# -*- coding: utf-8 -*-
"""The browser must receive the extension files as valid UTF-8 with the Chinese
labels intact; this checks the bytes exactly as the server sends them.

Override the target with MCM_BASE, e.g. set MCM_BASE=http://127.0.0.1:8188
"""
import os
import sys
import urllib.request

BASE = os.environ.get("MCM_BASE", "http://127.0.0.1:8189").rstrip("/") \
    + "/extensions/ComfyUI_ModelImagePicker/"

CHECK = {
    "model_conflict.js": [
        "基准: ", "冲突", "兼容",
        # written as \u escapes in the source, so the file holds the escapes
        "\\u5de5\\u4f5c\\u6d41\\u9700\\u8981",   # 工作流需要
        "\\u6682\\u4e0d\\u7740\\u8272",           # 暂不着色
        "mip-cf-red", "mip-cf-blue", "embedding:",
    ],
    "model_image_picker.js": [
        "大模型", "词嵌入", "文本编码器", "检测模型",
        ".mip-card.mip-cf-red:not(.mip-sel)",
        ".mip-card.mip-cf-blue:not(.mip-sel)",
        'from "./model_conflict.js"',
        # a failed list request must not look like an empty model folder
        "renderLoadError", "list-failed", "\\u52a0\\u8f7d\\u5931\\u8d25",   # 加载失败
    ],
}

fail = 0
for name, needles in CHECK.items():
    with urllib.request.urlopen(BASE + name, timeout=30) as resp:
        raw = resp.read()
        ctype = resp.headers.get("Content-Type")
    try:
        text = raw.decode("utf-8")
        decoded = True
        err = ""
    except UnicodeDecodeError as exc:
        text, decoded, err = "", False, str(exc)

    print("%-24s %6d bytes  Content-Type=%s  utf-8=%s" % (name, len(raw), ctype, decoded))
    if not decoded:
        fail += 1
        print("   FAIL:", err)
        continue
    if raw.startswith(b"\xef\xbb\xbf"):
        print("   note: served with a UTF-8 BOM")
    for needle in needles:
        ok = needle in text
        if not ok:
            fail += 1
        print("   %-4s %r" % ("OK" if ok else "FAIL", needle))

print("\nFAILURES:", fail)
sys.exit(1 if fail else 0)
