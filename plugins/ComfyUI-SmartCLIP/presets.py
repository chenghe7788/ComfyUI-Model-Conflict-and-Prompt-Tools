# -*- coding: utf-8 -*-
"""
SmartCLIP presets
=================
The word lists live in ``prompt_presets/presets.json`` so users can edit them
without touching code.  This module owns loading, normalising and caching them,
and it always hands the frontend the *same* shape:

    {
      "model": "pony",
      "role": "positive",
      "categories": {"评分标签": ["score_9", ...], ...},
      "source": "file" | "builtin",
      "models": ["sd15", "sdxl", ...],
      "roles": ["positive", "negative"],
      "shared": ["蝴蝶忍", ...],
      "annotations": {"embedding:EasyNegative": {"state": "ok", ...}},
      "embedding_stats": {"total": 4, "ok": 3, "incompatible": 1, ...}
    }

``categories`` is the merged view the dialog renders: the built-ins for the
family, then that family's section of the file, then the *shared* section - the
categories the user made themselves, which every dialog shows regardless of the
checkpoint the workflow uses (see ``SHARED_MODEL``).  ``shared`` lists just those
names so the dialog can mark them.

``annotations`` only ever carries entries that are textual inversions
(``embedding:...``): whether the file is installed and whether its architecture
matches the CLIP that will encode the prompt.  The dialog renders them as
badges; ordinary words are simply absent from the map.

Shape drift is what breaks UIs, so normalisation is not optional here: a value
may be a list, a single string, or a nested {"prompts": [...]} object, and any
missing model/role falls back to the built-in table instead of returning a
different structure (the draft this replaces returned a plain list in one branch
and a {category: [...]} dict in another, which cannot both be rendered).
"""

import json
import logging
import os
import threading
import time

try:                       # normal case: loaded as a package by ComfyUI
    from . import embedding_compat
except ImportError:        # standalone import (tests / tooling)
    import embedding_compat

log = logging.getLogger("SmartCLIP.presets")

PRESET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt_presets")
PRESET_FILE = os.path.join(PRESET_DIR, "presets.json")

ROLES = ("positive", "negative")
DEFAULT_MODEL = "generic"

# Where the categories the *user* made in the dialog live.
#
# A family section (generic/sd15/sdxl/...) holds the presets that are tuned for
# that architecture - 评分标签 belongs to pony, 描述模板 to flux.  Everything the
# user creates themselves is a different thing: it is their own word list and
# must show up in **every** dialog, whatever checkpoint the workflow happens to
# use (2026-09-19: "让只要是新建的文本分类在所有的提示词弹窗都能看到").
# Keeping such categories under whichever family the node detected is exactly
# why a category saved in one workflow was invisible in the next one.
#
# The leading underscore keeps this section out of the model list and matches the
# documented "以 _ 开头的 key 会被忽略" convention, so a build that predates this
# change simply ignores the section instead of choking on it.
SHARED_MODEL = "_shared"

# Small built-in safety net: used when the JSON file is missing, unreadable or
# does not contain the requested model.  Keeping it short is deliberate - the
# real lists belong in the editable JSON file.
BUILTIN = {
    "generic": {
        "positive": {
            "质量词": ["masterpiece", "best quality", "highly detailed", "sharp focus"],
            "光照": ["soft lighting", "cinematic lighting", "rim light"],
            "镜头": ["close-up", "medium shot", "depth of field", "85mm lens"],
        },
        "negative": {
            "通用负面": ["worst quality", "low quality", "blurry", "jpeg artifacts",
                     "watermark", "signature", "text"],
            "解剖": ["bad anatomy", "bad hands", "extra fingers", "deformed"],
        },
    },
}

