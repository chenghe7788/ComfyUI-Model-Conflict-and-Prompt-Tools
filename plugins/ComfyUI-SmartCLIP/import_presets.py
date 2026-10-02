# -*- coding: utf-8 -*-
"""
SmartCLIP prompt-library importer
=================================
Puts prompts you already have into the word list the dialog shows, without
hand-editing JSON.

    python import_presets.py --list
    python import_presets.py --file my_prompts.json --family sd15 --role negative --category 我的负面
    python import_presets.py --file workflow.json --family sd15 --role positive --category 经典2 --dry-run

Where the word list lives
-------------------------
``<this folder>/prompt_presets/presets.json`` - the deployed copy is
``ComfyUI/custom_nodes/ComfyUI_SmartCLIP/prompt_presets/presets.json``.  Editing
it by hand works too: it is re-read whenever the file changes (mtime-keyed), so
saving is enough - no ComfyUI restart.  In the dialog press 重新加载 (or reopen it)
to see the change.

Accepted input
--------------
1. A ComfyUI **workflow** JSON (the files exported from ComfyUI, e.g. workflow.json):
   the prompt text of every CLIP text-encode node is pulled out and becomes the
   entries of one category.
2. A presets-shaped JSON: ``{"sd15": {"negative": {"分类": ["a", "b"]}}}``.
3. A category map: ``{"分类": ["a", "b"], "另一类": {"prompts": ["c"]}}``.
4. A flat list: ``["a", "b"]``, or ``{"prompts": ["a", "b"]}``, or
   ``{"words": "a, b"}``.
5. Plain text (``.txt`` / ``.md``): one entry per line, commas also split.

Safety
------
* the target file is backed up to ``presets.json.bak-<timestamp>`` first;
* the write is atomic (temp file + replace);
* ``--dry-run`` prints exactly what would change and writes nothing;
* an invalid result is refused rather than saved.
"""

import argparse
import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TARGET = os.path.join(HERE, "prompt_presets", "presets.json")
ROLES = ("positive", "negative")

# Node types whose first widget value is a prompt.
PROMPT_NODES = ("CLIPTextEncode", "CLIPTextEncodeSDXL", "SmartCLIPTextEncode")


# ----------------------------------------------------------------------
# Reading input
# ----------------------------------------------------------------------

def read_text(path):
    with io.open(path, "r", encoding="utf-8-sig", errors="replace") as handle:
        return handle.read()


def read_source(path):
    """The parsed JSON when the file is JSON, otherwise the raw text."""
    raw = read_text(path)
    stripped = raw.lstrip()
    if path.lower().endswith(".json") or stripped[:1] in "[{":
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise SystemExit("not valid JSON (%s): %s" % (exc, path))
    return raw


def entries_of(value):
    """Coerce any supported value into a clean list of non-empty strings."""
    out = []
    if value is None:
        return out
    if isinstance(value, str):
        for line in value.replace("\r", "\n").split("\n"):
            for part in line.split(","):
                part = part.strip()
                if part:
                    out.append(part)
        return out
    if isinstance(value, dict):
        for field in ("prompts", "items", "words", "list"):
            if field in value:
                return entries_of(value[field])
        return out
    if isinstance(value, (list, tuple)):
        for item in value:
            out.extend(entries_of(item))
    elif isinstance(value, (int, float)):
        out.append(str(value))
    return out


def is_workflow(data):
    return (isinstance(data, dict) and isinstance(data.get("nodes"), list)
            and any(isinstance(n, dict) and ("type" in n or "widgets_values" in n)
                    for n in data["nodes"]))


def extract_workflow(data):
    """Prompt texts of a ComfyUI workflow, in node order, de-duplicated."""
    found = []
    for node in data.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        kind = str(node.get("type") or "")
        if not any(name in kind for name in PROMPT_NODES):
            continue
        values = node.get("widgets_values")
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, str) and value.strip():
                found.append(value.strip())
                break
    seen, out = set(), []
    for text in found:
        if text not in seen:
            seen.add(text)
            out.append(text)
    return out


def incoming_categories(data, category):
    """
    ``{category: [entries]}`` for any accepted input shape.
    """
    if isinstance(data, list):
        return {category: entries_of(data)}
    if isinstance(data, str):
        return {category: entries_of(data)}
    if isinstance(data, dict):
        if is_workflow(data):
            return {category: extract_workflow(data)}
        # a category map
        if not any(key in data for key in ROLES) and not _looks_like_family_map(data):
            out = {}
            for name, value in data.items():
                if str(name).startswith("_"):
                    continue
                prompts = entries_of(value)
                if prompts:
                    out[str(name)] = prompts
            if out:
                return out
        # a presets-shaped file
        merged = {}
        for _family, body in data.items():
            if not isinstance(body, dict):
                continue
            for role, cats in body.items():
                if role not in ROLES or not isinstance(cats, dict):
                    continue
                for name, value in cats.items():
                    prompts = entries_of(value)
                    if prompts:
                        merged.setdefault(str(name), []).extend(prompts)
        if merged:
            return merged
        return {category: entries_of(data)}
    return {category: []}


def _looks_like_family_map(data):
    return any(isinstance(v, dict) and any(r in v for r in ROLES) for v in data.values())


