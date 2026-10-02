# -*- coding: utf-8 -*-
"""
Workflow -> missing custom node packs
=====================================
Answers: "which of my workflows need nodes I don't have, and which repository
provides each of them?"

Sources
-------
* every workflow JSON under ComfyUI/user/default/workflows (UI format with
  "nodes", API format with class_type, and the .bak copies)
* /object_info of a running ComfyUI  -> the node types that ARE registered
* ComfyUI-Manager's own databases, used offline so no network is required:
    extension-node-map.json : repo url -> [node types]
    custom-node-list.json   : repo url -> title / install_type / pip requirements

Output
------
report_missing.json  (machine readable, consumed by install_missing.ps1)
and a readable summary on stdout.
"""

import json
import os
import sys
import urllib.request

WORKFLOWS = r"C:\ComfyUI_windows_portable\ComfyUI\user\default\workflows"
MANAGER = r"C:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI-Manager-main"
CUSTOM_NODES = r"C:\ComfyUI_windows_portable\ComfyUI\custom_nodes"
BASE = os.environ.get("MCM_BASE", "http://127.0.0.1:8189")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_missing.json")


# ---------------------------------------------------------------- workflows
def iter_node_types(data):
    """Yield every node type in a workflow, whatever format it is in."""
    if isinstance(data, dict) and isinstance(data.get("nodes"), list):
        for node in data["nodes"]:
            if isinstance(node, dict) and node.get("type"):
                yield str(node["type"])
        # newer UI files can carry subgraph definitions with their own nodes
        for key in ("definitions", "subgraphs"):
            for sub in (data.get(key) or {}).values() if isinstance(data.get(key), dict) else []:
                yield from iter_node_types(sub)
    elif isinstance(data, dict) and all(
            isinstance(v, dict) and "class_type" in v for v in data.values()) and data:
        for node in data.values():
            yield str(node["class_type"])


def scan_workflows():
    files = []
    for root, _dirs, names in os.walk(WORKFLOWS):
        for name in sorted(names):
            if not (name.lower().endswith(".json") or name.lower().endswith(".bak")):
                continue
            path = os.path.join(root, name)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except Exception as exc:
                print("  ! skipped %s (%s)" % (name, type(exc).__name__))
                continue
            types = sorted(set(iter_node_types(data)))
            if types:
                files.append({"file": name, "path": path, "types": types})
    return files


# ---------------------------------------------------------------- installed
def installed_types():
    with urllib.request.urlopen(BASE + "/object_info", timeout=120) as resp:
        info = json.loads(resp.read().decode("utf-8"))
    return set(info.keys())


def installed_dirs():
    out = {}
    for name in os.listdir(CUSTOM_NODES):
        full = os.path.join(CUSTOM_NODES, name)
        if not os.path.isdir(full) or name.startswith("__") or name.startswith("."):
            continue
        out[name.lower()] = full
    return out


# ---------------------------------------------------------------- databases
def load_manager_db():
    with open(os.path.join(MANAGER, "extension-node-map.json"), "r", encoding="utf-8") as handle:
        node_map = json.load(handle)
    with open(os.path.join(MANAGER, "custom-node-list.json"), "r", encoding="utf-8") as handle:
        catalogue = json.load(handle)

    type_to_repo = {}
    for repo, value in node_map.items():
        types = value[0] if isinstance(value, list) and value else []
        title = ""
        if isinstance(value, list) and len(value) > 1 and isinstance(value[1], dict):
            title = value[1].get("title_aux", "")
        for node_type in types or []:
            type_to_repo.setdefault(str(node_type), {"repo": repo, "title": title})

    by_repo = {}
    for entry in catalogue.get("custom_nodes", []):
        for key in filter(None, [entry.get("reference")] + list(entry.get("files") or [])):
            by_repo[key] = entry
            by_repo[key.rstrip("/").replace(".git", "")] = entry
    return type_to_repo, by_repo


def main():
    print("=" * 92)
    print("1. workflows")
    print("=" * 92)
    files = scan_workflows()
    all_types = sorted({t for f in files for t in f["types"]})
    print("  %d workflow files, %d distinct node types" % (len(files), len(all_types)))

    print()
    print("=" * 92)
    print("2. registered node types (live ComfyUI at %s)" % BASE)
    print("=" * 92)
    try:
        have = installed_types()
    except Exception as exc:
        print("  cannot reach ComfyUI: %s" % exc)
        return 1
    print("  %d node types registered" % len(have))

    missing = [t for t in all_types if t not in have]
    print("  %d MISSING node types" % len(missing))
    if not missing:
        print("\nnothing to install - every workflow node type is available.")
        return 0

    print()
    print("=" * 92)
    print("3. which pack provides each missing type (Manager DB, offline)")
    print("=" * 92)
    type_to_repo, by_repo = load_manager_db()
    dirs = installed_dirs()

    packs = {}
    unmapped = []
    for node_type in missing:
        info = type_to_repo.get(node_type)
        if not info:
            unmapped.append(node_type)
            continue
        repo = info["repo"]
        entry = by_repo.get(repo) or by_repo.get(repo.rstrip("/").replace(".git", "")) or {}
        pack = packs.setdefault(repo, {
            "repo": repo,
            "title": entry.get("title") or info["title"] or repo.rsplit("/", 1)[-1],
            "install_type": entry.get("install_type", "git-clone"),
            "pip": entry.get("pip") or [],
            "types": [],
            "workflows": set(),
        })
        pack["types"].append(node_type)

    for pack in packs.values():
        for f in files:
            if set(pack["types"]) & set(f["types"]):
                pack["workflows"].add(f["file"])

    # is it maybe already on disk under another name?
    for pack in packs.values():
        guess = pack["repo"].rstrip("/").rsplit("/", 1)[-1].lower()
        pack["local_dir"] = next((d for d in dirs if d == guess or guess in d or d in guess), "")

    ordered = sorted(packs.values(), key=lambda p: (-len(p["types"]), p["title"].lower()))
    for pack in ordered:
        flag = " [已在本地存在: %s]" % pack["local_dir"] if pack["local_dir"] else ""
        print("\n  %s%s" % (pack["title"], flag))
        print("    repo   : %s" % pack["repo"])
        print("    install: %s%s" % (pack["install_type"],
                                    ("  pip: " + ", ".join(pack["pip"])) if pack["pip"] else ""))
        print("    缺失节点(%d): %s" % (len(pack["types"]), ", ".join(pack["types"][:8])
                                      + (" ..." if len(pack["types"]) > 8 else "")))
        print("    影响工作流: %s" % ", ".join(sorted(pack["workflows"])[:4])
              + (" ..." if len(pack["workflows"]) > 4 else ""))

    if unmapped:
        print()
        print("  --- 数据库里没查到来源的节点类型（可能来自工作流内嵌/自定义/已改名）---")
        for t in unmapped:
            print("    %s" % t)

    report = {
        "generated_from": BASE,
        "workflow_count": len(files),
        "missing_types": missing,
        "unmapped_types": unmapped,
        "packs": [{
            "title": p["title"],
            "repo": p["repo"],
            "install_type": p["install_type"],
            "pip": p["pip"],
            "types": sorted(p["types"]),
            "workflows": sorted(p["workflows"]),
            "local_dir": p["local_dir"],
        } for p in ordered],
    }
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print()
    print("=" * 92)
    print("需安装的插件包: %d 个，报告已写入 %s" % (len(ordered), OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