# Built-in additions for the well known families, merged under the file content
# so an empty or half-filled presets.json still gives something useful.
BUILTIN_FAMILIES = {
    "sd15": {
        "positive": {
            "质量词": ["masterpiece", "best quality", "ultra detailed",
                    "high resolution", "8k wallpaper"],
            "写实摄影": ["photorealistic", "raw photo", "film grain",
                     "professional photography", "natural skin texture"],
            "负面兜底": [],
        },
        "negative": {
            "通用负面": ["worst quality", "low quality", "normal quality", "lowres",
                     "blurry", "jpeg artifacts", "watermark", "signature", "text",
                     "error", "cropped", "out of frame"],
            "解剖手部": ["bad anatomy", "bad hands", "missing fingers",
                     "extra digit", "fewer digits", "mutated hands",
                     "poorly drawn hands", "extra limbs", "long neck"],
            "画质崩坏": ["cartoon", "3d", "painting", "sketch", "anime"],
        },
    },
    "sdxl": {
        "positive": {
            "质量词": ["masterpiece", "best quality", "highly detailed",
                    "sharp focus", "professional"],
            "写实摄影": ["photorealistic", "cinematic lighting", "shot on DSLR",
                     "natural skin texture", "detailed eyes"],
            "细节增强": ["intricate details", "fine details", "high contrast"],
        },
        "negative": {
            "通用负面": ["worst quality", "low quality", "blurry", "jpeg artifacts",
                     "watermark", "signature", "text", "deformed"],
            "解剖手部": ["bad hands", "extra fingers", "missing fingers",
                     "mutated hands", "extra limbs"],
        },
    },
    "pony": {
        "positive": {
            "评分标签": ["score_9", "score_8_up", "score_7_up", "score_6_up"],
            "来源标签": ["source_anime", "source_cartoon", "source_furry",
                     "source_pony"],
            "质量词": ["masterpiece", "best quality", "absurdres",
                    "highres", "very aesthetic"],
        },
        "negative": {
            "评分负面": ["score_4", "score_5", "score_6", "score_3", "score_2",
                     "score_1", "worst quality", "low quality", "lowres"],
            "解剖": ["bad anatomy", "bad hands", "extra fingers", "deformed"],
        },
    },
    "illustrious": {
        "positive": {
            "质量词": ["masterpiece", "best quality", "amazing quality",
                    "very aesthetic", "absurdres"],
            "年代": ["year 2024", "year 2025", "newest"],
            "细节": ["detailed eyes", "detailed background", "intricate details"],
        },
        "negative": {
            "通用负面": ["worst quality", "low quality", "bad quality", "lowres",
                     "blurry", "jpeg artifacts", "watermark", "signature",
                     "artist name", "username", "text"],
            "解剖": ["bad anatomy", "bad hands", "extra fingers", "deformed"],
        },
    },
    "sd3": {
        "positive": {
            "质量词": ["masterpiece", "best quality", "highly detailed"],
            "描述模板": ["A photorealistic photograph of", "cinematic composition",
                     "soft natural light"],
        },
        "negative": {
            "通用负面": ["worst quality", "low quality", "blurry", "watermark"],
        },
    },
    "flux": {
        "positive": {
            "描述模板": ["A photorealistic photograph of", "shot on a full-frame camera",
                     "shallow depth of field", "natural volumetric lighting",
                     "ultra detailed skin texture", "cinematic color grading"],
            "质量词": ["highly detailed", "professional photography", "sharp focus"],
        },
        "negative": {
            "提示": ["FLUX 通常不需要负面提示词；如需抑制内容，用自然语言描述"],
        },
    },
}

_LOCK = threading.Lock()
_CACHE = {"key": None, "data": None}


def _as_prompt_list(value):
    """Coerce one category value into a clean list of non-empty strings."""
    out = []
    if value is None:
        return out
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        # {"prompts": [...]} / {"items": [...]} / {"words": "a, b"}
        for field in ("prompts", "items", "words", "list"):
            if field in value:
                return _as_prompt_list(value[field])
        return out
    if isinstance(value, (list, tuple)):
        for item in value:
            out.extend(_as_prompt_list(item))
    elif isinstance(value, (int, float)):
        out.append(str(value))
    return [p for p in (str(x).strip() for x in out) if p]


