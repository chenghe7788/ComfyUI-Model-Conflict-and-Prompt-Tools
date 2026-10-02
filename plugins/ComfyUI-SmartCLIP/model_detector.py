# -*- coding: utf-8 -*-
"""
SmartCLIP model detection
=========================
Two independent detection paths, because they answer two different questions:

1. ``detect_clip_arch(clip)`` - runtime truth.  Called inside the node, it looks
   at the CLIP object ComfyUI actually built and returns the base architecture
   family (sd15 / sd21 / sdxl / sd3 / flux / cascade / other / unknown).

   It deliberately never touches weights:

   * ``clip.cond_stage_model.__class__.__name__`` is exact
     (SD1ClipModel / SD2ClipModel / SDXLClipModel / SD3ClipModel / FluxClipModel
      / StableCascadeClipModel - verified against this ComfyUI checkout) and
     costs nothing;
   * ``clip.tokenizer`` class name and its sub-encoder attributes are the
     cross-check (``clip_g`` -> SDXL, ``t5xxl`` -> T5-based, ``clip_name`` ==
     "l"/"h" -> SD1.5/SD2);
   * calling ``state_dict()`` - as the draft this replaces did - is avoided on
     purpose: with a dynamic/mmap patcher it can materialise gigabytes of text
     encoder weights just to answer a string question.

2. ``detect_checkpoint(name)`` - pre-execution guess.  The frontend traces the
   CLIP wire back to its loader and sends the file name before anything runs, so
   the dialog is never stuck on "unknown".  This reads only the safetensors
   header (or a bounded byte scan for .pt/.ckpt) plus the file name, so it also
   reports the *flavour* (Pony / Illustrious / NoobAI / Krea 2) that the CLIP
   object cannot know.

Everything here returns a dict and never raises.
"""

import os
import re
import threading

try:  # only needed for the file-based path
    from safetensors import safe_open
except Exception:  # pragma: no cover
    safe_open = None

try:
    import folder_paths
except Exception:  # pragma: no cover
    folder_paths = None


# ======================================================================
# Catalogue
# ======================================================================

# family -> info.  "preset" is the key used in prompt_presets/presets.json.
FAMILY_INFO = {
    "sd15": {
        "label": "SD 1.5", "preset": "sd15", "score_tags": False,
        "note": "512 原生分辨率，单 CLIP-L 编码器",
    },
    "sd21": {
        "label": "SD 2.x", "preset": "sd15", "score_tags": False,
        "note": "1024 维 CLIP-H，提示词习惯与 SD1.5 接近",
    },
    "sdxl": {
        "label": "SDXL", "preset": "sdxl", "score_tags": False,
        "note": "1024 原生，双文本编码器（clip_l + clip_g）",
    },
    "pony": {
        "label": "Pony (SDXL)", "preset": "pony", "score_tags": True,
        "note": "SDXL 微调，提示词必须带 score_9 / score_8_up 等评分标签",
    },
    "illustrious": {
        "label": "Illustrious/NoobAI", "preset": "illustrious", "score_tags": False,
        "note": "SDXL 动漫微调，Danbooru 标签，不需要评分标签",
    },
    "sd3": {
        "label": "SD3 / SD3.5", "preset": "sd3", "score_tags": False,
        "note": "MMDiT，CLIP-L + CLIP-G + T5-XXL",
    },
    "flux": {
        "label": "FLUX", "preset": "flux", "score_tags": False,
        "note": "DiT，T5-XXL + CLIP-L，吃自然语言长句",
    },
    "cascade": {
        "label": "Stable Cascade", "preset": "generic", "score_tags": False,
        "note": "三级级联结构",
    },
    "krea2": {
        "label": "Krea 2", "preset": "generic", "score_tags": False,
        "note": "新一代 DiT（txtfusion），与 SD 系 LoRA 不通用",
    },
    "other": {
        "label": "其它架构", "preset": "generic", "score_tags": False,
        "note": "识别到非 SD 系文本编码器，按通用词库处理",
    },
    "unknown": {
        "label": "未识别", "preset": "generic", "score_tags": False,
        "note": "未能识别，弹窗给通用词库",
    },
}

