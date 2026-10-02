# -*- coding: utf-8 -*-
"""Sanity check for tests/test_routes.py: does it FAIL on the broken 2026-09-16 shape?

Rebuilds the old file (the 4 delete/rename handlers *after* the body-level
`return True`) in a scratch copy and runs the regression test against it.
The test must report failure - otherwise it would not have caught the bug.
"""

import os
import shutil
import subprocess
import sys
import tempfile

REPO = r"C:\ComfyUI-SmartCLIP"
SRC = os.path.join(REPO, "src")
PY = r"C:\ComfyUI_windows_portable\python_embeded\python.exe"
MARK = "    # ---- 删除词条 ----"

scratch = tempfile.mkdtemp(prefix="smartclip-broken-")
dst = os.path.join(scratch, "src")
shutil.copytree(SRC, dst)

api = os.path.join(dst, "smart_clip_api.py")
with open(api, "r", encoding="utf-8") as handle:
    text = handle.read()

# re-create the bug: close register_routes() before the delete/rename handlers
assert MARK in text, "marker not found - the source layout changed"
broken = text.replace(MARK, "    return True\n" + MARK, 1)
# ...and drop the trailing good return, exactly like the old file
broken = broken.replace('''    _REGISTERED = True
    log.info("[SmartCLIP] routes registered: /smart_clip/presets (+/save, +/save_many, "
             "+/delete, +/delete_category, +/rename_category, +/create_category), "
             "/smart_clip/classify, /smart_clip/text, /smart_clip/detect, /smart_clip/info, "
             "/smart_clip/reload, /smart_clip/embeddings (+/img)")
    return True
''', "")
with open(api, "w", encoding="utf-8") as handle:
    handle.write(broken)

env = dict(os.environ, SMARTCLIP_SRC=dst)
proc = subprocess.run([PY, os.path.join(REPO, "tests", "test_routes.py")],
                      env=env, capture_output=True, text=True)

print(proc.stdout)
if proc.stderr.strip():
    print("--- stderr ---")
    print(proc.stderr)

print("scratch: %s" % dst)
expected_fail = proc.returncode == 1 and "route not declared" in proc.stdout
print("VERDICT: %s" % ("PASS - test fails on the broken file" if expected_fail
                       else "FAIL - test did not catch the regression"))
sys.exit(0 if expected_fail else 1)
