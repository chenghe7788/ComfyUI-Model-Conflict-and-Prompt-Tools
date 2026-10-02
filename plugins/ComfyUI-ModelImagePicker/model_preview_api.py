"""
Model Image Picker - backend API
================================
Serves two endpoints used by the frontend extension (web/js/model_image_picker.js):

  GET /modelpreview/list?kind=checkpoints|loras|vae|embeddings|controlnet|
                            diffusion_models|text_encoders|upscale_models|
                            sams|ultralytics
      -> {"kind": ..., "folder": ..., "total": N, "withPreview": M,
          "items": [{"name": ..., "basename": ..., "hasPreview": bool}, ...]}

  GET /modelpreview/img?kind=...&name=...
      -> the sidecar preview image (same basename as the model, .png/.jpg/...)
         or 404 when the model has no preview image.

Every kind the picker can open must be listed here, not just the three that
have sidecar pictures: a kind this endpoint rejects makes the whole picker show
up empty, which reads as "the dialog is broken" (upscalers / SAM / detectors /
ControlNet / UNET / text encoders have no SD WebUI sidecars, but their cards
still carry the file name and the conflict colouring).

Why this exists
---------------
ComfyUI core has no model-preview mechanism at all (verified: no "preview"
handling in folder_paths.py / server.py for model files). SD WebUI stores
previews as a sidecar image next to the model file with the same basename:

    models/Stable-diffusion/anijed_v10.safetensors
    models/Stable-diffusion/anijed_v10.png          <-- preview

This module resolves that sidecar file safely (the requested name must be an
actual entry of folder_paths.get_filename_list, so path traversal is rejected).

Keep this file ASCII-only (no non-ASCII characters, not even in comments) so
that custom node loading never breaks on an encoding edge case.
"""

import os
import logging

import folder_paths

try:                      # normal case: loaded as a package by ComfyUI
    from . import model_conflict as mc
except ImportError:       # standalone / non-package import
    try:
        import model_conflict as mc
    except ImportError:   # noqa: N816 - the engine is optional for this module
        mc = None

log = logging.getLogger(__name__)

# Extensions we accept for a sidecar preview image, in priority order.
PREVIEW_EXTS = (".png", ".webp", ".jpg", ".jpeg", ".gif", ".jfif")

# Fallback kind -> ComfyUI model folder, used when model_conflict.py is not
# importable.  Keep this in sync with model_conflict.KINDS.
FALLBACK_KIND_TO_FOLDER = {
    "checkpoints": "checkpoints",
    "diffusion_models": "diffusion_models",
    "loras": "loras",
    "vae": "vae",
    "embeddings": "embeddings",
    "controlnet": "controlnet",
    "text_encoders": "text_encoders",
    "clip_vision": "clip_vision",
    "upscale_models": "upscale_models",
    "sams": "sams",
    "ultralytics": "ultralytics",
    "style_models": "style_models",
    "hypernetworks": "hypernetworks",
    "photomaker": "photomaker",
}

# Aliases the frontend or other packs may send instead of the canonical name.
KIND_ALIASES = {
    "unet": "diffusion_models",
    "clip": "text_encoders",
    "embedding": "embeddings",
    "textual_inversion": "embeddings",
    "lora": "loras",
    "checkpoint": "checkpoints",
    "upscale": "upscale_models",
    "upscaler": "upscale_models",
    "ultralytics_bbox": "ultralytics",
    "ultralytics_segm": "ultralytics",
}


def kind_to_folder(kind):
    """
    ComfyUI model folder for a picker kind, or None when the kind is unknown.

    The picker offers ten kinds (checkpoints / LoRAs / VAE / embeddings /
    ControlNet / UNET / text encoders / upscalers / SAM / detectors), and the
    folder table lives in model_conflict.KINDS so both features always agree.
    Only three of them used to be mapped here, which made every other picker -
    the upscale one the user opened - fail with HTTP 400 and show an empty
    dialog (2026-09-15).
    """
    key = str(kind or "").strip().lower()
    key = KIND_ALIASES.get(key, key)
    if mc is not None:
        entry = mc.KINDS.get(key)
        if entry:
            return entry[0]
    return FALLBACK_KIND_TO_FOLDER.get(key)


def kind_catalogue():
    """Every kind this endpoint can list, for diagnostics."""
    names = set(FALLBACK_KIND_TO_FOLDER)
    if mc is not None:
        names.update(mc.KINDS)
    return sorted(names)