# cond_stage_model class name -> family (verified against comfy/ in this checkout)
CLASS_FAMILY = {
    "SD1ClipModel": "sd15",
    "SD1CheckpointClipModel": "sd15",
    "SDClipModel": "sd15",
    "SD2ClipModel": "sd21",
    "SD2ClipHModel": "sd21",
    "SDXLClipModel": "sdxl",
    "SDXLRefinerClipModel": "sdxl",
    "SDXLClipG": "sdxl",
    "StableCascadeClipModel": "cascade",
    "SD3ClipModel": "sd3",
    "FluxClipModel": "flux",
    "Flux2ClipModel": "flux",
}

# tokenizer class name -> family (cross-check when the model class is wrapped)
TOKENIZER_FAMILY = {
    "SD1Tokenizer": "sd15",
    "SDTokenizer": "sd15",
    "SD2Tokenizer": "sd21",
    "SD2ClipHTokenizer": "sd21",
    "SDXLTokenizer": "sdxl",
    "SD3Tokenizer": "sd3",
    "FluxTokenizer": "flux",
    "Flux2Tokenizer": "flux",
    "StableCascadeTokenizer": "cascade",
}

# ---- name hints (flavour that only the file name can tell us) --------

HINT_PATTERNS = (
    ("pony", re.compile(r"pony|pdxl|_pxl", re.I)),
    ("illustrious", re.compile(r"illustrious|noob|ilff|nijijourney|hassaku", re.I)),
    ("krea2", re.compile(r"krea", re.I)),
    ("flux", re.compile(r"flux", re.I)),
    ("sd3", re.compile(r"\bsd3|sd3\.5|stable[-_ ]?diffusion[-_ ]?3", re.I)),
    ("sd15", re.compile(r"\bsd[-_ ]?1[._]?5|\bsd15|v1[-_ ]?5|1\.5", re.I)),
    ("sd21", re.compile(r"\bsd[-_ ]?2[._]?1|\bsd21|v2[-_ ]?1|2\.1", re.I)),
    ("sdxl", re.compile(r"sdxl|xl_base|xl_refiner|\bxl\b|[-_]xl[-_]|xl_?v?\d", re.I)),
)

# family hints that also change which preset set is right
FLAVOUR_HINTS = ("pony", "illustrious", "krea2")


def hint_from_name(name):
    """Best-effort family/flavour guess from a file name. Never raises."""
    text = os.path.basename(str(name or "")).lower()
    for family, pattern in HINT_PATTERNS:
        if pattern.search(text):
            return family
    return ""


def info_for(family):
    return FAMILY_INFO.get(family, FAMILY_INFO["unknown"])


def label_for(family):
    return info_for(family)["label"]


def preset_key_for(family, hint=""):
    """
    Which preset set to use.

    The runtime family wins for the *architecture*, but a flavour hint (pony /
    illustrious) is more specific - a Pony checkpoint is an SDXL model that wants
    score tags, so it must not fall back to the plain SDXL word list.
    """
    if hint in FLAVOUR_HINTS:
        base = info_for(family)
        # only trust the flavour when it does not contradict the runtime family
        if family in ("unknown", "other") or base["preset"] in ("sdxl", "generic"):
            return info_for(hint)["preset"]
    return info_for(family)["preset"]


# ======================================================================
# 1. Runtime detection (the CLIP object)
# ======================================================================

def _probe_tokenizer(tokenizer):
    """Attribute-level evidence from the tokenizer object."""
    evidence = []
    family = ""
    if tokenizer is None:
        return family, evidence

    cls = type(tokenizer).__name__
    if cls in TOKENIZER_FAMILY:
        family = TOKENIZER_FAMILY[cls]
        evidence.append("tokenizer=%s" % cls)
    else:
        evidence.append("tokenizer=%s" % cls)

    has_clip_g = hasattr(tokenizer, "clip_g")
    has_t5 = hasattr(tokenizer, "t5xxl")
    clip_name = getattr(tokenizer, "clip_name", None)

    if has_clip_g and not family:
        family = "sdxl"
    if has_t5 and not family:
        family = "sd3"          # T5 without clip_g is the SD3/DiT wiring
    if clip_name == "h" and family == "sd15":
        family = "sd21"
    if clip_name:
        evidence.append("clip_name=%s" % clip_name)
    if has_clip_g:
        evidence.append("has clip_g")
    if has_t5:
        evidence.append("has t5xxl")
    return family, evidence