def _declared_empty(value):
    """True when a category was *explicitly* declared with no prompts.

    A plain ``[]`` (or ``{"prompts": []}``) is a category the user created in
    the dialog and has not filled yet; it must survive the round trip, or the
    sidebar row disappears and there is nothing left to rename or delete.
    ``null`` / a stray number / a ``{}`` were never a category at all.
    """
    if isinstance(value, (list, tuple)):
        return len(value) == 0
    if isinstance(value, dict):
        for field in ("prompts", "items", "words", "list"):
            if field in value:
                return _declared_empty(value[field])
    return False


def _normalise_role(raw):
    """{'cat': [...]} -> {'cat': [...]} with every value a clean list."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for name, value in raw.items():
        prompts = _as_prompt_list(value)
        if prompts or _declared_empty(value):
            out[str(name)] = prompts
    return out


def _merge(base, extra):
    """extra wins, but only for the categories it actually defines."""
    merged = {k: list(v) for k, v in (base or {}).items()}
    for name, prompts in (extra or {}).items():
        merged[name] = list(prompts)
    return merged


def _union(base, extra):
    """Like :func:`_merge`, but a name both layers define keeps *both* lists.

    Used for the shared section.  If the user's global category happens to be
    called like a family preset (拆分入库 writes 光照 / 镜头 / 质量词, and those
    are also built-in names), replacing one with the other would make half of
    the entries vanish from the dialog; a deduped union shows everything.
    """
    merged = {k: list(v) for k, v in (base or {}).items()}
    for name, prompts in (extra or {}).items():
        if name in merged:
            for item in prompts:
                if item not in merged[name]:
                    merged[name].append(item)
        else:
            merged[name] = list(prompts)
    return merged


def _shared_role(data, role):
    """The user's global categories for one role ({name: [prompts]})."""
    if not isinstance(data, dict):
        return {}
    node = data.get(SHARED_MODEL)
    if not isinstance(node, dict):
        return {}
    return _normalise_role(node.get(role))


def _home_of(model, role, category, data):
    """``SHARED_MODEL`` for the user's own categories, the family for presets.

    A category the family ships (质量词 / 评分标签 / 通用负面 ...) stays with that
    family: it is tuned for that architecture.  Everything else belongs to the
    user, so it goes to the shared section and therefore shows up in every
    dialog.  The ``category in shared`` check comes first for a name that is a
    family preset somewhere and a user category somewhere else.
    """
    if category in (_builtin_for(model).get(role) or {}):
        node = data.get(SHARED_MODEL) if isinstance(data, dict) else None
        cats = node.get(role) if isinstance(node, dict) else None
        if not (isinstance(cats, dict) and category in cats):
            return model
    return SHARED_MODEL


def _bucket(data, home, role, create=False):
    """The ``{category: [prompts]}`` dict for one (home, role), or None."""
    node = data.get(home)
    if not isinstance(node, dict):
        if not create:
            return None
        node = {}
        data[home] = node
    cats = node.get(role)
    if not isinstance(cats, dict):
        if not create:
            return None
        cats = {}
        node[role] = cats
    return cats


def _homes_for(data, model, role, category):
    """Every bucket this category may live in: shared, its family, leftovers."""
    homes = [SHARED_MODEL, model]
    if isinstance(data, dict):
        for name, body in data.items():
            if str(name).startswith("_") or name in homes:
                continue
            if not isinstance(body, dict):
                continue
            cats = body.get(role)
            if not isinstance(cats, dict) or category not in cats:
                continue
            # a family's own presets are not the user's global category
            if category in (_builtin_for(name).get(role) or {}):
                continue
            homes.append(name)
    return homes


