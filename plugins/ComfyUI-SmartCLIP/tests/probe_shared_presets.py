# -*- coding: utf-8 -*-
"""
"新建的分类在所有的提示词弹窗都能看到" 的实测脚本（不依赖 ComfyUI）。

    python tests\\probe_shared_presets.py [presets.json 路径]

用真实词库（默认取部署副本）的一个**临时拷贝**跑，绝不动原文件：
  1) 迁移：模型族里属于用户自建的分类收拢进 _shared，模型族自带的预设原地不动；
  2) 可见性：一个族里建的分类，在另一个族的弹窗里也能查到（正/反向各自独立）；
  3) 隔离：pony 的评分标签、flux 的描述模板这类族内预设在别的族里**不**出现；
  4) 写路径：新分类/新词条落在 _shared 而不是当前模型族；
  5) 删除：在任意一个族里删掉分类，别的族里也跟着消失。
"""

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.environ.get("MCM_PLUGIN")
if not PLUGIN:
    for candidate in (os.path.join(os.path.dirname(HERE), "src"), os.path.dirname(HERE)):
        if os.path.isfile(os.path.join(candidate, "presets.py")):
            PLUGIN = candidate
            break
if not PLUGIN:
    PLUGIN = r"C:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_SmartCLIP"
sys.path.insert(0, PLUGIN)

import presets as ps  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILS.append("%s: got %r want %r" % (label, got, want))
    print("  %-4s %-62s %s" % ("OK" if ok else "FAIL", label,
                               got if ok else "got %r want %r" % (got, want)))


def categories(model, role):
    return ps.load(model, role)["categories"]


