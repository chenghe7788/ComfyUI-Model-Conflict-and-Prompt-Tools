# -*- coding: utf-8 -*-
"""
Model Conflict API
==================
HTTP surface for model_conflict.py, consumed by web/js/model_conflict.js.

  GET  /modelconflict/index
       -> {"kinds": {"loras": [...], "checkpoints": [...], ...},
           "labels": {"loras": "LoRA", ...},
           "roles":  {"loras": "dependent", ...},
           "catalogue": {"SDXL": {...}, ...}}

  POST /modelconflict/check
       body {"kind": "loras",
             "names": ["a.safetensors", ...],
             "picks": {"checkpoints": ["base.safetensors"], "loras": [...]}}
       -> {"reference": {...}, "counts": {...}, "graph": {...},
           "items": {"a.safetensors": {"arch","short","state","why",...}}}

  GET  /modelconflict/model?kind=loras&name=a.safetensors
       -> single item record (debugging / future per-node use)

  POST /modelconflict/refresh
       -> drops both caches (header cache and architecture cache)

Model header reading is disk I/O with no async library involved, so every
handler runs the work in the default executor instead of blocking the event
loop that is also serving workflow execution requests.

Log lines here stay ASCII: ComfyUI's Windows console is GBK and a Chinese
print() would raise UnicodeEncodeError in the middle of a request.
"""

import asyncio
import logging

try:                      # normal case: loaded as a package by ComfyUI
    from . import model_conflict as mc
except ImportError:       # standalone / non-package import
    import model_conflict as mc

try:
    from aiohttp import web
except Exception:  # pragma: no cover
    web = None

log = logging.getLogger(__name__)

# Human readable names for the model folder kinds the frontend may ask about.
KIND_LABELS = {
    "checkpoints": "大模型",
    "diffusion_models": "UNET / 扩散模型",
    "loras": "LoRA",
    "vae": "VAE",
    "embeddings": "词嵌入",
    "controlnet": "ControlNet",
    "text_encoders": "文本编码器",
    "clip_vision": "CLIP Vision",
    "upscale_models": "放大模型",
    "sams": "SAM 分割",
    "ultralytics": "检测模型",
    "style_models": "风格模型",
    "hypernetworks": "超网络",
    "photomaker": "PhotoMaker",
}


async def _in_thread(fn, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn, *args)


def _clean_names(value, limit=2000):
    if not isinstance(value, (list, tuple)):
        return []
    out = []
    for item in value[:limit]:
        if isinstance(item, str) and item:
            out.append(item)
    return out


def _clean_picks(value):
    if not isinstance(value, dict):
        return {}
    out = {}
    for kind, names in value.items():
        if isinstance(kind, str):
            cleaned = _clean_names(names, 400)
            if cleaned:
                out[kind] = cleaned
    return out


def _index_payload():
    kinds = mc.list_models()
    return {
        "kinds": kinds,
        "labels": {k: KIND_LABELS.get(k, k) for k in kinds},
        "roles": {k: mc.kind_role(k) for k in kinds},
        "catalogue": mc.ARCH_INFO,
        "conflict_on": True,
    }


def register_routes():
    """Attach the routes to the running PromptServer. Safe to call once."""
    if web is None:
        log.warning("[ModelConflict] aiohttp unavailable, routes not registered")
        return False
    try:
        from server import PromptServer
    except Exception as exc:
        log.warning("[ModelConflict] cannot reach PromptServer: %s", exc)
        return False

    routes = getattr(PromptServer.instance, "routes", None)
    if routes is None:
        log.warning("[ModelConflict] PromptServer.instance.routes unavailable")
        return False

    @routes.get("/modelconflict/index")
    async def modelconflict_index(request):
        try:
            payload = await _in_thread(_index_payload)
        except Exception as exc:
            log.warning("[ModelConflict] index failed: %s", exc)
            return web.json_response({"error": str(exc)[:300]}, status=500)
        return web.json_response(payload)

    @routes.post("/modelconflict/check")
    async def modelconflict_check(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "bad json"}, status=400)

        kind = str(body.get("kind", ""))
        names = _clean_names(body.get("names"))
        picks = _clean_picks(body.get("picks"))
        if not kind or not names:
            return web.json_response(
                {"error": "kind and names are required", "items": {}}, status=400)

        try:
            result = await _in_thread(mc.check, kind, names, picks)
        except Exception as exc:
            log.warning("[ModelConflict] check failed: %s", exc)
            return web.json_response({"error": str(exc)[:300], "items": {}}, status=500)
        return web.json_response(result)

    @routes.get("/modelconflict/model")
    async def modelconflict_model(request):
        kind = request.rel_url.query.get("kind", "")
        name = request.rel_url.query.get("name", "")
        if not kind or not name:
            return web.json_response({"error": "kind and name are required"}, status=400)

        def _one():
            arch, reason = mc.detect_arch(kind, name)
            return {
                "kind": mc.norm_kind(kind),
                "name": name,
                "arch": arch,
                "short": mc.arch_short(arch),
                "label": mc.arch_label(arch),
                "family": mc.arch_family(arch),
                "reason": reason,
                "path": mc.resolve_path(kind, name),
            }

        return web.json_response(await _in_thread(_one))

    @routes.post("/modelconflict/refresh")
    async def modelconflict_refresh(request):
        await _in_thread(mc.clear_cache)
        log.info("[ModelConflict] caches cleared")
        return web.json_response({"ok": True})

    log.info("[ModelConflict] routes registered: /modelconflict/index, "
             "/modelconflict/check, /modelconflict/model, /modelconflict/refresh")
    return True
