# -*- coding: utf-8 -*-
"""
Is `google-generativeai` the ONLY thing ComfyUI-Gemini is missing?

Instead of telling the user "install it and see", stub out the google package
with a minimal fake and import the pack for real.  If it then loads and reports
its node count, the dependency list is proven sufficient.  If it fails on a
deeper symbol/import, that shows up here too.
"""

import os
import shutil
import subprocess
import sys

PY = r"C:\ComfyUI_windows_portable\python_embeded\python.exe"
COMFY = r"C:\ComfyUI_windows_portable\ComfyUI"
PACK = os.path.join(COMFY, "custom_nodes", "ComfyUI-Gemini")
STUB = os.path.join(r"C:\ComfyUI-InstallMissing", "_stub_google")

# what the pack actually calls on the module (grep-verified below)
if os.path.isdir(STUB):
    shutil.rmtree(STUB)
os.makedirs(os.path.join(STUB, "google", "generativeai"), exist_ok=True)

open(os.path.join(STUB, "google", "__init__.py"), "w").write("")
open(os.path.join(STUB, "google", "generativeai", "__init__.py"), "w").write('''
"""Minimal stand-in used only to test the import chain."""
from . import types as _types


class _Anything:
    def __init__(self, *a, **k):
        pass

    def __call__(self, *a, **k):
        return self

    def __getattr__(self, name):
        return _Anything()

    def generate_content(self, *a, **k):
        return _Anything()


def configure(*a, **k):
    return None


def GenerativeModel(*a, **k):
    return _Anything()


Part = _Anything()
''')
open(os.path.join(STUB, "google", "generativeai", "types.py"), "w").write(
    "class Part:\n    def __init__(self, *a, **k):\n        pass\n")

# what does the pack import from google?
print("=== ComfyUI-Gemini 里与 google 相关的 import ===")
for root, _dirs, files in os.walk(PACK):
    if ".git" in root:
        continue
    for fn in files:
        if fn.endswith(".py"):
            path = os.path.join(root, fn)
            for i, line in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
                if "google" in line.lower() and ("import" in line or "genai" in line):
                    print("  %s:%d  %s" % (os.path.relpath(path, PACK), i, line.strip()))

PROBE = r'''
import importlib.util, os, sys, traceback
comfy = r"__COMFY__"
pack = r"__PACK__"
stub = r"__STUB__"
sys.path.insert(0, stub)
sys.path.insert(0, comfy)
sys.path.insert(0, pack)
os.chdir(pack)
try:
    spec = importlib.util.spec_from_file_location("probe_gemini", os.path.join(pack, "__init__.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["probe_gemini"] = mod
    spec.loader.exec_module(mod)
    print("RESULT OK nodes=%d" % len(getattr(mod, "NODE_CLASS_MAPPINGS", {}) or {}))
except BaseException as exc:
    chain, seen, cur = [], set(), exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        chain.append("%s: %s" % (type(cur).__name__, str(cur)[:140]))
        cur = cur.__cause__ or cur.__context__
    print("RESULT FAIL " + " <- ".join(chain))
'''

code = PROBE.replace("__COMFY__", COMFY).replace("__PACK__", PACK).replace("__STUB__", STUB)
out = subprocess.run([PY, "-c", code], capture_output=True, text=True,
                     encoding="utf-8", errors="replace", timeout=300)
print()
print("=== 用 google 桩模块导入 ComfyUI-Gemini ===")
for line in (out.stdout or "").splitlines():
    if line.startswith("RESULT"):
        print("  " + line)
if not (out.stdout or "").strip():
    print("  stderr:", (out.stderr or "").strip().splitlines()[-1:])
