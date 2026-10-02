# -*- coding: utf-8 -*-
"""
Self-test for the model-preview / picker kind coverage fix (2026-09-15).

Run with the embedded python, which is the only interpreter that can import
ComfyUI's folder_paths:

  C:\\ComfyUI_windows_portable\\python_embeded\\python.exe \
      C:\\ComfyUI-ModelConflict\\tests\\_test_preview_api.py

What it checks (no ComfyUI process needed, no network):
  1. every kind the frontend picker can open resolves to a model folder;
  2. /modelpreview/list answers 200 for all of them - upscale_models used to
     come back 400, which is why the upscale dialog was empty;
  3. the counted items equal what the conflict engine lists for that folder;
  4. an unknown kind is still rejected with 400 (no silent empty success);
  5. /modelpreview/img refuses a name that is not in the folder.
"""

import asyncio
import importlib.util
import io
import json
import os
import re
import sys

COMFY_ROOT = r"C:\ComfyUI_windows_portable\ComfyUI"
SRC = r"C:\ComfyUI-ModelConflict\src"
PICKER_JS = os.path.join(SRC, "web", "js", "model_image_picker.js")

sys.path.insert(0, COMFY_ROOT)
sys.path.insert(0, SRC)

fail = 0


def check(label, got, want):
    global fail
    ok = got == want
    if not ok:
        fail += 1
    print("  %-4s %-52s %s" % ("OK" if ok else "FAIL", label,
                               got if ok else "got %r want %r" % (got, want)))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ----------------------------------------------------------------------
# 0. kinds declared by the picker frontend must all be known to the backend
# ----------------------------------------------------------------------
picker_src = io.open(PICKER_JS, encoding="utf-8").read()
block = re.search(r"const LABEL = \{(.*?)\n\};", picker_src, re.S).group(1)
picker_kinds = re.findall(r"^\s*([a-z_]+):", block, re.M)
print("[kind coverage] picker offers:", picker_kinds)

mp = load_module("mpa", os.path.join(SRC, "model_preview_api.py"))
mc = mp.mc
assert mc is not None, "model_conflict must be importable for this test"

for kind in picker_kinds:
    check("picker kind %s -> folder" % kind, mp.kind_to_folder(kind) is not None, True)

check("alias unet -> diffusion_models", mp.kind_to_folder("unet"), "diffusion_models")
check("alias clip -> text_encoders", mp.kind_to_folder("clip"), "text_encoders")
check("unknown kind rejected", mp.kind_to_folder("bogus_kind"), None)

# ----------------------------------------------------------------------
# 1. real HTTP handlers, mounted on a stub PromptServer
# ----------------------------------------------------------------------
from aiohttp import web           # noqa: E402
from aiohttp.test_utils import TestServer, TestClient   # noqa: E402


class StubServer:
    def __init__(self):
        self.routes = web.RouteTableDef()


stub = StubServer()
sys.modules["server"] = type("m", (), {"PromptServer": type("P", (), {"instance": stub})})
check("routes registered", mp.register_routes(), True)


async def main():
    app = web.Application()
    app.add_routes(stub.routes)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        print("\n[HTTP /modelpreview/list]")
        for kind in picker_kinds:
            r = await client.get("/modelpreview/list?kind=%s" % kind)
            body = await r.json()
            folder = mp.kind_to_folder(kind)
            names = [n for n in (mc.list_models(folder).get(mc.norm_kind(kind)) or [])]
            check("HTTP 200 %s" % kind, r.status, 200)
            if folder == mc.norm_kind(kind):
                check("  items == engine list (%s)" % kind, body["total"], len(names))
            # every listed item must carry the picker's card fields
            if body.get("items"):
                check("  item shape (%s)" % kind,
                      sorted(body["items"][0].keys()), ["basename", "hasPreview", "name"])

        r = await client.get("/modelpreview/list?kind=upscale_models")
        body = await r.json()
        print("\n[upscale picker payload]")
        print("  folder=%s total=%s withPreview=%s" % (body["folder"], body["total"], body["withPreview"]))
        for it in body["items"]:
            print("   - %s (preview=%s)" % (it["name"], it["hasPreview"]))
        check("upscale_models total", body["total"], 6)
        check("upscale_models folder", body["folder"], "upscale_models")

        r = await client.get("/modelpreview/list?kind=bogus")
        check("unknown kind is a 400, not an empty 200", r.status, 400)

        print("\n[HTTP /modelpreview/img]")
        r = await client.get("/modelpreview/img?kind=upscale_models&name=../../secret.txt")
        check("path traversal refused", r.status, 404)
        r = await client.get("/modelpreview/img?kind=upscale_models&name=4x-AnimeSharp.pth")
        check("no sidecar -> 404", r.status, 404)
    finally:
        await client.close()


asyncio.run(main())

print("\nFAILURES:", fail)
sys.exit(1 if fail else 0)