def main(argv):
    source = argv[1] if len(argv) > 1 else os.path.join(
        r"C:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_SmartCLIP",
        "prompt_presets", "presets.json")
    print("word list: %s" % source)
    with open(source, "r", encoding="utf-8") as handle:
        before = json.load(handle)

    workdir = tempfile.mkdtemp(prefix="smartclip-shared-")
    target = os.path.join(workdir, "presets.json")
    shutil.copyfile(source, target)
    original = ps.PRESET_FILE
    try:
        ps.PRESET_FILE = target
        ps.clear_cache()

        # ---- 1. 迁移 -------------------------------------------------
        print("\n[1] 迁移：自建分类 -> _shared")
        family_user_before = [
            (fam, role, name)
            for fam, body in before.items() if not fam.startswith("_")
            for role, cats in (body.items() if isinstance(body, dict) else [])
            if isinstance(cats, dict) and role in ps.ROLES
            for name in cats if name not in (ps._builtin_for(fam).get(role) or {})
        ]
        print("     迁移前散落在各模型族的自建分类: %d 个" % len(family_user_before))
        ps.load("generic", "positive")           # 第一次 load 触发迁移
        with open(target, "r", encoding="utf-8") as handle:
            after = json.load(handle)
        check("文件里出现 _shared 段", isinstance(after.get(ps.SHARED_MODEL), dict), True)
        left = [
            (fam, role, name)
            for fam, body in after.items() if not fam.startswith("_")
            for role, cats in (body.items() if isinstance(body, dict) else [])
            if isinstance(cats, dict) and role in ps.ROLES
            for name in cats if name not in (ps._builtin_for(fam).get(role) or {})
        ]
        check("模型族里不再有自建分类", left, [])
        check("迁移前确实有东西可迁", len(family_user_before) > 0, True)
        check("迁移留了一次性备份",
              os.path.isfile(target + ps.MIGRATION_SUFFIX), True)
        check("迁移是幂等的（第二次 load 不再写盘）",
              ps._promote_user_categories(), [])

        # ---- 2. 可见性：任意族都能看到 -------------------------------
        print("\n[2] 可见性：一个族里建的分类，别的族也看得到")
        shared_pos = ps.shared_summary()["positive"]
        check("共享段里有正向分类", len(shared_pos) > 0, True)
        sample = "蝴蝶忍" if "蝴蝶忍" in shared_pos else shared_pos[0]
        for fam in ("generic", "sd15", "sdxl", "pony", "illustrious", "sd3", "flux"):
            check("%-12s 正向弹窗能看到 %s" % (fam, sample),
                  sample in categories(fam, "positive"), True)
        check("反向弹窗看不到正向分类", sample in categories("illustrious", "negative"), False)

        shared_neg = ps.shared_summary()["negative"]
        check("共享段里有反向分类", len(shared_neg) > 0, True)
        # 同一个名字（比如误建的 "1"）可以正反向各有一份，那是两条独立词条；
        # 这里挑一个只在反向存在的分类，用来验证方向是隔离的。
        neg_sample = next((n for n in shared_neg if n not in shared_pos), shared_neg[0])
        check("反向分类在任意族的反面弹窗可见（illustrious）",
              neg_sample in categories("illustrious", "negative"), True)
        check("反向分类不会跑进正向弹窗",
              neg_sample in categories("illustrious", "positive"), False)

        # ---- 3. 族内预设没有被摊平 -----------------------------------
        print("\n[3] 隔离：模型族自带的预设仍然只属于那个族")
        check("pony 的评分标签不会跑到 illustrious",
              "评分标签" in categories("illustrious", "positive"), False)
        check("...但它自己还在 pony 里",
              "评分标签" in categories("pony", "positive"), True)
        check("flux 的描述模板不会跑到 pony",
              "描述模板" in categories("pony", "positive"), False)
        check("pony 自己的族内预设没被搬走",
              "评分标签" in ps._bucket(after, "pony", "positive"), True)

        # ---- 4. 写路径 ------------------------------------------------
        print("\n[4] 写路径：新分类/新词条落到 _shared")
        report = ps.add_entry("illustrious", "positive", sample, "new butterfly tag")
        check("往自建分类里加词条 -> 共享段",
              report["stored_in"], ps.SHARED_MODEL)
        check("...在别的族立刻可见",
              "new butterfly tag" in categories("pony", "positive").get(sample, []), True)

        created = ps.create_category("flux", "positive", "临时新分类")
        check("新建分类 -> 共享段", created["stored_in"], ps.SHARED_MODEL)
        check("...在别的族也能看到", "临时新分类" in categories("sd15", "positive"), True)

        builtin = ps.add_entry("sdxl", "positive", "质量词", "my own quality word")
        check("族内预设分类仍写回该族", builtin["stored_in"], "sdxl")
        check("...不会污染别的族的同名预设",
              "my own quality word" in categories("flux", "positive").get("质量词", []), False)
        check("...在本族可见",
              "my own quality word" in categories("sdxl", "positive").get("质量词", []), True)

        # ---- 5. 删除 / 重命名是全局的 ---------------------------------
        print("\n[5] 删除 / 重命名：自建分类是同一个分类")
        renamed = ps.rename_category("generic", "positive", "临时新分类", "改名后的分类")
        check("重命名成功", renamed["ok"], True)
        check("...在别的族也改了名",
              "改名后的分类" in categories("sdxl", "positive"), True)
        removed = ps.delete_category("illustrious", "positive", "改名后的分类")
        check("删除成功", removed["ok"], True)
        check("...在别的族也消失了",
              "改名后的分类" in categories("sd15", "positive"), False)

        dropped = ps.delete_entry("pony", "positive", sample, "new butterfly tag")
        check("删词条成功", dropped["ok"], True)
        check("...别的族里也没了",
              "new butterfly tag" in categories("illustrious", "positive").get(sample, []), False)

        # ---- 6. 旧文件兼容 -------------------------------------------
        print("\n[6] 兼容：坏文件 / 老版本文件")
        broken = os.path.join(workdir, "broken.json")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write("{ not json ]")
        ps.PRESET_FILE = broken
        ps.clear_cache()
        check("坏文件不炸，回落内置", ps.load("pony", "positive")["source"], "builtin")
        check("坏文件不被迁移写坏",
              open(broken, encoding="utf-8").read(), "{ not json ]")
    finally:
        ps.PRESET_FILE = original
        ps.clear_cache()
        shutil.rmtree(workdir, ignore_errors=True)

    print()
    if FAILS:
        print("FAILURES: %d" % len(FAILS))
        for line in FAILS:
            print("  -", line)
        return 1
    print("FAILURES: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
