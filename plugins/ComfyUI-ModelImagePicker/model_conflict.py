# -*- coding: utf-8 -*-
"""
Model Conflict engine
=====================
Answers one question for every model file ComfyUI can load:

    "which architecture family does this file belong to, and does it clash with
     the architecture the rest of the workflow is built on?"

This is deliberately broader than "LoRA vs base model": checkpoints, LoRAs, VAEs,
textual-inversion embeddings, ControlNets, UNets/diffusion models and text
encoders are all classified, because every one of them can be fed to a base
model it was never trained for.

Detection is calibrated against the real files found on this machine
(33 checkpoints / 97 LoRAs / 10 VAEs / 12 embeddings), which is why the rules
below are key-shape based rather than name based:

  * SDXL vs SD1.5 LoRA, both written in kohya naming, is decided by
    ``transformer_blocks_<N>`` with N >= 2 (SD 1.5 only ever has index 0) plus
    the second text encoder (``lora_te2``) and the 4th down/up block
    (``down_blocks_3`` / ``up_blocks_3``), which only SD 1.5 has.
  * Krea 2 and FLUX LoRAs both look "blocky"; Krea 2 is identified by the
    ``txtfusion`` / ``attn.gate`` keys, FLUX by ``double_blocks``.
  * A VAE is SD-family when it has ``quant_conv`` (4-channel latent) and
    FLUX when it uses diffusers-style ``encoder.down_blocks`` (16-channel
    latent).  Those two really cannot be swapped, so they are reported as a
    hard conflict.
  * SDXL textual inversions carry ``clip_g`` + ``clip_l``; SD1.5 ones carry a
    single ``emb_params`` of width 768.  An SDXL embedding on an SD1.5 base is
    exactly the kind of silent garbage this feature is meant to expose.

Everything is cached per (path, mtime, size) and every read is header-only, so
classifying 100 LoRAs costs a few hundred milliseconds once.

This module never raises and never blocks: an unreadable file is simply
reported as UNKNOWN, and UNKNOWN is never painted as a conflict.
"""

import os
import re
import threading

try:  # present when running inside ComfyUI
    import folder_paths
except Exception:  # standalone (tests, tooling)
    folder_paths = None

try:
    from safetensors import safe_open
except Exception:
    safe_open = None


# ======================================================================
# Architecture catalogue
# ======================================================================

ARCH_SD15 = "SD15"
ARCH_SD21 = "SD21"
ARCH_SDXL = "SDXL"
ARCH_PONY = "PONY"
ARCH_ILLUSTRIOUS = "ILLUSTRIOUS"
ARCH_SD3 = "SD3"
ARCH_FLUX = "FLUX"
ARCH_KREA2 = "KREA2"
ARCH_ANIMA = "ANIMA"
ARCH_MINIMAX = "MINIMAX"
ARCH_SDVAE = "SDVAE"
ARCH_FLUXVAE = "FLUXVAE"
ARCH_TI_SD15 = "TI_SD15"
ARCH_TI_SD21 = "TI_SD21"
ARCH_TI_SDXL = "TI_SDXL"
ARCH_UNIVERSAL = "UNIVERSAL"
ARCH_UNKNOWN = "UNKNOWN"

