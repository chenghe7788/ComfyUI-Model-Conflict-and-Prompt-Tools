# -*- coding: utf-8 -*-
"""
SmartCLIP embedding compatibility
=================================
A word list may reference a textual inversion - ``embedding:EasyNegative`` - and
the entry itself cannot say whether that word is usable right now.  Two things
decide it, and both live outside the preset file:

  * **installed?**  the referenced file has to exist in ``models/embeddings``;
    the word lists are shipped with entries the user may never have downloaded.
  * **same CLIP?**  a textual inversion is trained against one text encoder.
    ``clip_g`` + ``clip_l`` means SDXL's dual encoder, a single 768-wide
    ``emb_params`` means SD 1.5, 1024 means SD 2.x.  Feeding an SDXL embedding
    to an SD 1.5 base is the silent "does nothing / garbles the prompt" case.

This module answers both for the entries of one loaded word list, and returns a
plain dict the dialog can render as a badge.  It never loads model weights: a
safetensors text encoder is inspected through its JSON header (the file's first
few KB) and a ``.pt`` textual inversion through a byte scan of its head, exactly
like the model-conflict engine does.

The compatibility groups mirror ``model_conflict.py``'s ``FAMILY_COMPAT`` on
purpose - two plugins on one machine must not disagree about the same file.

Nothing here needs a third-party package.
"""

import json
import os
import re
import threading

EMBEDDING_PREFIX = "embedding:"

# "embedding:EasyNegative", "embedding:写实/foo", "embedding:foo.pt"
_EMBEDDING_RE = re.compile(r"^\s*embedding:\s*([^,\s)\]}]+)\s*$", re.I)

# The same reference inside a longer prompt ("..., embedding:badhandv4, ...").
# It stops at ":" so that "(embedding:badhandv4:1.2)" captures the name rather
# than the weight ComfyUI parses off the end.
_MULTI_RE = re.compile(r"embedding:\s*([^,\s)\]\n:]+)", re.I)

# ":1.2" / ":0.8" / ":-0.5" after a name is a ComfyUI weight, not part of it.
_WEIGHT_RE = re.compile(r":-?\d+(?:\.\d+)?$")


def clean_reference(name):
    """Drop weight syntax and trailing punctuation from a referenced name."""
    text = str(name or "").strip().strip("\"'").rstrip(".。，")
    return _WEIGHT_RE.sub("", text)

# What a prompt reference may be missing, and what folder_paths would list.
_EXTENSIONS = (".safetensors", ".pt", ".pth", ".ckpt", ".bin")

TI_SD15 = "ti_sd"
TI_SD21 = "ti_sd21"
TI_SDXL = "ti_sdxl"
TI_UNKNOWN = "ti_unknown"

TI_SHORT = {
    TI_SD15: "TI-SD1.5",
    TI_SD21: "TI-SD2",
    TI_SDXL: "TI-SDXL",
    TI_UNKNOWN: "TI-?",
}
TI_LABEL = {
    TI_SD15: "SD1.5 词嵌入",
    TI_SD21: "SD2.x 词嵌入",
    TI_SDXL: "SDXL 词嵌入",
    TI_UNKNOWN: "未识别的词嵌入",
}

# preset key -> the textual inversions that CLIP can actually load.
# sd3 / flux are absent on purpose: their text encoders are not SD CLIPs, so no
# verdict is claimed for them (the entry is only checked for being installed).
#
# A TI_SD15 entry under an SDXL preset is in the table because CLIP-L can load
# it, but "compatible" would be a lie: SDXL encodes with two text encoders
# (CLIP-L 768 + OpenCLIP-bigG 1280), ComfyUI feeds the 768-wide inversion to
# CLIP-L and drops it on the CLIP-G pass, logging
#   "shape mismatch when trying to apply embedding, embedding will be ignored
#    768 != 1280"
# So it reaches exactly half the conditioning.  PARTIAL below is that state -
# usable, quieter than a conflict, but not the same thing as a full match.
ACCEPTED = {
    "sd15": {TI_SD15},
    "sd21": {TI_SD21},
    "sdxl": {TI_SD15, TI_SDXL},
    "pony": {TI_SD15, TI_SDXL},
    "illustrious": {TI_SD15, TI_SDXL},
}

# (preset, arch) pairs that load, but only reach one of SDXL's two encoders.
PARTIAL = {(family, TI_SD15) for family in ("sdxl", "pony", "illustrious")}

