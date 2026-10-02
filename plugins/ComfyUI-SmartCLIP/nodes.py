# -*- coding: utf-8 -*-
"""
SmartCLIPTextEncode
===================
A drop-in replacement for ComfyUI's CLIPTextEncode that also tells the frontend
which architecture the incoming CLIP belongs to, so a prompt dialog can offer
the right word lists (Pony score tags, SD1.5 quality words, FLUX natural
language, ...).

Two ComfyUI mechanisms matter here, and both were verified against this
checkout rather than assumed:

1. Encoding.  This ComfyUI's own CLIPTextEncode.encode now does

       return (clip.encode_from_tokens_scheduled(tokens), )

   ``encode_from_tokens_scheduled`` is what applies hooks, LoRA conditioning
   patches and the per-model token handling.  Calling
   ``encode_from_tokens(..., return_pooled=True)`` and hand-building
   ``{"pooled_output": pooled}`` - as the draft this replaces did - bypasses all
   of that and injects a pooled vector even for models that have none (FLUX),
   so it is *not* interface compatible no matter how similar the return type
   looks.  We use the native call.

2. UI payload.  ``execution.py`` collects a dict return as

       {"ui": {...}, "result": (...)}

   and then flattens it with
       ui = {k: [y for x in uis for y in x[k]] for k in uis[0].keys()}
   so every ui value MUST be a list - a bare string is silently split into
   characters.  The frontend receives it as ``node.onExecuted(output)``
   (dispatched from the ``executed`` websocket event).  Cached executions replay
   the cached ui, so no IS_CHANGED trickery is needed to keep the frontend
   informed.
"""

try:                       # normal case: loaded as a package by ComfyUI
    from .model_detector import detect_clip_arch
except ImportError:        # standalone import (tests / tooling)
    from model_detector import detect_clip_arch

MAX_UI_TEXT = 4000


def _safe_log(message):
    """Console output that cannot explode on a GBK Windows console."""
    try:
        print(message, flush=True)
    except Exception:
        try:
            print(str(message).encode("ascii", "replace").decode("ascii"), flush=True)
        except Exception:
            pass


class SmartCLIPTextEncode:
    """CLIP Text Encode (Smart)

    Identical behaviour to the core node plus an architecture report for the UI.
    """

    CATEGORY = "conditioning/smart"
    FUNCTION = "encode"

    # OUTPUT_NODE is what makes the ui payload survive a cache hit.
    #
    # Measured on this build (tests/live_ws_check.py): without it, a fully cached
    # re-run delivers nothing to the frontend, so a dialog opened afterwards
    # would still show the previous run's architecture.  With it, ComfyUI keeps
    # the node in the execution list and replays the cached ui - and the Sampler
    # downstream is still served from cache (nothing re-renders), because the
    # node's CONDITIONING output is unchanged.
    #
    # Side effect, by design: an unconnected SmartCLIP node still runs, so the
    # button label is filled in even before the output is wired anywhere.  That
    # costs one text encode (~ms), not a sampling pass.
    OUTPUT_NODE = True

    RETURN_TYPES = ("CONDITIONING", "STRING")
    RETURN_NAMES = ("CONDITIONING", "model_type")

    DESCRIPTION = (
        "CLIP 文本编码（智能）：接口与原生 CLIPTextEncode 完全一致，"
        "另外把输入 CLIP 的架构（SD1.5 / SDXL / Pony / Illustrious / SD3 / FLUX）"
        "上报给前端，用于弹出对应的提示词词库。"
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip": ("CLIP",),
                "text": ("STRING", {
                    "multiline": True,
                    "dynamicPrompts": True,
                    "default": "",
                    "tooltip": "提示词正文，可直接手写，也可以用「选择提示词」按钮从词库追加",
                }),
                "prompt_role": (["auto", "positive", "negative"], {
                    "default": "auto",
                    "tooltip": "auto = 根据下游连线（KSampler 的正面/负面）自动判断",
                }),
            },
            "optional": {
                "prompt_category": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "标注用：记录上次从哪个分类取的词，不参与编码",
                }),
            },
        }

    # ------------------------------------------------------------------
    # Encoding
    # ------------------------------------------------------------------

    def encode(self, clip, text, prompt_role="auto", prompt_category=""):
        arch = detect_clip_arch(clip)

        tokens = clip.tokenize(text)
        conditioning = clip.encode_from_tokens_scheduled(tokens)

        role = prompt_role if prompt_role in ("positive", "negative") else "auto"

        payload = {
            "family": arch["family"],
            "label": arch["label"],
            "preset": arch["preset"],
            "score_tags": arch["score_tags"],
            "note": arch.get("note", ""),
            "evidence": arch["evidence"],
            "source": arch["source"],
            "role": role,
            "category": prompt_category or "",
            "chars": len(text or ""),
            "text_preview": (text or "")[:200],
            "raw_text": (text or "")[:MAX_UI_TEXT],
        }

        _safe_log("[SmartCLIP] %s | role=%s | %s | %s"
                  % (arch["label"], role, arch["evidence"], arch["source"]))

        # ui values must be lists (execution.py flattens them), result carries
        # the real node outputs.
        return {
            "ui": {"smart_clip": [payload]},
            "result": (conditioning, arch["label"]),
        }

    # NOTE: IS_CHANGED is deliberately NOT defined.
    #
    # Returning NaN (a common trick) forces a re-encode on every queue, and the
    # real cost is worse than the encode itself: a fresh CONDITIONING object each
    # run invalidates the Sampler's cache key, so re-queueing an unchanged
    # workflow would re-render the whole image.  Combined with OUTPUT_NODE above,
    # the frontend still gets the model type on every queue - from the cache.


NODE_CLASS_MAPPINGS = {
    "SmartCLIPTextEncode": SmartCLIPTextEncode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SmartCLIPTextEncode": "CLIP Text Encode (Smart) / \u667a\u80fd\u63d0\u793a\u8bcd",
}
