# -*- coding: utf-8 -*-
"""
SmartCLIP: which base model is the *workflow* actually running?
==============================================================

Every embedding verdict ("compatible / half / incompatible / unknown") is a
statement about one thing: the text encoder of the base model the prompt is
going to be encoded with.  The word list cannot carry that, so the frontend
traces the CLIP wire back to a loader and asks /smart_clip/detect - that is the
normal path and it stays authoritative, because it looks at the canvas the user
is editing right now.

It is not, however, always available.  A stock CLIPTextEncode whose CLIP wire
runs through a LoRA stack, a page that loaded while ComfyUI was still starting,
a browser tab that kept a stale bundle: all of them send ``generic``, and then
every entry in the embedding picker degrades to "unknown" - honest, but useless
for the one question the picker exists to answer.  (The log meanwhile fills up
with ``shape mismatch ... 768 != 1280``.)

This module answers the same question from the server side, and is only
consulted when the client has no verdict of its own:

    ComfyUI's prompt queue / history  ->  the loader nodes of the graph that
    actually ran  ->  model_detector.detect_checkpoint()  ->  preset key

Nothing here loads weights (the detector reads file headers only) and nothing
raises: an empty queue, a workflow without a loader, or an unreadable file all
end up as "no answer", which leaves the client's verdict untouched.

Keep this file ASCII-only.
"""

import logging

try:                       # normal case: loaded as a package by ComfyUI
    from . import model_detector
except ImportError:        # standalone import (tests / tooling)
    import model_detector

log = logging.getLogger(__name__)

# Preset keys that mean "the caller could not answer".  "" and "unknown" are
# what an unidentified base looks like; "generic" is what ComfyUI_SmartCLIP
# hands out for cascade / krea2 / an unreadable header.
NO_VERDICT = ("", "generic", "unknown")

# class_type -> (input field holding the file name, folder kind for the detector)
PROMPT_LOADERS = (
    ("CheckpointLoaderSimple", "ckpt_name", "checkpoints"),
    ("CheckpointLoader", "ckpt_name", "checkpoints"),
    ("UNETLoader", "unet_name", "diffusion_models"),
    ("UnetLoaderGGUF", "unet_name", "diffusion_models"),
    ("CLIPLoader", "clip_name", "text_encoders"),
    ("DualCLIPLoader", "clip_name1", "text_encoders"),
)

_LOADER_TABLE = {
    class_type: (field, kind) for class_type, field, kind in PROMPT_LOADERS
}

# A workflow may wire several loaders.  The checkpoint is the model the whole
# graph is built on; a bare UNET or CLIP loader is only a hint about it.
_LOADER_RANK = {"checkpoints": 0, "diffusion_models": 1, "text_encoders": 2}

# "None" is what ComfyUI's own loaders write for "nothing selected"; the last
# two are the same idea in Chinese (escaped to keep this file ASCII-only).
_SENTINELS = frozenset(("", "none", "null", "undefined", "n/a",
                        "\u65e0", "\u7a7a"))


# ----------------------------------------------------------------------
# What did ComfyUI last run?
# ----------------------------------------------------------------------

def _prompt_queue():
    """The running PromptQueue, or ``None`` when not inside the server."""
    try:
        import server
        return getattr(server.PromptServer.instance, "prompt_queue", None)
    except Exception:
        return None


def _queue_prompts():
    """
    Prompt graphs to look at, most relevant first: what is running now, what is
    queued next, then the most recently finished one.

    Each entry is the ``(number, prompt_id, prompt, extra_data, outputs)`` tuple
    PromptQueue stores; only the graph itself (index 2) is of interest.
    """
    queue = _prompt_queue()
    if queue is None:
        return []

    found = []

    def take(item):
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            return
        prompt = item[2]
        if isinstance(prompt, dict) and prompt:
            found.append(prompt)

    for entries in (list(getattr(queue, "currently_running", {}).values()),
                    _sorted_queue(queue)):
        for item in entries:
            try:
                take(item)
            except Exception:
                continue
    take(_newest_history(queue))
    return found