FAMILY_LABEL = {
    "generic": "通用",
    "sd15": "SD 1.5",
    "sd21": "SD 2.x",
    "sdxl": "SDXL",
    "pony": "Pony (SDXL)",
    "illustrious": "Illustrious (SDXL)",
    "sd3": "SD3",
    "flux": "FLUX",
    "krea2": "Krea 2",
}

# Name hints, used only when the file itself is inconclusive.  Kept small: a
# wrong guess is worse than "unknown", because "unknown" claims nothing.
_XL_HINT = re.compile(r"xl|pony|pdxl|illustrious|noob|sd_xl|sdxl", re.I)
_SD15_HINT = re.compile(r"(^|[^a-z])v?1[-_.]?5|sd15|sd_15|768", re.I)

_HEAD_BYTES = 8 * 1024 * 1024
_MAX_HEADER = 64 * 1024 * 1024

_LOCK = threading.Lock()
_FILE_CACHE = {}
_DIR_CACHE = {}

try:                                    # only inside ComfyUI
    import folder_paths                 # type: ignore
except Exception:                       # pragma: no cover - standalone
    folder_paths = None


# ----------------------------------------------------------------------
# Where the embeddings live
# ----------------------------------------------------------------------

def _fallback_root():
    """``<ComfyUI>/models``, derived from this file's location."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", "models"))


def embedding_dirs():
    """Every folder ComfyUI would search for a textual inversion."""
    # Test / tooling escape hatch: point the checker at another models folder
    # without needing a ComfyUI install (tests/probe_embeddings.py uses it).
    # It *replaces* discovery, so a test is not polluted by the real install.
    override = os.environ.get("SMARTCLIP_EMBEDDINGS_DIR")
    if override:
        return [override]

    roots = []
    if folder_paths is not None:
        try:
            roots.extend(folder_paths.get_folder_paths("embeddings"))
        except Exception:
            pass
    if not roots:
        roots.append(os.path.join(_fallback_root(), "embeddings"))
    out = []
    for root in roots:
        if root and root not in out:
            out.append(root)
    return out


def _dir_stamp(directory):
    try:
        st = os.stat(directory)
        return (int(st.st_mtime), int(st.st_size))
    except OSError:
        return None


def _index_one(directory):
    """
    ``{lowercased basename: absolute path}`` for one folder (cached by stat).

    The folder is walked rather than asked of ``folder_paths``: that listing
    belongs to ComfyUI's own roots and would otherwise be applied to a folder it
    knows nothing about (which is exactly how an extra search path or a test
    override ends up resolving names to files that do not exist).
    """
    stamp = _dir_stamp(directory)
    if stamp is None:
        return {}
    with _LOCK:
        hit = _DIR_CACHE.get(directory)
        if hit is not None and hit[0] == stamp:
            return hit[1]

    index = {}
    for dirpath, _dirs, files in os.walk(directory):
        for filename in files:
            if os.path.splitext(filename)[1].lower() not in _EXTENSIONS:
                continue
            index.setdefault(filename.lower(), os.path.join(dirpath, filename))

    with _LOCK:
        _DIR_CACHE[directory] = (stamp, index)
    return index


def embedding_index():
    """
    Every installed textual inversion, across every root ComfyUI searches.

    Cached per folder and rebuilt when a folder changes, so dropping a file in
    does not need a restart. On a name collision the earlier root wins, which is
    the order ComfyUI itself resolves model names in.
    """
    merged = {}
    for directory in embedding_dirs():
        for key, path in _index_one(directory).items():
            merged.setdefault(key, path)
    return merged


def resolve(name):
    """
    Absolute path of an installed textual inversion, or ``None``.

    Forgiving on purpose: the prompt may quote a subfolder, drop the extension
    (the normal case: ``embedding:EasyNegative``), or use the other slash.
    """
    if not name:
        return None
    clean = str(name).strip().strip("\"'").replace("\\", "/").lstrip("/")
    index = embedding_index()
    if not index:
        return None

    # A name that carries a folder ("embedding:sub/foo") has to match that
    # folder: ComfyUI joins it onto each embeddings root verbatim, so quietly
    # falling back to a same-named file elsewhere would call a reference
    # "installed" that ComfyUI drops without a word.
    if "/" in clean:
        wanted = "/" + clean.lower()
        suffixes = [wanted]
        if not os.path.splitext(clean)[1]:
            suffixes += [wanted + ext for ext in _EXTENSIONS]
        for path in index.values():
            posix = path.replace("\\", "/").lower()
            if any(posix.endswith(suffix) for suffix in suffixes):
                return path
        return None

    base = os.path.basename(clean).lower()
    found = index.get(base)
    if found:
        return found
    if not os.path.splitext(base)[1]:
        for ext in _EXTENSIONS:
            found = index.get(base + ext)
            if found:
                return found
    return None


# ----------------------------------------------------------------------
# Reading an embedding's architecture
# ----------------------------------------------------------------------

def _stat_key(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (path, int(st.st_mtime), int(st.st_size))


def _read_safetensors_header(path):
    """
    ``(key_names, shapes, metadata)`` from a safetensors header, or ``None``.

    The format is: 8-byte little-endian header length, then that many bytes of
    JSON (a ``__metadata__`` entry plus one entry per tensor).  Only the header
    is read - the tensors themselves are never touched.
    """
    try:
        with open(path, "rb") as handle:
            raw = handle.read(8)
            if len(raw) != 8:
                return None
            length = int.from_bytes(raw, "little")
            if length <= 0 or length > _MAX_HEADER:
                return None
            blob = handle.read(length)
            if len(blob) != length:
                return None
        data = json.loads(blob.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    metadata = data.get("__metadata__") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    keys = []
    shapes = {}
    for key, value in data.items():
        if key == "__metadata__":
            continue
        keys.append(key)
        if isinstance(value, dict) and isinstance(value.get("shape"), list):
            shapes[key] = value["shape"]
    return keys, shapes, metadata


def _read_torch_markers(path):
    """Byte scan of a ``.pt`` / ``.ckpt`` head: torch.save writes keys first."""
    found = set()
    text = ""
    try:
        with open(path, "rb") as handle:
            data = handle.read(_HEAD_BYTES)
    except Exception:
        return found, text
    for marker in (b"clip_g", b"clip_l", b"emb_params", b"sd_checkpoint_name"):
        if marker in data:
            found.add(marker.decode("ascii"))
    at = data.find(b"sd_checkpoint_name")
    if at >= 0:
        text = data[max(0, at - 64):at + 320].decode("latin-1", "ignore")
    return found, text


def _width_from_shapes(shapes):
    """The textual inversion's token width: 768=SD1.5, 1024=SD2.x, 1280=SDXL."""
    for key, shape in (shapes or {}).items():
        if "emb_params" in key and len(shape) == 2:
            return int(shape[1])
    for key, shape in (shapes or {}).items():
        if key in ("clip_l", "clip_g") and len(shape) == 2:
            return int(shape[1])
    return None