def _iter_folder_preview_dirs(model_folder_name):
    """Yield every configured folder for a model kind (ComfyUI dir + shared SD dir)."""
    for folder in folder_paths.get_folder_paths(model_folder_name):
        if folder and os.path.isdir(folder):
            yield folder


def find_preview_path(model_folder_name, name):
    """
    Resolve the sidecar preview image for a model.

    `name` is a ComfyUI model name (relative path inside the model folder, e.g.
    "anijed_v10.safetensors" or "sd15/sub/model.safetensors").

    Returns an absolute path or None. The result is guaranteed to stay inside one
    of the configured model folders.
    """
    stem, _ext = os.path.splitext(name)
    for folder in _iter_folder_preview_dirs(model_folder_name):
        folder_abs = os.path.abspath(folder)
        for ext in PREVIEW_EXTS:
            candidate = os.path.abspath(os.path.join(folder_abs, stem + ext))
            # Containment check: reject anything that escaped the model folder.
            if not candidate.startswith(folder_abs + os.sep):
                continue
            if os.path.isfile(candidate):
                return candidate
    return None


def _mime_for(path):
    ext = os.path.splitext(path)[1].lower()
    return {
        ".png": "image/png",
        ".webp": "image/webp",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".jfif": "image/jpeg",
        ".gif": "image/gif",
    }.get(ext, "application/octet-stream")


def register_routes():
    """Attach the two routes to the running PromptServer. Safe to call once."""
    try:
        from server import PromptServer
        from aiohttp import web
    except Exception as exc:  # pragma: no cover - only when running inside ComfyUI
        log.warning("[ModelImagePicker] cannot register routes: %s", exc)
        return False

    routes = getattr(PromptServer.instance, "routes", None)
    if routes is None:
        log.warning("[ModelImagePicker] PromptServer.instance.routes unavailable")
        return False

    @routes.get("/modelpreview/list")
    async def modelpreview_list(request):
        kind = request.rel_url.query.get("kind", "checkpoints")
        folder = kind_to_folder(kind)
        if folder is None:
            return web.json_response(
                {"error": "unknown kind", "kind": kind, "known": kind_catalogue()},
                status=400,
            )

        try:
            names = folder_paths.get_filename_list(folder)
        except Exception as exc:      # folder not registered by any node pack
            log.info("[ModelImagePicker] folder %s unavailable: %s", folder, exc)
            names = []

        items = []
        found = 0
        for name in names:
            has = find_preview_path(folder, name) is not None
            if has:
                found += 1
            items.append({
                "name": name,
                "basename": os.path.basename(name),
                "hasPreview": has,
            })

        return web.json_response({
            "kind": kind,
            "folder": folder,
            "total": len(items),
            "withPreview": found,
            "items": items,
        })

    @routes.get("/modelpreview/img")
    async def modelpreview_img(request):
        kind = request.rel_url.query.get("kind", "checkpoints")
        name = request.rel_url.query.get("name", "")
        folder = kind_to_folder(kind)
        if folder is None or not name:
            return web.Response(status=400)

        # Security: only allow names that ComfyUI itself lists for this folder.
        try:
            allowed = set(folder_paths.get_filename_list(folder))
        except Exception:
            allowed = set()
        if name not in allowed:
            return web.Response(status=404)

        path = find_preview_path(folder, name)
        if path is None:
            return web.Response(status=404)

        return web.FileResponse(path, headers={
            "Content-Type": _mime_for(path),
            "Cache-Control": "public, max-age=86400",
        })

    @routes.post("/modelpreview/debug")
    async def modelpreview_debug(request):
        """
        Diagnostic sink for the frontend interception layer.

        Because the browser cannot tell us what happened, the extension posts
        short event strings here and they land in ComfyUI's log. This is what
        makes it possible to diagnose "the picker did not open" without a
        devtools session.
        """
        try:
            data = await request.json()
        except Exception:
            data = {"stage": "unparseable"}
        stage = str(data.get("stage", "?"))[:80]
        detail = str(data.get("detail", ""))[:400]
        log.info("[ModelImagePicker] %s | %s", stage, detail)
        return web.json_response({"ok": True})

    log.info("[ModelImagePicker] routes registered: "
             "/modelpreview/list, /modelpreview/img, /modelpreview/debug")
    return True
