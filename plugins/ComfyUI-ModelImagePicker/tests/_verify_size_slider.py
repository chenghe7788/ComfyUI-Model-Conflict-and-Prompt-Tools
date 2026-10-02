# -*- coding: utf-8 -*-
"""Guard: the "image size" slider must be present on EVERY picker open path.

Regression this guards (2026-09-16): the intercepted native model menu used to
pass `showSize: false`, so opening the model list from a node widget - the
common case - showed a modal WITHOUT the thumbnail-size control.  The user saw
it as "模型弹窗上面的调整图片大小没有了".

The check is deliberately byte-level: it validates the file the BROWSER will
receive (over HTTP), not just the one on disk, so a failed deploy is caught too.

MCM_BASE selects the instance; for the user's live one use
    set MCM_BASE=http://127.0.0.1:8188
"""
import os
import sys
import urllib.request

BASE = os.environ.get("MCM_BASE", "http://127.0.0.1:8189").rstrip("/")
URL = BASE + "/extensions/ComfyUI_ModelImagePicker/model_image_picker.js"

fail = 0


def check(label, ok, detail=""):
    global fail
    if not ok:
        fail += 1
    print("   %-4s %s%s" % ("OK" if ok else "FAIL", label, ("  " + detail) if detail else ""))


with urllib.request.urlopen(URL, timeout=30) as resp:
    raw = resp.read()
    ctype = resp.headers.get("Content-Type")
text = raw.decode("utf-8")

print("model_image_picker.js  %d bytes  Content-Type=%s" % (len(raw), ctype))
check("served as utf-8", "text/javascript" in (ctype or ""))

# 1. The takeover call site must not switch the slider off.
check("no `showSize: false` option literal", "showSize: false," not in text)
check("takeover passes showSize: true", "showSize: true," in text)

# 2. The slider itself must still exist and be wired to the grid width.
check("slider markup built", 'this.sizeEl.type = "range"' in text)
check("slider hidden only via the showSize guard",
      "if (!this.showSize) sizeWrap.style.display = \"none\";" in text)
check("width applied to the grid", "--mip-cell" in text)
check("width persisted", 'localStorage.setItem(CELL_STORE_KEY' in text)
check("Chinese label present", "\\u56fe\\u7247\\u5927\\u5c0f" in text)  # 图片大小

print("\nFAILURES:", fail)
sys.exit(1 if fail else 0)