def classify(path):
    """
    ``{"arch","short","label","evidence"}`` for one installed embedding file.

    Unknown is a valid, deliberate answer: a `.pt` textual inversion whose head
    carries no usable marker simply is not guessed at.
    """
    key = _stat_key(path)
    if key is None:
        return {"arch": TI_UNKNOWN, "short": TI_SHORT[TI_UNKNOWN],
                "label": TI_LABEL[TI_UNKNOWN], "evidence": "文件不存在"}
    with _LOCK:
        hit = _FILE_CACHE.get(path)
        if hit is not None and hit[0] == key:
            return hit[1]

    arch = TI_UNKNOWN
    evidence = ""
    name = os.path.basename(path)

    if path.lower().endswith(".safetensors"):
        header = _read_safetensors_header(path)
        if header is not None:
            keys, shapes, metadata = header
            joined = "\n".join(keys)
            width = _width_from_shapes(shapes)
            if "clip_g" in joined:
                arch = TI_SDXL
                evidence = "clip_g + clip_l（SDXL 双编码器）"
            elif width == 1024:
                arch = TI_SD21
                evidence = "emb_params 1024 维"
            elif width == 768:
                arch = TI_SD15
                evidence = "emb_params 768 维"
            elif width == 1280:
                arch = TI_SDXL
                evidence = "emb_params 1280 维"
            elif "clip_l" in joined:
                arch = TI_SD15
                evidence = "仅 clip_l（SD1.5 文本编码器）"
            hint = str(metadata.get("modelspec.architecture", "")) + " " + name
            if arch == TI_UNKNOWN and hint.strip():
                arch, evidence = _from_name(hint, "文件名/元数据推测")
    else:
        found, text = _read_torch_markers(path)
        if "clip_g" in found:
            arch = TI_SDXL
            evidence = "clip_g（字节标记）"
        elif "emb_params" in found or "sd_checkpoint_name" in found:
            arch, evidence = _from_name(name + " " + text, "文件名/内嵌名推测")
            if arch == TI_UNKNOWN:
                # Same default the model-conflict engine uses: a .pt textual
                # inversion without an SDXL marker is overwhelmingly SD1.5-era,
                # and saying so is far more useful than "unknown".
                arch = TI_SD15
                evidence = ".pt 词嵌入且无 SDXL 标记（按 SD1.5 处理）"
        else:
            arch, evidence = _from_name(name, "文件名推测")

    record = {
        "arch": arch,
        "short": TI_SHORT[arch],
        "label": TI_LABEL[arch],
        "evidence": evidence,
    }
    with _LOCK:
        _FILE_CACHE[path] = (key, record)
    return record