def split_input(data, family, role, category, flatten=False):
    """
    ``{family: {role: {category: [entries]}}}`` - what will be merged and where.

    A presets-shaped file keeps its own structure (family + role per category),
    which is what "import another presets.json" has to mean.  Everything else -
    a workflow, a category map, a flat list, plain text - goes to the family and
    role given on the command line.  ``flatten`` forces that for presets-shaped
    input too.
    """
    if is_workflow(data):
        return {family: {role: {category: extract_workflow(data)}}}
    if not flatten and isinstance(data, dict) and _looks_like_family_map(data):
        out = {}
        for fam, body in data.items():
            if str(fam).startswith("_") or not isinstance(body, dict):
                continue
            for r, cats in body.items():
                if r not in ROLES or not isinstance(cats, dict):
                    continue
                for name, value in cats.items():
                    prompts = entries_of(value)
                    if prompts:
                        out.setdefault(fam, {}).setdefault(r, {})[name] = prompts
        if out:
            return out
    return {family: {role: incoming_categories(data, category)}}


# ----------------------------------------------------------------------
# Writing the target
# ----------------------------------------------------------------------

def load_target(path):
    if not os.path.isfile(path):
        return {}
    try:
        data = json.loads(read_text(path))
    except ValueError as exc:
        raise SystemExit("the current presets file is not valid JSON, refusing to "
                         "touch it: %s (%s)" % (path, exc))
    return data if isinstance(data, dict) else {}


def merge(target, family, role, categories):
    body = target.setdefault(family, {})
    if not isinstance(body, dict):
        body = {}
        target[family] = body
    current = body.setdefault(role, {})
    if not isinstance(current, dict):
        current = {}
        body[role] = current
    report = []
    for name, prompts in categories.items():
        before = len(current.get(name) or [])
        merged, seen = [], set()
        for item in list(current.get(name) or []) + list(prompts):
            if item not in seen:
                seen.add(item)
                merged.append(item)
        current[name] = merged
        report.append((name, before, len(merged), len(merged) - before))
    return target, report


def atomic_write(path, data):
    tmp = path + ".tmp-%d" % int(time.time() * 1000)
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(data, ensure_ascii=False, indent=2))
        handle.write("\n")
    # refuse to publish something unreadable
    with io.open(tmp, "r", encoding="utf-8") as handle:
        json.load(handle)
    os.replace(tmp, path)


def describe(target):
    lines = []
    for family, body in sorted(target.items()):
        if str(family).startswith("_") or not isinstance(body, dict):
            continue
        for role in ROLES:
            cats = body.get(role)
            if not isinstance(cats, dict):
                continue
            names = ", ".join("%s(%d)" % (n, len(entries_of(v))) for n, v in cats.items())
            lines.append("  %-14s %-9s %s" % (family, role, names or "-"))
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Import prompts into the SmartCLIP word list.")
    parser.add_argument("--file", "-f", help="the file to import (json / txt / md)")
    parser.add_argument("--family", default="sd15",
                        help="target model family: generic/sd15/sdxl/pony/illustrious/sd3/flux")
    parser.add_argument("--role", default="negative", choices=list(ROLES))
    parser.add_argument("--category", default=None,
                        help="category name (default: the file's base name)")
    parser.add_argument("--target", default=DEFAULT_TARGET,
                        help="presets.json to write (default: the plugin's own)")
    parser.add_argument("--dry-run", action="store_true", help="print the plan only")
    parser.add_argument("--flatten", action="store_true",
                        help="force presets-shaped input into --family/--role "
                             "instead of keeping its own structure")
    parser.add_argument("--list", action="store_true",
                        help="show what the word list currently contains, then exit")
    args = parser.parse_args(argv)

    target = load_target(args.target)
    print("word list : %s" % args.target)
    print("exists    : %s" % os.path.isfile(args.target))

    if args.list or not args.file:
        print("\ncurrent contents")
        for line in describe(target):
            print(line)
        if not args.file:
            print("\nnothing imported (no --file); see --help for the accepted shapes")
        return 0

    if not os.path.isfile(args.file):
        raise SystemExit("no such file: %s" % args.file)

    source = read_source(args.file)
    category = args.category or os.path.splitext(os.path.basename(args.file))[0]
    plan = split_input(source, args.family, args.role, category, args.flatten)
    plan = {fam: {r: {n: p for n, p in cats.items() if p} for r, cats in body.items()}
            for fam, body in plan.items()}
    plan = {fam: {r: cats for r, cats in body.items() if cats}
            for fam, body in plan.items() if body}
    if not plan:
        raise SystemExit("no prompts found in %s" % args.file)

    total = sum(len(p) for body in plan.values() for cats in body.values()
                for p in cats.values())
    kind = "workflow" if is_workflow(source) else "prompt list"
    print("source    : %s (%s), %d entries" % (args.file, kind, total))

    for fam in sorted(plan):
        for role in sorted(plan[fam]):
            print("target    : %s / %s" % (fam, role))
            target, report = merge(target, fam, role, plan[fam][role])
            for name, before, after, added in report:
                print("  %-24s %d -> %d  (+%d)" % (name[:24], before, after, added))

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    if os.path.isfile(args.target):
        backup = "%s.bak-%s" % (args.target, time.strftime("%Y%m%d-%H%M%S"))
        with io.open(args.target, "r", encoding="utf-8") as src, \
                io.open(backup, "w", encoding="utf-8", newline="\n") as dst:
            dst.write(src.read())
        print("backup    : %s" % backup)

    atomic_write(args.target, target)
    print("written   : %s" % args.target)
    print("next      : in the dialog press 重新加载 (or reopen it) - no restart needed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
