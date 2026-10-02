"""
ComfyUI Model Image Picker
==========================
Frontend-only custom node. It adds no graph nodes; it only injects a small
panel into the workflow UI that lists Checkpoints / LoRAs as clickable
thumbnails, so you can recognise a model by its picture instead of its filename.

Contents:
  web/js/model_image_picker.js  - the UI extension (button + collapsible panel)
  web/js/model_conflict.js      - architecture/conflict colouring for the modal
  model_preview_api.py          - backend routes that list models and serve the
                                  sidecar preview images
  model_conflict.py             - architecture detection + conflict rules,
                                  covering checkpoints, LoRAs, VAEs, textual
                                  inversions, ControlNets and text encoders
  model_conflict_api.py         - routes for the conflict engine

Preview images are the ones your SD WebUI already uses: a .png next to the
model file with the same basename.

Keep this file ASCII-only.
"""

import os

NODE_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))

# ComfyUI serves this directory at /extensions/ComfyUI_ModelImagePicker/
WEB_DIRECTORY = "./web/js"

# No graph nodes are provided by this pack.
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

# Register the HTTP routes used by the frontend panel.
try:
    from . import model_preview_api

    model_preview_api.register_routes()
except Exception as exc:  # pragma: no cover
    print(f"[ModelImagePicker] route registration failed: {exc}")

# Register the architecture / conflict routes.
try:
    from . import model_conflict_api

    model_conflict_api.register_routes()
except Exception as exc:  # pragma: no cover
    print(f"[ModelImagePicker] conflict route registration failed: {exc}")

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