def _from_name(text, evidence):
    if not text:
        return TI_UNKNOWN, ""
    if _XL_HINT.search(text):
        return TI_SDXL, evidence
    if _SD15_HINT.search(text):
        return TI_SD15, evidence
    return TI_UNKNOWN, ""


# ----------------------------------------------------------------------
# The verdict for one word-list entry
# ----------------------------------------------------------------------

def embedding_name(text):
    """The referenced embedding name, or ``""`` when the entry is not one."""
    match = _EMBEDDING_RE.match(str(text or ""))
    return clean_reference(match.group(1)) if match else ""


def reference_name(text):
    """
    The textual inversion an entry points at, or ``""``.

    Two spellings mean the same thing to ComfyUI, and both occur in real prompt
    files: the explicit ``embedding:EasyNegative``, and the bare file name
    ``EasyNegative`` (which is how most downloaded negative prompts are written).
    A bare name only counts when it IS an installed embedding file - matching a
    whole entry against the file list is what keeps ordinary words such as
    "masterpiece" from being mistaken for one.
    """
    name = embedding_name(text)
    if name:
        return name

    token = str(text or "").strip().strip("\"'")
    if not token or len(token) > 160:
        return ""
    if any(sep in token for sep in (",", "(", ")", "[", "]", "{", "}", "\n", ":")):
        return ""
    lower = token.lower()
    index = embedding_index()
    for ext in ("",) + _EXTENSIONS:
        if (lower + ext) in index:
            return token
    return ""


def _verdict(name, reference, preset):
    """The badge record for one referenced embedding name."""
    family = str(preset or "").strip().lower()
    accepted = ACCEPTED.get(family)
    family_label = FAMILY_LABEL.get(family, family or "未识别")

    path = resolve(name)
    if path is None:
        return {
            "kind": "embedding",
            "name": name,
            "reference": reference,
            "state": "missing",
            "arch": TI_UNKNOWN,
            "short": "未安装",
            "why": "models/embeddings 里没有这个文件（词条需要自己下载）",
        }

    info = classify(path)
    arch = info["arch"]
    if arch == TI_UNKNOWN:
        state = "unknown"
        why = "已安装，但架构未识别，不判断兼容性"
    elif (family, arch) in PARTIAL:
        state = "partial"
        why = ("半兼容：本项是 768 维的 SD1.5 词嵌入，%s 的 CLIP-L 能吃下它，"
               "但 CLIP-G(1280) 会忽略并打印 shape mismatch 警告 —— 只有一半"
               "文本编码器生效（本项 %s）" % (family_label, info["short"]))
    elif family in ("", "generic", "unknown"):
        # The base family is not known well enough to name a CLIP.  Claiming
        # "compatible" would be a lie, and so would "incompatible".
        state = "unknown"
        why = "已安装，但当前底模族无法按 SD CLIP 判断兼容性，不做判断"
    elif family in ("sd3", "flux") and arch == TI_SD15:
        # Both keep a 768-wide CLIP-L next to their big encoder (SD3: clip_l +
        # clip_g + t5xxl, FLUX: clip_l + t5xxl), so a 768 TI lands on CLIP-L
        # only - the same half effect as on SDXL.
        state = "partial"
        why = ("半兼容：%s 里只有 CLIP-L(768) 会吃下这个 768 维词嵌入，"
               "其它文本编码器（T5 / CLIP-G）不吃它（本项 %s）" % (family_label, info["short"]))
    elif family == "flux" and arch == TI_SDXL:
        state = "incompatible"
        why = ("与当前 FLUX 不兼容：FLUX 的文本编码器是 CLIP-L(768) + T5，"
               "没有 1280 维那一路（本项 %s）" % info["label"])
    elif accepted is not None and arch in accepted:
        state = "ok"
        why = "与当前 %s 兼容（%s）" % (family_label, info["short"])
    elif accepted is None:
        # SD3 / FLUX are handled above; what lands here is cascade / krea2 / an
        # unknown preset.  This table cannot speak for their text encoders, so
        # the only honest claim is "the file is there".
        state = "ok"
        why = "已安装；%s 的文本编码器与本表未对齐，不判断架构兼容性" % family_label
    else:
        state = "incompatible"
        why = "与当前 %s 不兼容（本项 %s）" % (family_label, info["label"])
    return {
        "kind": "embedding",
        "name": name,
        "reference": reference,
        "state": state,
        "arch": arch,
        "short": info["short"] if state != "missing" else "未安装",
        "why": why,
    }


