# -*- coding: utf-8 -*-
"""
Why does each freshly installed pack fail to import?

Imports every custom node pack in a *separate* subprocess (so one broken pack
cannot poison the next) and prints the exception chain - including the
__cause__/__context__ - which is where the real "No module named 'x'" lives.
"""

import os
import subprocess
import sys

COMFY = r"C:\ComfyUI_windows_portable\ComfyUI"
PY = r"C:\ComfyUI_windows_portable\python_embeded\python.exe"
NODES = os.path.join(COMFY, "custom_nodes")

TARGETS = [
    "ComfyUI-ArtGallery",
    "ComfyUI-Gemini",
    "ComfyUI-Flowty-TripoSR-ZHO",
    "ComfyUI-LivePortraitKJ",
    "ComfyUI-Qwen",
    "ComfyUI-BRIA_AI-RMBG",
    "comfyui-portrait-master-zh-cn",
    "ComfyUI-VideoHelperSuite",
    "rgthree-comfy",
    "comfyui_controlnet_aux",
]

PROBE = r'''
import importlib.util, os, sys, traceback
comfy = r"__COMFY__"
pack = r"__PACK__"
sys.path.insert(0, comfy)
sys.path.insert(0, pack)
os.chdir(pack)
init = os.path.join(pack, "__init__.py")
if not os.path.isfile(init):
    print("RESULT NO_INIT (没有 __init__.py，可能是纯前端/工作流仓库)")
    raise SystemExit(0)
try:
    spec = importlib.util.spec_from_file_location("probe_pack", init)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["probe_pack"] = mod
    spec.loader.exec_module(mod)
    n = len(getattr(mod, "NODE_CLASS_MAPPINGS", {}) or {})
    print("RESULT OK nodes=%d" % n)
except BaseException as exc:
    chain = []
    seen = set()
    cur = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        chain.append("%s: %s" % (type(cur).__name__, str(cur)[:160]))
        cur = cur.__cause__ or cur.__context__
    print("RESULT FAIL " + " <- ".join(chain))
'''

print("%-32s %s" % ("PACK", "RESULT"))
print("-" * 100)
problems = {}
for name in TARGETS:
    pack = os.path.join(NODES, name)
    if not os.path.isdir(pack):
        print("%-32s %s" % (name, "MISSING ON DISK"))
        continue
    code = PROBE.replace("__COMFY__", COMFY).replace("__PACK__", pack)
    try:
        out = subprocess.run([PY, "-c", code], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=180)
        result = next((ln for ln in (out.stdout or "").splitlines() if ln.startswith("RESULT")), "")
        if not result:
            tail = (out.stderr or "").strip().splitlines()[-1:] or ["(no output)"]
            result = "RESULT ? " + tail[0][:150]
    except subprocess.TimeoutExpired:
        result = "RESULT TIMEOUT (>180s)"
    print("%-32s %s" % (name, result.replace("RESULT ", "")))
    if "FAIL" in result or "?" in result:
        problems[name] = result

print()
if problems:
    print("需要处理:", ", ".join(problems))
else:
    print("全部可导入")
