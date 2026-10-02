# -*- coding: utf-8 -*-
"""
合并后的 SmartCLIP 集成自测（只读，不碰正在跑的实例）

  1. 把本插件目录拷到 <ComfyUI>/custom_nodes 下的临时包目录
     （因此 __init__.py 的同级相对导入走真实路径）
  2. 导入并核对：词库、嵌入列表、兼容判定、侧车预览图
  3. 结束后删除临时目录

需要一份 ComfyUI 安装（用来 import folder_paths）：用 MCM_COMFY 指到
"包含 custom_nodes 的那个目录"；探测不到就直接 SKIP，不会去猜路径。
插件源码默认取本文件的上上级目录，也可以用 MCM_PLUGIN 覆盖。
"""
import json
import os
import shutil
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
COMFY = os.environ.get("MCM_COMFY") or r"C:\ComfyUI_windows_portable\ComfyUI"
SRC = os.environ.get("MCM_PLUGIN") or os.path.dirname(HERE)
TMPNAME = "ComfyUI__sc_merge_probe"
TMP = os.path.join(COMFY, "custom_nodes", TMPNAME)

if not os.path.isdir(os.path.join(COMFY, "custom_nodes")):
    print("SKIP: this test needs a ComfyUI install (for folder_paths).")
    print("      set MCM_COMFY to the folder that contains custom_nodes; tried: %s" % COMFY)
    raise SystemExit(0)

report = {"ok": [], "fail": [], "info": {}}


def check(name, fn):
    try:
        value = fn()
        report["ok"].append(name)
        print("[ok] %s -> %s" % (name, value))
        return value
    except Exception as exc:
        report["fail"].append("%s: %s: %s" % (name, type(exc).__name__, exc))
        print("[FAIL] %s: %s" % (name, exc))
        traceback.print_exc()
        return None


def main():
    sys.path.insert(0, COMFY)
    sys.path.insert(0, os.path.join(COMFY, "custom_nodes"))
    if os.path.isdir(TMP):
        shutil.rmtree(TMP)
    shutil.copytree(SRC, TMP, ignore=shutil.ignore_patterns("__pycache__"))
    print("temp package:", TMP)

    import importlib
    pkg = importlib.import_module(TMPNAME)
    print("package loaded:", pkg)

    ep = importlib.import_module(TMPNAME + ".embedding_preview")
    compat = importlib.import_module(TMPNAME + ".embedding_compat")

    # --- 1. 嵌入索引 / 列表 ---
    idx = check("embedding_index", lambda: len(compat.embedding_index()))
    report["info"]["installed_embeddings"] = idx

    data = check("list_embeddings(sdxl)", lambda: ep.list_embeddings("sdxl"))
    if data:
        report["info"]["total"] = data["total"]
        report["info"]["with_preview"] = data["withPreview"]
        report["info"]["states"] = data["states"]
        print("    items:", [(i["name"], i["hasPreview"],
                              (i.get("compat") or {}).get("state")) for i in data["items"]])
        check("list has names", lambda: [i["name"] for i in data["items"]][:5])
        check("每项都有 preview 字段", lambda: all("preview" in i for i in data["items"]))

    # --- 2. 解析一致性：列表里的每个名字都必须 resolve 得到 ---
    def resolve_all():
        names = [i["name"] for i in (data or {}).get("items", [])]
        bad = [n for n in names if compat.resolve(n) is None and compat.resolve("embedding:" + n) is None]
        assert not bad, "resolve 失败: %s" % bad
        return "%d/%d 全部可解析" % (len(names), len(names))
    check("列表名字全部可 resolve", resolve_all)

    # --- 3. 预览图：有 hasPreview 的必须真的能取到文件，且 MIME 认识 ---
    def preview_consistency():
        items = (data or {}).get("items", [])
        img = [i for i in items if i["hasPreview"]]
        missing = [i["name"] for i in img if ep.preview_path(i["name"]) is None]
        assert not missing, "声明有图但取不到: %s" % missing
        exts = sorted({os.path.splitext(ep.preview_path(i["name"]))[1].lower() for i in img})
        unknown = [e for e in exts if e not in ep._MIME]
        assert not unknown, "MIME 缺失: %s" % unknown
        return "%d 张图, 后缀=%s" % (len(img), exts)
    check("预览图与声明一致", preview_consistency)

    # --- 4. 兼容判定：与提示词弹窗同源（annotate），且族切换会变状态 ---
    def verdict_same_source():
        items = (data or {}).get("items", [])
        for i in items:
            want = compat.annotate("embedding:" + i["name"], "sdxl")
            assert i.get("compat") == want or (want is None and not i.get("compat")), \
                "判定不同源: %s" % i["name"]
        return "%d 项与 annotate 完全一致" % len(items)
    check("兼容判定同源", verdict_same_source)

    def family_switch():
        a = ep.list_embeddings("sd15")["states"]
        b = ep.list_embeddings("flux")["states"]
        return "sd15=%s flux=%s" % (a, b)
    check("族切换", family_switch)

    # --- 5. 词库里的 embedding 词条：提示词弹窗的徽标仍然工作 ---
    presets = importlib.import_module(TMPNAME + ".presets")
    loaded = check("presets.load(sdxl, negative)", lambda: presets.load("sdxl", "negative"))
    if loaded:
        report["info"]["annotations"] = len(loaded.get("annotations") or {})
        report["info"]["embedding_stats"] = loaded.get("embedding_stats")
        print("    annotations:", list((loaded.get("annotations") or {}).keys())[:6])
        print("    stats:", loaded.get("embedding_stats"))

    # --- 6. 路由注册（用假的 routes 表，不碰真服务器）---
    class FakeRoutes:
        def __init__(self):
            self.paths = []

        def get(self, path):
            def deco(fn):
                self.paths.append(path)
                return fn
            return deco

        def post(self, path):
            def deco(fn):
                self.paths.append(path)
                return fn
            return deco

    def route_names():
        fake = FakeRoutes()
        ep.register_routes(fake)
        assert "/smart_clip/embeddings" in fake.paths, fake.paths
        assert "/smart_clip/embeddings/img" in fake.paths, fake.paths
        return fake.paths
    check("嵌入路由可注册", route_names)

    def no_legacy_routes():
        """代码里不能再有活的 /embeddinghelper/ 调用（注释里的沿革说明不算）。"""
        hits = []
        for root, dirs, files in os.walk(SRC):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests", "docs", ".git")]
            for f in files:
                if not f.endswith((".py", ".js")):
                    continue
                p = os.path.join(root, f)
                for lineno, line in enumerate(
                        open(p, "r", encoding="utf-8", errors="replace"), 1):
                    if "/embeddinghelper/" not in line:
                        continue
                    stripped = line.strip()
                    if (stripped.startswith("#") or stripped.startswith("//")
                            or stripped.startswith("*") or stripped.startswith('"""')
                            or stripped.startswith("'''")):
                        continue          # 沿革说明：写清楚「合并自哪里」
                    if any("\u4e00" <= ch <= "\u9fff" for ch in line):
                        continue          # 中文行都是文档/注释
                    hits.append("%s:%d %s" % (p, lineno, stripped[:80]))
        assert not hits, "仍有旧路由引用: %s" % hits
        return "无活的 /embeddinghelper/ 引用"
    check("旧路由无残留（源码）", no_legacy_routes)

    shutil.rmtree(TMP, ignore_errors=True)
    print("\n== 汇总 ==")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