# How bad each state is, so a prompt quoting several embeddings can be labelled
# by its worst one.  A *known* half effect outranks "could not tell": an item
# that will definitely print a shape-mismatch warning deserves the badge more
# than one whose architecture is merely unknown.
_SEVERITY = {"ok": 0, "unknown": 1, "partial": 2, "missing": 3, "incompatible": 4}
_STATE_LABEL = {"ok": "兼容", "partial": "半兼容", "unknown": "未知",
                "missing": "未安装", "incompatible": "不兼容"}


def annotate(text, preset):
    """
    Badge data for one word-list entry, or ``None`` for ordinary words.

    Handles three shapes:
      * the entry IS a reference - ``embedding:EasyNegative`` or a bare
        ``EasyNegative`` (an installed file name);
      * the entry is a whole negative prompt that *contains* ``embedding:...``
        references - very common after importing a workflow, so the entry is
        labelled by the worst of them;
      * anything else, which gets no badge at all.

    ``state`` is one of:
      ``ok``            installed and loadable by this CLIP
      ``partial``       installed and loadable, but only by CLIP-L (SDXL halves it)
      ``incompatible``  installed, but trained for another text encoder
      ``missing``       not installed
      ``unknown``       installed, architecture not identifiable (or base family unknown)
    """
    explicit = embedding_name(text)
    name = explicit or reference_name(text)
    if name:
        return _verdict(name, "embedding:" if explicit else "bare", preset)

    # A longer prompt that quotes embeddings inside it.
    names = []
    for match in _MULTI_RE.finditer(str(text or "")):
        found = clean_reference(match.group(1))
        if found and found not in names:
            names.append(found)
    if not names:
        return None

    verdicts = [_verdict(item, "embedding:", preset) for item in names]
    # An unregistered state must not be silently swallowed by a known one.
    worst = max(verdicts, key=lambda v: _SEVERITY.get(v["state"], 5))
    family_label = FAMILY_LABEL.get(str(preset or "").strip().lower(), preset or "未识别")
    if worst["state"] == "ok":
        why = "%d 个词嵌入都与当前 %s 兼容" % (len(names), family_label)
    else:
        marked = [v["name"] for v in verdicts if v["state"] == worst["state"]]
        why = "%d 个词嵌入中 %d 个%s：%s" % (
            len(names), len(marked), _STATE_LABEL.get(worst["state"], worst["state"]),
            "、".join(marked))
    return {
        "kind": "embedding",
        "name": names[0] if len(names) == 1 else "%d 个词嵌入" % len(names),
        "reference": "mixed",
        "state": worst["state"],
        "arch": worst["arch"],
        "short": worst["short"] if len(names) == 1 else "%d 个词嵌入" % len(names),
        "why": why,
    }


def annotate_categories(categories, preset):
    """
    ``(annotations, stats)`` for every embedding entry of a loaded word list.

    ``annotations`` is keyed by the exact entry text the dialog renders, so the
    frontend only has to look the string up.  Ordinary words are simply absent.
    """
    annotations = {}
    stats = {"total": 0, "ok": 0, "partial": 0, "incompatible": 0, "missing": 0, "unknown": 0}
    for prompts in (categories or {}).values():
        for text in prompts or []:
            text = str(text)
            # Cheap pre-filter: only "embedding:..." or a name that matches an
            # installed file can be a textual inversion.
            if EMBEDDING_PREFIX not in text.lower() and not reference_name(text):
                continue
            try:
                info = annotate(text, preset)
            except Exception:
                info = None
            if not info:
                continue
            annotations[text] = info
            stats["total"] += 1
            stats[info["state"]] = stats.get(info["state"], 0) + 1
    return annotations, stats


def info():
    """Diagnostics for /smart_clip/info."""
    index = embedding_index()
    return {
        "dirs": embedding_dirs(),
        "count": len(index),
        "families": {key: sorted(value) for key, value in ACCEPTED.items()},
    }


def clear_cache():
    with _LOCK:
        _FILE_CACHE.clear()
        _DIR_CACHE.clear()
    return True