# family == the compatibility group.  Pony / Illustrious / NoobAI live in the
# SDXL group because in practice their LoRAs are used interchangeably.
ARCH_INFO = {
    ARCH_SD15:        {"label": "SD 1.5",                 "short": "SD1.5",    "family": "sd15"},
    ARCH_SD21:        {"label": "SD 2.x",                 "short": "SD2",      "family": "sd21"},
    ARCH_SDXL:        {"label": "SDXL",                   "short": "SDXL",     "family": "sdxl"},
    ARCH_PONY:        {"label": "Pony (SDXL)",            "short": "Pony",     "family": "sdxl"},
    ARCH_ILLUSTRIOUS: {"label": "Illustrious/NoobAI",     "short": "ILL",      "family": "sdxl"},
    ARCH_SD3:         {"label": "SD3 / SD3.5",            "short": "SD3",      "family": "sd3"},
    ARCH_FLUX:        {"label": "FLUX",                   "short": "FLUX",     "family": "flux"},
    ARCH_KREA2:       {"label": "Krea 2",                 "short": "Krea2",    "family": "krea2"},
    ARCH_ANIMA:       {"label": "Anima",                  "short": "Anima",    "family": "anima"},
    ARCH_MINIMAX:     {"label": "MiniMax H3（视频）",       "short": "H3",       "family": "minimax"},
    ARCH_SDVAE:       {"label": "SD VAE (1.5/2/SDXL 通用)", "short": "SD VAE", "family": "sd_vae"},
    ARCH_FLUXVAE:     {"label": "FLUX VAE (16 通道)",      "short": "FLUX VAE", "family": "flux"},
    ARCH_TI_SD15:     {"label": "SD1.5 词嵌入",            "short": "TI-SD1.5", "family": "ti_sd"},
    ARCH_TI_SD21:     {"label": "SD2.x 词嵌入",            "short": "TI-SD2",   "family": "ti_sd21"},
    ARCH_TI_SDXL:     {"label": "SDXL 词嵌入",             "short": "TI-SDXL",  "family": "sdxl"},
    ARCH_UNIVERSAL:   {"label": "通用（不受架构限制）",      "short": "通用",     "family": "universal"},
    ARCH_UNKNOWN:     {"label": "未识别",                  "short": "?",        "family": "unknown"},
}

# Which families a given base family accepts.
#   Filled in from the measurements: SDXL accepts SD-family VAEs and SD1.5
#   (768-dim) textual inversions, but nothing else.
FAMILY_COMPAT = {
    "sd15":  {"sd15", "sd_vae", "ti_sd"},
    "sd21":  {"sd21", "sd_vae"},
    "sdxl":  {"sdxl", "sd_vae", "ti_sd", "ti_sdxl"},
    "sd3":   {"sd3"},
    "flux":  {"flux"},
    "krea2": {"krea2"},
    "anima": {"anima"},
    "minimax": {"minimax"},
}

# ======================================================================
# Model kinds
# ======================================================================

# name -> (comfy folder, role)
#   role: "base"      = the checkpoint / diffusion model everything else hangs off
#         "dependent" = models that must match the base architecture
#         "neutral"   = never architecture bound (upscalers, detectors, ...)
KINDS = {
    "checkpoints":      ("checkpoints", "base"),
    "diffusion_models": ("diffusion_models", "base"),
    "loras":            ("loras", "dependent"),
    "vae":              ("vae", "dependent"),
    "embeddings":       ("embeddings", "dependent"),
    "controlnet":       ("controlnet", "dependent"),
    "text_encoders":    ("text_encoders", "dependent"),
    "clip_vision":      ("clip_vision", "neutral"),
    "upscale_models":   ("upscale_models", "neutral"),
    "sams":             ("sams", "neutral"),
    "ultralytics":      ("ultralytics", "neutral"),
    "style_models":     ("style_models", "neutral"),
    "hypernetworks":    ("hypernetworks", "neutral"),
    "photomaker":       ("photomaker", "neutral"),
}

# aliases used by the frontend / other packs
KIND_ALIASES = {
    "unet": "diffusion_models",
    "clip": "text_encoders",
    "embedding": "embeddings",
    "lora": "loras",
    "checkpoint": "checkpoints",
    "upscale": "upscale_models",
    "ultralytics_bbox": "ultralytics",
    "ultralytics_segm": "ultralytics",
}


def norm_kind(kind):
    k = str(kind or "").strip().lower()
    return KIND_ALIASES.get(k, k)


def kind_role(kind):
    entry = KINDS.get(norm_kind(kind))
    return entry[1] if entry else "neutral"


# ======================================================================
# Path resolution / header reading (cached)
# ======================================================================

_CACHE = {}          # path -> {"key": (path, mtime, size), ...}
_LOCK = threading.Lock()
MAX_KEYS = 20000