def detect_clip_arch(clip):
    """
    Inspect a live CLIP object.

    -> {"family", "label", "preset", "score_tags", "evidence", "source"}
    """
    result = {"family": "unknown", "label": FAMILY_INFO["unknown"]["label"],
              "preset": "generic", "score_tags": False,
              "evidence": "", "source": "none"}

    if clip is None:
        result["evidence"] = "clip is None"
        return result

    evidence = []
    family = ""

    # ---- 1) the text encoder module ComfyUI built (exact) -------------
    try:
        csm = getattr(clip, "cond_stage_model", None)
        if csm is not None:
            cls = type(csm).__name__
            evidence.append("cond_stage_model=%s" % cls)
            family = CLASS_FAMILY.get(cls, "")
            if family:
                result["source"] = "cond_stage_model"
    except Exception as exc:                      # never let detection break a run
        evidence.append("cond_stage_model?%s" % type(exc).__name__)

    # ---- 2) tokenizer as cross-check / fallback ----------------------
    try:
        tok_family, tok_evidence = _probe_tokenizer(getattr(clip, "tokenizer", None))
        evidence.extend(tok_evidence)
        if not family and tok_family:
            family = tok_family
            result["source"] = "tokenizer"
    except Exception as exc:
        evidence.append("tokenizer?%s" % type(exc).__name__)

    # ---- 3) last resort: patcher model class name --------------------
    #     (still no weight access - this is just a class name)
    if not family:
        try:
            model = getattr(getattr(clip, "patcher", None), "model", None)
            cls = type(model).__name__ if model is not None else ""
            if cls:
                evidence.append("patcher.model=%s" % cls)
                if cls in CLASS_FAMILY:
                    family = CLASS_FAMILY[cls]
                    result["source"] = "patcher.model"
        except Exception as exc:
            evidence.append("patcher?%s" % type(exc).__name__)

    if not family:
        family = "unknown"

    info = info_for(family)
    result.update({
        "family": family,
        "label": info["label"],
        "preset": info["preset"],
        "score_tags": info["score_tags"],
        "note": info["note"],
        "evidence": "; ".join(evidence),
    })
    return result


# ======================================================================
# 2. File-based detection (before anything runs)
# ======================================================================

_FILE_CACHE = {}
_FILE_LOCK = threading.Lock()

# safetensors key markers, most specific first
_KEY_RULES = (
    ("flux", ("double_blocks", "single_blocks")),
    ("krea2", ("txtfusion", "attn.gate")),
    ("sd3", ("joint_blocks",)),
    ("sdxl", ("conditioner.embedders.1", "label_emb", "text_encoder_2")),
    ("sd15", ("cond_stage_model.transformer", "first_stage_model")),
)

# byte markers for .pt / .ckpt (torch.save writes key names before tensor data)
_BYTE_RULES = (
    (b"double_blocks", "flux"),
    (b"joint_blocks", "sd3"),
    (b"txtfusion", "krea2"),
    (b"conditioner.embedders.1", "sdxl"),
    (b"label_emb", "sdxl"),
    (b"cond_stage_model", "sd15"),
)

_SCAN_LIMIT = 6 * 1024 * 1024


def _model_roots(kind):
    folder = {"checkpoints": "checkpoints", "unet": "diffusion_models",
              "clip": "text_encoders", "text_encoders": "text_encoders"}.get(kind, kind)
    roots = []
    if folder_paths is not None:
        try:
            roots = [p for p in folder_paths.get_folder_paths(folder) if os.path.isdir(p)]
        except Exception:
            roots = []
    if not roots:
        guess = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "models", folder))
        if os.path.isdir(guess):
            roots = [guess]
    return roots


