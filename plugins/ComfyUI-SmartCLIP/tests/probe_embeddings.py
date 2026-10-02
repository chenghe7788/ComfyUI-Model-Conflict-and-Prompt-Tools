# -*- coding: utf-8 -*-
"""
Probe: classify the textual inversions installed on this machine.

    set SMARTCLIP_EMBEDDINGS_DIR=D:\\...\\ComfyUI\\models\\embeddings
    python tests\\probe_embeddings.py

Prints, for every embedding file, what the dialog would badge it as, and what
the shipped word-list entries resolve to for each model family.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# Source checkout (tests/../src), deployed layout (tests/..), or MCM_PLUGIN.
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

import embedding_compat as ec          # noqa: E402
import presets as ps                   # noqa: E402


def main():
    print("=" * 92)
    print("dirs:", ec.embedding_dirs())
    index = ec.embedding_index()
    print("installed:", len(index))
    print("=" * 92)
    for name in sorted(index):
        info = ec.classify(index[name])
        print("  %-42s %-10s %s" % (name[:42], info["short"], info["evidence"]))

    print()
    print("=" * 92)
    print("what the shipped word lists say")
    print("=" * 92)
    for family in ("sd15", "sdxl", "pony", "illustrious", "flux"):
        for role in ("negative",):
            data = ps.load(family, role)
            seen = []
            for category, prompts in data["categories"].items():
                for text in prompts:
                    if "embedding:" in text.lower():
                        ann = data["annotations"].get(text) or {}
                        seen.append("%s -> %s (%s)" % (text, ann.get("state", "?"),
                                                       ann.get("why", "")))
            print("\n[%s/%s] stats=%s" % (family, role, data["embedding_stats"]))
            for line in seen:
                print("   ", line)


if __name__ == "__main__":
    main()
