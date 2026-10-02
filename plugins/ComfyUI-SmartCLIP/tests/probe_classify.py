# -*- coding: utf-8 -*-
"""
Probe: what would "拆分入库" do to a prompt?

    python tests\\probe_classify.py "masterpiece, 1girl, long hair, red dress, forest"

With no argument it runs a few examples, including a real prompt from the
workspace workflows.  Nothing is written anywhere.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CANDIDATES = [
    os.environ.get("MCM_PLUGIN"),
    os.path.join(os.path.dirname(HERE), "src"),
    os.path.dirname(HERE),
    r"C:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_SmartCLIP",
]
PLUGIN = next((p for p in CANDIDATES if p and os.path.isfile(os.path.join(p, "nodes.py"))), None)
if PLUGIN is None:
    raise SystemExit("cannot find the SmartCLIP plugin files; set MCM_PLUGIN")
sys.path.insert(0, PLUGIN)

import classify as cl          # noqa: E402

EXAMPLES = [
    "masterpiece, best quality, 1girl, solo, long hair, silver hair, red dress, "
    "thighhighs, forest, night, soft lighting, close-up",
    "杰作, 女孩, 双马尾, 白色衬衫, 城市夜景, 逆光",
    "(red dress:1.2), [long hair], BREAK, masterpiece",
]


def show(text):
    result = cl.plan(text)
    print("-" * 92)
    print("prompt:", text[:88] + ("…" if len(text) > 88 else ""))
    print("rules :", result["source"], "·", len(result["categories"]), "个分类，",
          "fallback =", result["fallback"])
    for item in result["tags"]:
        print("   %-34s -> %s" % (item["text"][:34], item["category"]))
    print("counts:", result["counts"])


if __name__ == "__main__":
    if len(sys.argv) > 1:
        show(" ".join(sys.argv[1:]))
    else:
        for text in EXAMPLES:
            show(text)
        print("-" * 92)
        print("rules file:", cl.info())