def _builtin_for(model):
    base = BUILTIN.get(model) or {}
    added = BUILTIN_FAMILIES.get(model) or {}
    out = {}
    for role in ROLES:
        merged = _merge(base.get(role), added.get(role))
        if merged:
            out[role] = merged
    if not out and model != DEFAULT_MODEL:
        return _builtin_for(DEFAULT_MODEL)
    return out


def _read_file():
    """Raw JSON with an mtime-keyed cache, so edits apply without a restart."""
    try:
        stamp = (int(os.path.getmtime(PRESET_FILE)), os.path.getsize(PRESET_FILE))
    except OSError:
        return None
    with _LOCK:
        if _CACHE["key"] == stamp:
            return _CACHE["data"]
    try:
        with open(PRESET_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            data = None
    except Exception:
        data = None
    with _LOCK:
        _CACHE["key"] = stamp
        _CACHE["data"] = data
    return data


def _models_in_file(data):
    if not isinstance(data, dict):
        return []
    found = []
    for key, value in data.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and any(r in value for r in ROLES):
            found.append(key)
    return found


def available_models():
    """Models offered by the file, plus the built-in ones, in a stable order."""
    data = _read_file() or {}
    models = []
    for name in _models_in_file(data) + list(BUILTIN_FAMILIES.keys()) + [DEFAULT_MODEL]:
        if name and name not in models:
            models.append(name)
    return sorted(models)


def load(model=DEFAULT_MODEL, role="positive", verdict_model=None):
    """
    Word lists for one model + role, always in the documented shape.

    Three layers, in this order: the built-in safety net for the family, the
    family's own section of the file, and finally the *shared* section - the
    categories the user made, which every dialog must show.

    ``verdict_model`` only overrides the family the embedded textual-inversion
    verdicts are judged against, never which word list is returned: the dialog
    may be showing the generic list because the frontend could not identify the
    base while the backend still knows which checkpoint ran (see
    workflow_model.resolve_preset).  ``None`` means "judge against ``model``",
    which is what every pre-2026-09-23 caller did.
    """
    model = str(model or DEFAULT_MODEL).strip().lower() or DEFAULT_MODEL
    role = str(role or "positive").strip().lower()
    if role not in ROLES:
        role = "positive"
    verdict = str(verdict_model or model).strip().lower() or model

    _promote_user_categories()

    data = _read_file() or {}
    source = "builtin"
    file_role = {}
    entry = data.get(model)
    if isinstance(entry, dict):
        file_role = _normalise_role(entry.get(role))
    shared_role = _shared_role(data, role)

    if file_role or shared_role:
        source = "file"
        # family content wins over the built-ins, the user's own categories are
        # added on top (and never hide a same-named preset: see _union)
        categories = _union(_merge(_builtin_for(model).get(role, {}), file_role),
                            shared_role)
    else:
        categories = _builtin_for(model).get(role, {})

    # Textual inversions need two facts the word list cannot carry: is the file
    # installed, and does its text encoder match this model family.  This must
    # never be able to break the word list itself, hence the guard.
    try:
        annotations, embedding_stats = embedding_compat.annotate_categories(categories, verdict)
    except Exception:
        annotations, embedding_stats = {}, {}

    return {
        "model": model,
        "role": role,
        "categories": categories,
        "source": source,
        "models": available_models(),
        "roles": list(ROLES),
        "preset_file": PRESET_FILE,
        "exists": os.path.isfile(PRESET_FILE),
        "annotations": annotations,
        "embedding_stats": embedding_stats,
        # The family the embedding verdicts were actually judged against.  It
        # differs from "model" only when the caller supplied a fallback.
        "embedding_family": verdict,
        # Which of these categories are the user's global ones (every dialog
        # shows them); the dialog marks them so the behaviour is visible.
        "shared": sorted(shared_role),
        # Advertises that POST /smart_clip/presets/save exists in this build, so
        # the dialog can disable its "入库" button instead of letting the user
        # click into a 405 after a JS-only update.
        "writable": True,
    }


def text_for(model, role, category):
    """Joined text of one category - handy for copy/paste and API users."""
    data = load(model, role)
    prompts = data["categories"].get(category)
    if prompts is None:
        return {"model": data["model"], "role": data["role"], "category": category,
                "found": False, "text": "", "prompts": []}
    return {"model": data["model"], "role": data["role"], "category": category,
            "found": True, "prompts": prompts, "text": ", ".join(prompts)}


def clear_cache():
    with _LOCK:
        _CACHE["key"] = None
        _CACHE["data"] = None
    embedding_compat.clear_cache()
    return True


# ----------------------------------------------------------------------
# Writing back: "put this prompt in the library" from the dialog
# ----------------------------------------------------------------------

MAX_ENTRY_TEXT = 2000
MAX_CATEGORY_NAME = 60
BACKUP_SUFFIX = ".bak-last"
_WRITE_LOCK = threading.Lock()


def _write_json(data):
    """Atomic write: temp file in the same folder, validated, then replaced."""
    folder = os.path.dirname(PRESET_FILE) or "."
    tmp = os.path.join(folder, ".presets.json.tmp-%d" % int(time.time() * 1000))
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    try:
        with open(tmp, "r", encoding="utf-8") as handle:
            json.load(handle)
        os.replace(tmp, PRESET_FILE)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _backup_file(suffix=BACKUP_SUFFIX):
    """One rolling backup next to the word list (overwritten on every save)."""
    if not os.path.isfile(PRESET_FILE):
        return None
    backup = PRESET_FILE + suffix
    try:
        with open(PRESET_FILE, "r", encoding="utf-8") as src:
            payload = src.read()
        with open(backup, "w", encoding="utf-8", newline="\n") as dst:
            dst.write(payload)
        return backup
    except OSError:
        return None


# ----------------------------------------------------------------------
# 全局分类：把用户自建的分类收拢到 _shared 段
# ----------------------------------------------------------------------

MIGRATION_SUFFIX = ".bak-before-shared"


def _is_user_category(model, role, category):
    """True when the family does not ship this category itself."""
    return category not in (_builtin_for(model).get(role) or {})


def _user_categories_in_families(data):
    """[(model, role, category)] still sitting in a family section by mistake."""
    pending = []
    if not isinstance(data, dict):
        return pending
    for model, body in data.items():
        if str(model).startswith("_") or not isinstance(body, dict):
            continue
        for role in ROLES:
            cats = body.get(role)
            if not isinstance(cats, dict):
                continue
            for category in cats:
                if _is_user_category(model, role, category):
                    pending.append((model, role, category))
    return pending


def _move_user_categories(data):
    """Move the categories from :func:`_user_categories_in_families` into _shared."""
    moved = []
    for model, role, category in _user_categories_in_families(data):
        src = _bucket(data, model, role)
        if not isinstance(src, dict) or category not in src:
            continue
        prompts = _as_prompt_list(src.pop(category))

        shared = _bucket(data, SHARED_MODEL, role, create=True)
        existing = _as_prompt_list(shared.get(category))
        for item in prompts:
            if item not in existing:
                existing.append(item)
        shared[category] = existing          # 空分类也要保留，否则左侧那一行会消失
        if not src:
            body = data.get(model)
            if isinstance(body, dict):
                body.pop(role, None)
                if not body:
                    data.pop(model, None)
        moved.append("%s/%s/%s" % (model, role, category))
    return moved


def _promote_user_categories():
    """One-time normalisation: user categories live in _shared, not per family.

    Older builds filed everything the dialog created under whichever model
    family the node detected, which is why a category saved in one workflow was
    missing in the next one.  This moves those categories (never the presets a
    family ships) into the shared section.  Idempotent and cheap: when there is
    nothing to move it does not touch the file at all.
    """
    if not _user_categories_in_families(_read_file()):
        return []
    with _WRITE_LOCK:
        raw = _read_file()
        if not _user_categories_in_families(raw):
            return []
        data = json.loads(json.dumps(raw))
        moved = _move_user_categories(data)
        if not moved:
            return []
        backup = _backup_file(MIGRATION_SUFFIX)
        _write_json(data)
        clear_cache()
        log.info("[SmartCLIP] 用户自建分类已收拢到 %s（%d 个，备份：%s）：%s",
                 SHARED_MODEL, len(moved), backup, ", ".join(moved[:12]))
        return moved


def add_entry(model, role, category, text):
    """
    Append one prompt to the word-list file, so the dialog can save what the
    user just typed or pasted.

    Returns a report dict (``duplicate`` tells the caller nothing was written).
    Raises ``ValueError`` with a user-facing message for anything that must not
    be stored.  The file is backed up first and written atomically; a file that
    is currently unreadable is refused rather than overwritten, because that
    would silently destroy a word list a human is editing.
    """
    clean = _clean_entry(model, role, category, text)
    report = _save([clean])
    m, r, c, t = clean
    return {
        "ok": True,
        "duplicate": report["duplicates"] > 0,
        "model": m,
        "role": r,
        "category": c,
        "text": t,
        "count": report["sizes"].get(c, 0),
        "backup": report.get("backup"),
        "stored_in": report["homes"].get(c),
        "global": report["homes"].get(c) == SHARED_MODEL,
        "preset_file": PRESET_FILE,
    }


def add_entries(model, role, entries, skip_invalid=True):
    """
    Append many prompts - one read, one backup, one atomic write.

    ``entries`` is a list of ``{"category","text"}`` (or ``(category, text)``
    pairs): the "拆分入库" flow classifies a pasted prompt into several
    categories and saves them together, so a half-written library is impossible.
    Entries that fail validation are reported in ``skipped`` instead of aborting
    the whole batch.
    """
    cleaned = []
    skipped = []
    for item in entries or []:
        if isinstance(item, dict):
            category, text = item.get("category"), item.get("text")
        else:
            pair = list(item) if isinstance(item, (list, tuple)) else [None, None]
            category, text = (pair + [None, None])[:2]
        try:
            cleaned.append(_clean_entry(model, role, category, text))
        except ValueError as exc:
            if not skip_invalid:
                raise
            skipped.append({"category": str(category or ""), "text": str(text or "")[:80],
                            "error": str(exc)})

    if not cleaned:
        reason = skipped[0]["error"] if skipped else "没有可入库的词条"
        raise ValueError(reason)

    report = _save(cleaned)
    report["skipped"] = skipped
    report["ok"] = True
    return report


def _clean_entry(model, role, category, text):
    """Validate one entry and normalise its four fields, or raise ValueError."""
    model = str(model or "").strip().lower()
    role = str(role or "positive").strip().lower()
    category = str(category or "").strip()
    text = str(text or "").strip()

    if not text:
        raise ValueError("提示词不能为空")
    if len(text) > MAX_ENTRY_TEXT:
        raise ValueError("提示词太长（最多 %d 字）" % MAX_ENTRY_TEXT)
    if not category:
        raise ValueError("分类名不能为空")
    if len(category) > MAX_CATEGORY_NAME:
        raise ValueError("分类名太长（最多 %d 字）" % MAX_CATEGORY_NAME)
    if not model or model.startswith("_"):
        raise ValueError("模型族名不合法")
    if role not in ROLES:
        role = "positive"
    return (model, role, category, text)


def _save(entries):
    """One read-modify-write for already validated ``(model, role, cat, text)``."""
    _promote_user_categories()
    with _WRITE_LOCK:
        raw = _read_file()
        if raw is None:
            if os.path.isfile(PRESET_FILE):
                raise ValueError("词库文件不是合法 JSON，已拒绝写入（原文件保留，请先修好）")
            raw = {}
        data = json.loads(json.dumps(raw))          # deep copy: never mutate the cache

        added = 0
        duplicates = 0
        counts = {}
        sizes = {}
        homes = {}
        for model, role, category, text in entries:
            # 自建分类写进 _shared（所有弹窗都能看到），模型族自带的预设留在族里
            home = _home_of(model, role, category, data)
            homes[category] = home
            cats = _bucket(data, home, role, create=True)

            prompts = _as_prompt_list(cats.get(category))
            if text in prompts:
                duplicates += 1
                sizes[category] = len(prompts)
                continue
            prompts.append(text)
            cats[category] = prompts
            added += 1
            counts[category] = counts.get(category, 0) + 1
            sizes[category] = len(prompts)

        if not added:
            return {"added": 0, "duplicates": duplicates, "categories": counts,
                    "sizes": sizes, "homes": homes, "changed": False,
                    "preset_file": PRESET_FILE}

        backup = _backup_file()
        _write_json(data)
        clear_cache()
        return {"added": added, "duplicates": duplicates, "categories": counts,
                "sizes": sizes, "homes": homes, "changed": True, "backup": backup,
                "preset_file": PRESET_FILE}


def info():
    return {
        "preset_file": PRESET_FILE,
        "exists": os.path.isfile(PRESET_FILE),
        "editable": os.access(os.path.dirname(PRESET_FILE) or ".", os.W_OK),
        "backup_file": PRESET_FILE + BACKUP_SUFFIX,
        "max_entry_chars": MAX_ENTRY_TEXT,
        "models": available_models(),
        "roles": list(ROLES),
        "cache_ttl": "mtime-keyed (edits apply immediately)",
        "shared_key": SHARED_MODEL,
        "shared": shared_summary(),
        "embeddings": embedding_compat.info(),
        "checked_at": time.time(),
    }


def shared_summary():
    """How many global (user-made) categories exist per role - for /info."""
    data = _read_file() or {}
    return {role: sorted(_shared_role(data, role)) for role in ROLES}


def _name_is_free(data, home, role, category):
    """Collision check for rename: the target name must be free in this bucket."""
    cats = _bucket(data, home, role)
    return not (isinstance(cats, dict) and category in cats)


def delete_entry(model, role, category, text):
    """删除指定分类下的某个词条。

    自建分类可能同时出现在共享段和模型族段（迁移前的旧文件），所以每个
    含该词条的桶都要清掉，否则并集视图里它又回来了。
    """
    model = str(model or "").strip().lower()
    role = str(role or "positive").strip().lower()
    if role not in ROLES:
        role = "positive"
    category = str(category or "").strip()
    text = str(text or "").strip()
    if not category or not text:
        raise ValueError("分类和词条都不能为空")

    _promote_user_categories()
    with _WRITE_LOCK:
        raw = _read_file()
        if raw is None:
            raise ValueError("词库文件不是合法JSON，拒绝写入")
        data = json.loads(json.dumps(raw))

        removed_from = []
        for home in _homes_for(data, model, role, category):
            cats = _bucket(data, home, role)
            if not isinstance(cats, dict):
                continue
            prompts = _as_prompt_list(cats.get(category))
            if text not in prompts:
                continue
            prompts.remove(text)
            if prompts:
                cats[category] = prompts
            else:
                del cats[category]  # 分类空了就删掉
            removed_from.append(home)

        if not removed_from:
            return {"ok": False, "error": "词条不存在"}

        backup = _backup_file()
        _write_json(data)
        clear_cache()
        return {"ok": True, "deleted": text, "category": category,
                "removed_from": removed_from, "backup": backup}


def rename_category(model, role, old_name, new_name):
    """重命名分类（自建分类在所有模型族里都是同一个，所以处处跟着改）"""
    model = str(model or "").strip().lower()
    role = str(role or "positive").strip().lower()
    if role not in ROLES:
        role = "positive"
    old_name = str(old_name or "").strip()
    new_name = str(new_name or "").strip()
    if not old_name or not new_name:
        raise ValueError("分类名不能为空")
    if len(new_name) > MAX_CATEGORY_NAME:
        raise ValueError("新分类名太长")

    _promote_user_categories()
    with _WRITE_LOCK:
        raw = _read_file()
        if raw is None:
            raise ValueError("词库文件不是合法JSON，拒绝写入")
        data = json.loads(json.dumps(raw))

        targets = []
        for home in _homes_for(data, model, role, old_name):
            cats = _bucket(data, home, role)
            if isinstance(cats, dict) and old_name in cats:
                targets.append(home)
        if not targets:
            return {"ok": False, "error": "原分类不存在"}
        if any(not _name_is_free(data, home, role, new_name) for home in targets):
            return {"ok": False, "error": "新分类名已存在"}

        for home in targets:
            cats = _bucket(data, home, role)
            cats[new_name] = cats.pop(old_name)
        backup = _backup_file()
        _write_json(data)
        clear_cache()
        return {"ok": True, "old": old_name, "new": new_name,
                "renamed_in": targets, "backup": backup}


def delete_category(model, role, category):
    """删除整个分类：共享段和模型族里的副本一起清掉，否则并集视图里还看得到。"""
    model = str(model or "").strip().lower()
    role = str(role or "positive").strip().lower()
    if role not in ROLES:
        role = "positive"
    category = str(category or "").strip()
    if not category:
        raise ValueError("分类名不能为空")

    _promote_user_categories()
    with _WRITE_LOCK:
        raw = _read_file()
        if raw is None:
            raise ValueError("词库文件不是合法JSON，拒绝写入")
        data = json.loads(json.dumps(raw))

        removed_from = []
        for home in _homes_for(data, model, role, category):
            cats = _bucket(data, home, role)
            if isinstance(cats, dict) and category in cats:
                del cats[category]
                removed_from.append(home)
        if not removed_from:
            return {"ok": False, "error": "分类不存在"}

        backup = _backup_file()
        _write_json(data)
        clear_cache()
        return {"ok": True, "deleted": category, "removed_from": removed_from,
                "backup": backup}


def create_category(model, role, category):
    """新建一个（可以是空的）分类。

    空分类必须真的落到 presets.json 里，弹窗左侧才会出现这一行；
    只有出现了这一行，右键重命名 / 删除才有对象可点。

    自建的分类一律进共享段（_shared）：这样在任何工作流、任何底模下打开
    提示词弹窗都能看到它，正向的只进正向、反向的只进反向。
    """
    model = str(model or "").strip().lower()
    role = str(role or "positive").strip().lower()
    if role not in ROLES:
        role = "positive"
    category = str(category or "").strip()
    if not category:
        raise ValueError("分类名不能为空")
    if len(category) > MAX_CATEGORY_NAME:
        raise ValueError("分类名太长（最多 %d 字）" % MAX_CATEGORY_NAME)

    _promote_user_categories()
    with _WRITE_LOCK:
        raw = _read_file()
        if raw is None and os.path.isfile(PRESET_FILE):
            raise ValueError("词库文件不是合法JSON，拒绝写入")
        data = json.loads(json.dumps(raw or {}))

        home = _home_of(model, role, category, data)
        cats = _bucket(data, home, role, create=True)

        if category in cats:
            return {"ok": True, "created": False, "category": category,
                    "count": len(_as_prompt_list(cats[category])),
                    "stored_in": home, "global": home == SHARED_MODEL}

        cats[category] = []
        backup = _backup_file()
        _write_json(data)
        clear_cache()
        return {"ok": True, "created": True, "category": category,
                "stored_in": home, "global": home == SHARED_MODEL, "backup": backup}