def _sorted_queue(queue):
    """The pending queue as a list; heapq order = the order they will run."""
    try:
        return sorted(list(getattr(queue, "queue", []) or []))
    except Exception:
        return []


def _newest_history(queue):
    """The queue tuple of the most recently finished prompt, or ``None``."""
    try:
        history = getattr(queue, "history", None) or {}
    except Exception:
        return None
    best = None
    best_number = None
    for entry in history.values():
        if not isinstance(entry, dict):
            continue
        item = entry.get("prompt")
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        number = item[0] if isinstance(item[0], (int, float)) else 0
        if best_number is None or number > best_number:
            best_number = number
            best = item
    return best


# ----------------------------------------------------------------------
# Which loader does that graph name?
# ----------------------------------------------------------------------

def _loader_candidates(prompt):
    """``[(rank, kind, name, class_type)]`` for one prompt graph, best first."""
    out = []
    if not isinstance(prompt, dict):
        return out
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type") or "")
        spec = _LOADER_TABLE.get(class_type)
        if spec is None:
            continue
        field, kind = spec
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        name = inputs.get(field)
        if not isinstance(name, str) or name.strip().lower() in _SENTINELS:
            continue
        out.append((_LOADER_RANK.get(kind, 9), kind, name.strip(), class_type))
    out.sort(key=lambda row: row[0])
    return out


def workflow_loaders(limit=8):
    """
    Model files the newest prompt references, best first.

    Only the newest prompt contributes: an older run of a different workflow
    would answer a question nobody asked.
    """
    rows = []
    seen = set()
    for prompt in _queue_prompts():
        for row in _loader_candidates(prompt):
            key = (row[1], row[2])
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
            if len(rows) >= limit:
                return rows
        if rows:
            break
    return rows


def workflow_model():
    """
    The detector payload for the model ComfyUI last ran, plus ``source`` and the
    ``class_type`` it came from - or ``None`` when nothing can be said.
    """
    for _rank, kind, name, class_type in workflow_loaders():
        try:
            info = model_detector.detect_checkpoint(kind, name)
        except Exception as exc:              # never let a bad file break a route
            log.warning("[SmartCLIP] workflow detect failed for %s: %s", name, exc)
            continue
        if not isinstance(info, dict):
            continue
        if str(info.get("family") or "").strip().lower() in ("", "unknown"):
            # Unreadable / unrecognised: the next loader may still know.
            continue
        info = dict(info)
        info["source"] = "workflow"
        info["class_type"] = class_type
        return info
    return None


def resolve_preset(client_family=""):
    """
    ``(preset, source)`` - the family key the embedding verdicts should be
    judged against.

    ``("...", "client")``    the caller had a real verdict; it always wins,
                             because it sees the canvas being edited right now.
    ``("...", "workflow")``  the caller had none and the last run supplied it.
    ``("generic", "none")``  nobody can say; the caller keeps its generic list.
    """
    clean = str(client_family or "").strip().lower()
    if clean not in NO_VERDICT:
        return clean, "client"

    info = workflow_model()
    preset = str((info or {}).get("preset") or "").strip().lower()
    if preset and preset not in NO_VERDICT:
        return preset, "workflow"
    if info and preset == "generic":
        # A recognised non-SD base (cascade / krea2): there is still no CLIP
        # verdict to give, but the dialog should at least name the right family.
        return "generic", "workflow"
    return clean or "generic", "none"


def info():
    """Diagnostics for /smart_clip/info - what the server thinks is loaded."""
    loaders = workflow_loaders()
    return {
        "loaders": [{"kind": kind, "name": name, "class_type": class_type}
                    for _rank, kind, name, class_type in loaders],
        "model": workflow_model(),
    }