def resolve_model_path(kind, name):
    if not name:
        return None
    name = str(name)
    if os.path.isabs(name):
        return name if os.path.isfile(name) else None
    for root in _model_roots(kind):
        cand = os.path.join(root, name)
        if os.path.isfile(cand):
            return cand
    # basename search inside the folder (hand-written workflows quote bare names)
    base = os.path.basename(name.replace("\\", "/")).lower()
    for root in _model_roots(kind):
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if fn.lower() == base:
                    return os.path.join(dirpath, fn)
    return None


def _read_header_markers(path):
    """(markers, metadata) from a safetensors header; header only, no tensors."""
    if safe_open is None:
        return set(), {}
    with safe_open(path, framework="pt") as handle:
        meta = dict(handle.metadata() or {})
        keys = list(handle.keys())[:8000]
    blob = "\n".join(keys)
    found = set()
    for family, tokens in _KEY_RULES:
        if any(token in blob for token in tokens):
            found.add(family)
    return found, meta


def _read_byte_markers(path):
    found = set()
    meta_text = ""
    try:
        with open(path, "rb") as handle:
            data = handle.read(_SCAN_LIMIT)
        for marker, family in _BYTE_RULES:
            if marker in data:
                found.add(family)
        at = data.find(b"sd_checkpoint_name")
        if at >= 0:
            meta_text = data[max(0, at - 64): at + 256].decode("latin-1", "ignore")
    except Exception:
        pass
    return found, meta_text


def detect_checkpoint(kind, name):
    """
    Classify a model *file* without loading it.

    -> {"name", "family", "label", "preset", "score_tags", "hint", "evidence"}
    """
    hint = hint_from_name(name)
    family = ""
    evidence = []
    if hint:
        evidence.append("name~%s" % hint)

    path = resolve_model_path(kind, name)
    if path is None:
        # nothing on disk: the name hint is all we have
        family = hint or "unknown"
        info = info_for(family)
        return {"name": name, "family": family, "label": info["label"],
                "preset": preset_key_for(family, hint), "score_tags": info["score_tags"],
                "hint": hint, "evidence": "; ".join(evidence) or "file not found",
                "path": None}

    key = (path, int(os.path.getmtime(path)), os.path.getsize(path))
    with _FILE_LOCK:
        hit = _FILE_CACHE.get(path)
        if hit and hit["key"] == key:
            cached = dict(hit["value"])
            cached["cached"] = True
            return cached

    markers = set()
    try:
        if path.lower().endswith(".safetensors"):
            markers, meta = _read_header_markers(path)
            arch = str(meta.get("modelspec.architecture", "")).lower()
            base = str(meta.get("ss_base_model_version", "")).lower()
            meta_text = "%s %s" % (arch, base)
        else:
            markers, meta_text = _read_byte_markers(path)
        if meta_text:
            meta_hint = hint_from_name(meta_text)
            if meta_hint:
                evidence.append("meta~%s" % meta_hint)
                if not hint:
                    hint = meta_hint
    except Exception as exc:
        evidence.append("read failed: %s" % type(exc).__name__)

    # the file's own structure is stronger evidence than the name.
    # Order matters: an SDXL checkpoint also carries first_stage_model keys, so
    # the looser sd15 rule has to be evaluated last.
    for family_name in ("flux", "krea2", "sd3", "sdxl", "sd15"):
        if family_name in markers:
            family = family_name
            evidence.append("keys~%s" % family_name)
            break

    if not family:
        family = hint or "unknown"

    # a Pony/Illustrious checkpoint is structurally SDXL; keep the architecture
    # but let the flavour drive the preset selection
    if family == "sdxl" and hint in FLAVOUR_HINTS:
        evidence.append("flavour=%s" % hint)

    info = info_for(family)
    value = {
        "name": name, "family": family, "label": info["label"],
        "preset": preset_key_for(family, hint), "score_tags": info["score_tags"],
        "hint": hint, "evidence": "; ".join(evidence), "path": path,
    }
    with _FILE_LOCK:
        _FILE_CACHE[path] = {"key": key, "value": value}
    return value


def clear_cache():
    with _FILE_LOCK:
        _FILE_CACHE.clear()