def _fallback_root():
    """<ComfyUI>/models, derived from this file's location, for standalone use."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", "models"))


def resolve_path(kind, name, allow_basename=True):
    """
    Absolute path of a model, or None.  Accepts absolute paths too.

    ComfyUI lists nested models as "sub\\file.safetensors" on Windows, but
    hand-written workflows often reference just "file.safetensors".  When the
    exact relative name does not exist, the file is looked up by basename
    anywhere inside that model folder, which is the same forgiveness a human
    would apply.

    Names that went through a "smart" text transformation also resolve: the
    workflow files on this machine contain U+2011 non-breaking hyphens
    ("vae<U+2011>ft<U+2011>mse-...safetensors") where the real file has ASCII
    hyphens, and nothing else in ComfyUI would accept those names.
    """
    if not name:
        return None
    name = str(name)
    if os.path.isabs(name):
        return name if os.path.isfile(name) else None

    k = norm_kind(kind)
    folder = KINDS.get(k, (k, "neutral"))[0]

    candidates = [name]
    fixed = fix_unicode_punct(name)
    if fixed != name:
        candidates.append(fixed)

    for cand in candidates:
        direct = _direct_path(folder, cand)
        if direct:
            return direct

    if allow_basename:
        for cand in candidates:
            base = os.path.basename(cand.replace("\\", "/")).lower()
            rel = _basename_index(folder).get(base)
            if rel and str(rel) != cand:
                return _direct_path(folder, rel)

    # Names quoted without an extension: prompts reference textual inversions as
    # "embedding:EasyNegative", while the file on disk is EasyNegative.safetensors.
    if not os.path.splitext(name)[1]:
        for ext in (".safetensors", ".pt", ".pth", ".ckpt"):
            base = os.path.basename(name + ext).lower()
            rel = _basename_index(folder).get(base)
            if rel:
                found = _direct_path(folder, rel)
                if found:
                    return found
    return None


# Characters a "smart punctuation" pass (Word, some editors, WeChat, OCR) swaps
# in place of an ASCII hyphen.  They are invisible in the UI but fatal to every
# lookup ComfyUI performs.
_PUNCT_MAP = {
    0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2014: "-",
    0x2015: "-", 0x2212: "-", 0xFE63: "-", 0xFF0D: "-",
    0x00A0: " ", 0x3000: " ", 0x200B: "", 0x200C: "", 0x200D: "", 0xFEFF: "",
}


def fix_unicode_punct(name):
    """Replace smart punctuation with the ASCII characters the filesystem uses."""
    return str(name).translate(_PUNCT_MAP)


def _direct_path(folder, name):
    if folder_paths is not None:
        try:
            path = folder_paths.get_full_path(folder, name)
            if path:
                return path
        except Exception:
            pass
        try:
            for root in folder_paths.get_folder_paths(folder):
                cand = os.path.join(root, name)
                if os.path.isfile(cand):
                    return cand
        except Exception:
            pass

    cand = os.path.join(_fallback_root(), folder, name)
    return cand if os.path.isfile(cand) else None


_NAME_INDEX = {}


def _basename_index(folder):
    """basename(lower) -> relative name, built once per folder."""
    hit = _NAME_INDEX.get(folder)
    if hit is not None:
        return hit

    names = []
    if folder_paths is not None:
        try:
            names = list(folder_paths.get_filename_list(folder))
        except Exception:
            names = []
    if not names:
        root = os.path.join(_fallback_root(), folder)
        if os.path.isdir(root):
            for dirpath, _dirs, files in os.walk(root):
                for fn in files:
                    # keep the platform separator, exactly like folder_paths
                    names.append(os.path.relpath(os.path.join(dirpath, fn), root))

    idx = {}
    for n in names:
        base = os.path.basename(str(n).replace("\\", "/")).lower()
        idx.setdefault(base, n)
    _NAME_INDEX[folder] = idx
    return idx


def _stat_key(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (path, int(st.st_mtime), int(st.st_size))


_SHAPE_PROBES = (
    "emb_params", "clip_g", "clip_l", "quant_conv.weight",
    "cond_stage_model.transformer.text_model.embeddings.token_embedding.weight",
    "conditioner.embedders.0.transformer.text_model.embeddings.token_embedding.weight",
)
_SHAPE_RE = re.compile(r"(token_embedding\.weight|attn2\.to_[kv]\.weight)$")


def _new_info(key):
    return {"key": key, "meta": {}, "keys": (), "blob": "", "shapes": {},
            "markers": set(), "bytes": set(), "read": False}


def read_header(path):
    """Header-only read of a safetensors file: metadata, key names, few shapes."""
    key = _stat_key(path)
    if key is None:
        return _new_info(None)

    with _LOCK:
        hit = _CACHE.get(path)
        if hit is not None and hit["key"] == key:
            return hit
        info = _new_info(key)
        _CACHE[path] = info

    if safe_open is None or not path.endswith(".safetensors"):
        return info

    try:
        with safe_open(path, framework="pt") as f:
            info["meta"] = dict(f.metadata() or {})
            keys = list(f.keys())[:MAX_KEYS]
            info["keys"] = tuple(keys)
            info["blob"] = "\n".join(keys)
            wanted = [k for k in keys if k in _SHAPE_PROBES]
            if len(wanted) < 2:
                wanted += [k for k in keys if _SHAPE_RE.search(k)][:2]
            for k in wanted[:6]:
                try:
                    info["shapes"][k] = tuple(f.get_slice(k).get_shape())
                except Exception:
                    continue
            info["read"] = True
    except Exception as exc:  # unreadable / not really safetensors
        info["error"] = str(exc)[:200]
    return info


# Byte markers used for .pt / .ckpt (and anything safetensors could not open).
# torch.save writes the pickle (key names + training metadata) before the raw
# tensor data, so scanning the head of the file is enough.
_BYTE_MARKERS = (
    b"double_blocks", b"single_blocks", b"joint_blocks", b"txtfusion",
    b"attn.gate", b"quant_conv.weight", b"encoder.down_blocks",
    b"lora_te2", b"lora_te1", b"lora_te_text_model",
    b"clip_g", b"clip_l", b"label_emb", b"conditioner.embedders.1",
    b"cond_stage_model", b"krea2", b"stable-diffusion-xl", b"sdxl",
    b"adaln_modulation", b"lora_unet_blocks_", b"minimax", b"circlestone",
    b"stable-diffusion-v1", b"sd_v1", b"stable-diffusion-v2", b"sd_v2",
    b"sd_checkpoint_name",
)
_SCAN_LIMIT = 8 * 1024 * 1024


def _wrap_torch_info(path, key):
    """Byte-level marker scan -> a psuedo 'info' dict for the key-based rules."""
    with _LOCK:
        hit = _CACHE.get(path)
        if hit is not None and hit["key"] == key and hit["read"]:
            return hit
    found = set()
    meta_text = ""
    try:
        with open(path, "rb") as fh:
            data = fh.read(_SCAN_LIMIT)
        for m in _BYTE_MARKERS:
            if m in data:
                found.add(m.decode("ascii"))
        # Pull a readable slice around sd_checkpoint_name so name hints survive.
        at = data.find(b"sd_checkpoint_name")
        if at >= 0:
            meta_text = data[max(0, at - 64): at + 320].decode("latin-1", "ignore")
    except Exception:
        pass

    info = _new_info(key)
    info["bytes"] = found
    info["read"] = True
    info["torch_text"] = meta_text
    with _LOCK:
        _CACHE[path] = info
    return info


def _get_info(path):
    """Header read plus the byte scan fallback (only when the header is useless)."""
    info = read_header(path)
    if info.get("read"):
        return info
    if path.lower().endswith(".safetensors"):
        return info          # a .safetensors we could not parse: stay UNKNOWN
    return _wrap_torch_info(path, info["key"])


# ======================================================================
# Architecture detection
# ======================================================================

_TB_RE = re.compile(r"transformer_blocks_(\d+)")
_BLOCK_RE = re.compile(r"(?:input|output)_blocks_(1[01])_")
_PONY_RE = re.compile(r"pony|pdxl")
_ILL_RE = re.compile(r"illustrious|noob|ilff|nijijourney|hassaku")


def _hints(name, info):
    meta = info.get("meta") or {}
    parts = [
        os.path.basename(str(name or "")),
        meta.get("ss_sd_model_name", ""),
        meta.get("modelspec.title", ""),
        meta.get("modelspec.architecture", ""),
        meta.get("ss_base_model_version", ""),
    ]
    parts.append(info.get("torch_text", ""))
    return " ".join(str(p).lower() for p in parts if p)


def _flavor(text, default):
    if _PONY_RE.search(text or ""):
        return ARCH_PONY
    if _ILL_RE.search(text or ""):
        return ARCH_ILLUSTRIOUS
    return default


def _arch_from_meta(info):
    meta = info.get("meta") or {}
    raw = {
        k: str(meta.get(k, "")).strip().lower()
        for k in ("modelspec.architecture", "ss_base_model_version",
                  "ss_sd_model_name", "ss_network_module")
    }
    text = " ".join(v for v in raw.values() if v)
    if "krea2" in text or "krea-2" in text:
        return ARCH_KREA2
    # NB: "anime" contains "anima", so Anima is only matched on whole tokens
    # and known package names - never as a bare substring.
    if (raw["ss_base_model_version"] == "anima"
            or raw["modelspec.architecture"].startswith("anima")
            or raw["ss_network_module"] == "networks.lora_anima"
            or "air:anima" in text or "circlestone" in text):
        return ARCH_ANIMA
    if (raw["ss_base_model_version"].startswith("minimax")
            or raw["ss_network_module"] == "networks.lora_minimax_h3"
            or "minimax" in text):
        return ARCH_MINIMAX
    if "flux" in text:
        return ARCH_FLUX
    if "stable-diffusion-3" in text or "sd3" in text:
        return ARCH_SD3
    if "stable-diffusion-xl" in text or "sdxl" in text or "sd_xl" in text:
        return ARCH_SDXL
    if "stable-diffusion-v2" in text or "sd_v2" in text or "sd2" in text:
        return ARCH_SD21
    if "stable-diffusion-v1" in text or "sd_v1" in text or "sd1" in text:
        return ARCH_SD15
    return None


def _markers(info):
    """Unified view over safetensors keys and .pt byte markers."""
    blob = info.get("blob", "")
    found = info.get("bytes") or set()
    if blob:
        return blob, set()
    return "", found


def _arch_from_keys(info):
    """Key-structure rules, ordered most specific first."""
    blob, found = _markers(info)

    def has(token):
        return (token in blob) if blob else (token in found)

    if has("txtfusion") or (has("attn.gate") and "diffusion_model.blocks." in blob):
        return ARCH_KREA2
    blocks_dit = bool(re.search(r"lora_unet_blocks_\d", blob)) or has("lora_unet_blocks_")
    if has("adaln_modulation") or (blocks_dit and has("cross_attn")):
        return ARCH_ANIMA                     # Anima DiT (diffusers / kohya layouts)
    if blocks_dit and (has("qkv_proj") or has("mlp_fc1")):
        return ARCH_MINIMAX                   # MiniMax H3 video DiT
    if has("double_blocks") or has("single_blocks"):
        return ARCH_FLUX
    if has("joint_blocks"):
        return ARCH_SD3
    if has("lora_te2") or has("text_encoder_2") or has("label_emb") or has("add_embedding"):
        return ARCH_SDXL
    if blob:
        idx = [int(m) for m in _TB_RE.findall(blob)]
        if idx and max(idx) >= 2:
            return ARCH_SDXL
        if "lora_te_text_model" in blob:          # SD1.5 kohya: single TE, no digit
            return ARCH_SD15
        if _BLOCK_RE.search(blob):                # input/output_blocks_10|11
            return ARCH_SD15
        if "down_blocks_3_" in blob or "up_blocks_3_" in blob:
            return ARCH_SD15
    if has("conditioner.embedders.1"):
        return ARCH_SDXL
    if has("cond_stage_model"):
        return ARCH_SD15
    return None


def _te_width(info):
    """Token-embedding width: 768=SD1.5, 1024=SD2.x, 1280/2048=SDXL."""
    for key, shape in (info.get("shapes") or {}).items():
        if "token_embedding.weight" in key and len(shape) == 2:
            return int(shape[1])
    return None


def _detect_checkpoint(name, info):
    arch = _arch_from_meta(info)
    if arch:
        if arch == ARCH_SDXL:
            return _flavor(_hints(name, info), ARCH_SDXL), "元数据"
        return arch, "元数据"
    arch = _arch_from_keys(info)
    if arch == ARCH_SDXL:
        return _flavor(_hints(name, info), ARCH_SDXL), "键结构"
    if arch:
        return arch, "键结构"
    width = _te_width(info)
    if width == 1024:
        return ARCH_SD21, "TE 维度"
    if width == 768:
        return ARCH_SD15, "TE 维度"
    if info.get("keys"):
        return ARCH_SD15, "无 SDXL 标记（按 SD1.5 处理）"
    return ARCH_UNKNOWN, ""


def _detect_lora(name, info):
    meta_arch = _arch_from_meta(info)
    if meta_arch:
        if meta_arch == ARCH_SDXL:
            return _flavor(_hints(name, info), ARCH_SDXL), "元数据"
        return meta_arch, "元数据"
    arch = _arch_from_keys(info)
    if arch:
        if arch == ARCH_SDXL:
            return _flavor(_hints(name, info), ARCH_SDXL), "键结构"
        return arch, "键结构"
    return ARCH_UNKNOWN, ""


def _detect_vae(name, info):
    meta_arch = _arch_from_meta(info)
    if meta_arch == ARCH_FLUX or meta_arch == ARCH_SD3:
        return ARCH_FLUXVAE, "元数据"
    if meta_arch in (ARCH_SD15, ARCH_SD21, ARCH_SDXL, ARCH_PONY, ARCH_ILLUSTRIOUS):
        return ARCH_SDVAE, "元数据"

    blob, found = _markers(info)
    has_quant = ("quant_conv" in blob) if blob else ("quant_conv.weight" in found)
    has_diffusers = ("encoder.down_blocks" in blob) if blob else ("encoder.down_blocks" in found)
    if has_diffusers and not has_quant:
        return ARCH_FLUXVAE, "16 通道潜空间（diffusers 命名）"
    if has_quant:
        return ARCH_SDVAE, "4 通道潜空间（quant_conv）"
    return ARCH_UNKNOWN, ""


def _detect_embedding(name, info):
    meta_arch = _arch_from_meta(info)
    if meta_arch == ARCH_SDXL:
        return ARCH_TI_SDXL, "元数据"
    shapes = info.get("shapes") or {}
    if "clip_g" in shapes or "clip_g" in (info.get("blob") or ""):
        return ARCH_TI_SDXL, "clip_g + clip_l（SDXL 双编码器）"
    if "clip_l" in shapes or "clip_l" in (info.get("blob") or ""):
        return ARCH_TI_SD15, "仅 clip_l"
    width = None
    if "emb_params" in shapes and len(shapes["emb_params"]) == 2:
        width = int(shapes["emb_params"][1])
    if width == 1024:
        return ARCH_TI_SD21, "768/1024 维度"
    if width == 768:
        return ARCH_TI_SD15, "768 维度"
    if width == 1280:
        return ARCH_TI_SDXL, "1280 维度"
    found = info.get("bytes") or set()
    if "clip_g" in found:
        return ARCH_TI_SDXL, "clip_g"
    if "clip_l" in found:
        return ARCH_TI_SD15, "clip_l"
    if "sd_checkpoint_name" in found:      # .pt textual inversion, name hint only
        hints = _hints(name, info)
        if _PONY_RE.search(hints) or "xl" in hints:
            return ARCH_TI_SDXL, "文件名/内嵌名推测"
        return ARCH_TI_SD15, "文件名/内嵌名推测"
    return ARCH_UNKNOWN, ""


def _detect_generic(name, info):
    arch = _arch_from_meta(info)
    if arch and arch != ARCH_SDXL:
        return arch, "元数据"
    arch = _arch_from_keys(info)
    if arch:
        if arch == ARCH_SDXL:
            return _flavor(_hints(name, info), ARCH_SDXL), "键结构"
        return arch, "键结构"
    return ARCH_UNKNOWN, ""


_DETECTORS = {
    "checkpoints": _detect_checkpoint,
    "diffusion_models": _detect_generic,
    "loras": _detect_lora,
    "vae": _detect_vae,
    "embeddings": _detect_embedding,
    "controlnet": _detect_generic,
    "text_encoders": _detect_generic,
}


_ARCH_CACHE = {}


def detect_arch(kind, name):
    """-> (arch, reason).  Never raises."""
    k = norm_kind(kind)
    role = kind_role(k)
    if role == "neutral":
        return ARCH_UNIVERSAL, "不受架构限制"

    cache_key = (k, str(name))
    hit = _ARCH_CACHE.get(cache_key)
    if hit is not None:
        return hit

    result = (ARCH_UNKNOWN, "文件未找到")
    try:
        path = resolve_path(k, name)
        if path:
            info = _get_info(path)
            detector = _DETECTORS.get(k, _detect_generic)
            arch, reason = detector(name, info)
            result = (arch or ARCH_UNKNOWN, reason or "")
    except Exception as exc:
        result = (ARCH_UNKNOWN, "读取失败: %s" % str(exc)[:80])

    _ARCH_CACHE[cache_key] = result
    return result


def arch_short(arch):
    return ARCH_INFO.get(arch, ARCH_INFO[ARCH_UNKNOWN])["short"]


def arch_label(arch):
    return ARCH_INFO.get(arch, ARCH_INFO[ARCH_UNKNOWN])["label"]


def arch_family(arch):
    return ARCH_INFO.get(arch, ARCH_INFO[ARCH_UNKNOWN])["family"]


# ======================================================================
# Conflict rules
# ======================================================================

def compatible(base_family, item_family):
    if base_family in ("unknown", "universal") or item_family in ("unknown", "universal"):
        return None                      # cannot judge / not architecture bound
    if item_family in FAMILY_COMPAT.get(base_family, set()):
        return True
    return False


def _why(arch, ref, state):
    if state == "ok":
        return "与工作流基准同源（%s）" % arch_label(arch)
    if state == "conflict":
        if ref is None:
            return "工作流里没有可参照的底模"
        if ref.get("mode") == "base":
            have = "、".join(
                "%s×%d" % (f, n) for f, n in sorted(ref.get("families", {}).items())
            ) or "无"
            return "工作流里已接入的模型都不是 %s 系（现有 %s）" % (arch_short(arch), have)
        if arch == ARCH_FLUXVAE:
            return "FLUX VAE 是 16 通道潜空间，%s 底模无法解码" % arch_label(ref["arch"])
        if arch == ARCH_SDVAE:
            return "SD 系 VAE 与 %s 不通用" % arch_label(ref["arch"])
        return "与基准 %s 不同源（本项 %s）" % (arch_label(ref["arch"]), arch_label(arch))
    return "无法判断（架构未识别）"


def _allowed_families(ref):
    """Families this picker should paint blue."""
    if ref is None:
        return None
    if ref.get("mode") == "base":
        # The candidates are base models themselves, so every dependent family
        # in the graph is translated back into the base families that serve it.
        allowed = set()
        for fam in (ref.get("families") or {}):
            allowed |= _reverse_compat(fam)
        if not allowed and ref.get("family"):
            allowed = _reverse_compat(ref["family"])
        return allowed or None

    base_fam = ref.get("family")
    if not base_fam:
        return None
    return {base_fam} | set(FAMILY_COMPAT.get(base_fam, set()))


# ======================================================================
# Reference resolution over a workflow
# ======================================================================

BASE_KINDS = ("checkpoints", "diffusion_models")
# LoRAs / ControlNets / text encoders really pin the base architecture down.
STRONG_DEPENDENTS = ("loras", "controlnet", "text_encoders")
# VAEs and textual inversions are widely interchangeable, so they only get a
# say when nothing stronger is wired up.
WEAK_DEPENDENTS = ("vae", "embeddings")
DEPENDENT_KINDS = STRONG_DEPENDENTS + WEAK_DEPENDENTS


def _reverse_compat(item_family):
    """Which base families accept this item family."""
    return {base for base, allowed in FAMILY_COMPAT.items() if item_family in allowed}


def _classify_picks(picks):
    """picks: {kind: [name, ...]} -> {kind: [(name, arch, reason), ...]}"""
    out = {}
    for kind, names in (picks or {}).items():
        k = norm_kind(kind)
        if k not in KINDS:
            continue
        rows = []
        for name in (names or [])[:400]:
            if not name:
                continue
            arch, reason = detect_arch(k, name)
            rows.append((str(name), arch, reason))
        if rows:
            out[k] = rows
    return out


def _vote(rows):
    """Most common confident family among (name, arch, reason) rows."""
    tally = {}
    order = []
    for name, arch, _reason in rows:
        fam = arch_family(arch)
        if fam in ("unknown", "universal"):
            continue
        if fam not in tally:
            tally[fam] = {"count": 0, "arch": arch, "name": name}
            order.append(fam)
        tally[fam]["count"] += 1
    if not tally:
        return None
    best = max(order, key=lambda f: tally[f]["count"])
    info = tally[best]
    return {"family": best, "arch": info["arch"], "name": info["name"],
            "count": info["count"], "tally": {f: tally[f]["count"] for f in order}}


def compute_reference(kind, picks):
    """
    Working out what "the workflow's architecture" is.

    * opening a *base* picker (checkpoint / diffusion model) compares against the
      dependents that are already wired up, because that is what the new base has
      to serve.  A workflow may legitimately mix families (a Pony LoRA stack plus
      one Krea 2 experiment), so every family that occurs at least once counts as
      "served": a base is only red when *none* of the wired-up models wants it.
    * opening a *dependent* picker compares against the base model in the graph,
      strictly: the LoRA/VAE/embedding must belong to the base's family.
    """
    k = norm_kind(kind)
    role = kind_role(k)
    classified = _classify_picks(picks)

    if role == "base":
        pool, source_kind = [], ""
        for group in (STRONG_DEPENDENTS, WEAK_DEPENDENTS):
            rows = [row for dk in group for row in classified.get(dk, [])]
            if rows:
                pool = rows
                source_kind = next(dk for dk in group if dk in classified)
                break
        if not pool:
            return None
    else:
        pool, source_kind = [], ""
        for bk in BASE_KINDS:
            if bk in classified:
                pool = classified[bk]
                source_kind = bk
                break
        if not pool:
            # No base in the graph: fall back to the *other* dependents.
            for dk in DEPENDENT_KINDS:
                if dk != k and dk in classified:
                    pool = classified[dk]
                    source_kind = dk
                    break
        if not pool:
            return None

    vote = _vote(pool)
    if not vote:
        return None
    return {
        "arch": vote["arch"],
        "family": vote["family"],
        "families": vote["tally"],          # every family present, with counts
        "label": arch_label(vote["arch"]),
        "short": arch_short(vote["arch"]),
        "source_kind": source_kind,
        "source_name": vote["name"],
        "agreement": vote["count"],
        "pool_size": len(pool),
        "mode": role,
    }


def graph_families(picks):
    """Family histogram of everything wired into the workflow (for the legend)."""
    classified = _classify_picks(picks)
    hist = {}
    for kind, rows in classified.items():
        for _name, arch, _reason in rows:
            fam = arch_family(arch)
            if fam in ("unknown", "universal"):
                continue
            slot = hist.setdefault(fam, {"count": 0, "short": arch_short(arch)})
            slot["count"] += 1
    return hist


def check(kind, names, picks=None):
    """Annotate every candidate `name` for `kind` against the workflow's base."""
    k = norm_kind(kind)
    ref = compute_reference(k, picks or {})
    allowed = _allowed_families(ref)

    items = {}
    counts = {"conflict": 0, "ok": 0, "unknown": 0}
    for name in (names or [])[:2000]:
        arch, reason = detect_arch(k, name)
        fam = arch_family(arch)
        if fam == "universal":
            state = "ok"
        elif allowed is None or fam == "unknown":
            state = "unknown"
        elif fam in allowed:
            state = "ok"
        else:
            state = "conflict"
        counts[state] += 1
        items[str(name)] = {
            "arch": arch,
            "short": arch_short(arch),
            "label": arch_label(arch),
            "family": fam,
            "state": state,
            "reason": reason,
            "why": _why(arch, ref, state),
        }

    return {
        "kind": k,
        "role": kind_role(k),
        "reference": ref,
        "counts": counts,
        "graph": graph_families(picks or {}),
        "items": items,
    }


def list_models(kind=None):
    """Model names per kind, from folder_paths (or the fallback tree)."""
    kinds = [norm_kind(kind)] if kind else list(KINDS.keys())
    out = {}
    for k in kinds:
        folder = KINDS.get(k, (k, "neutral"))[0]
        names = []
        if folder_paths is not None:
            try:
                names = list(folder_paths.get_filename_list(folder))
            except Exception:
                names = []
        if not names:
            root = os.path.join(_fallback_root(), folder)
            if os.path.isdir(root):
                for dirpath, _dirs, files in os.walk(root):
                    for fn in files:
                        if fn.lower().endswith((".safetensors", ".pt", ".pth", ".ckpt", ".bin")):
                            rel = os.path.relpath(os.path.join(dirpath, fn), root)
                            names.append(rel)
        if names:
            out[k] = sorted(names)
    return out


def clear_cache():
    with _LOCK:
        _CACHE.clear()
    _ARCH_CACHE.clear()
    _NAME_INDEX.clear()
