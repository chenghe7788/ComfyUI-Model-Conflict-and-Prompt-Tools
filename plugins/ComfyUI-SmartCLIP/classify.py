# -*- coding: utf-8 -*-
"""
SmartCLIP prompt classification
===============================
Turns one pasted prompt into per-category entries, so a word list can be
organised the way prompts actually read:

    "masterpiece, 1girl, long hair, red dress, forest, soft lighting"
      -> 质量词: masterpiece
         人物:   1girl
         发型:   long hair
         衣服:   red dress
         环境:   forest
         光照:   soft lighting

The rules are plain keyword lists in ``prompt_presets/classify_rules.json`` (a
built-in table is used when that file is missing or broken), so the taxonomy can
be extended without touching code - the file is re-read whenever it changes.

Matching is deliberately two-tier: a keyword that sits on a token boundary wins
over one that merely appears inside the tag (``hair`` on ``long hair`` beats
``ir`` on ``shirt``), and the longest matching keyword breaks the remaining ties.
Anything unmatched lands in the fallback category instead of being guessed at.
"""

import json
import os
import re
import threading

PRESET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt_presets")
RULES_FILE = os.path.join(PRESET_DIR, "classify_rules.json")

FALLBACK = "其它"

# Order matters only for ties at equal match length.
BUILTIN_RULES = {
    "categories": {
        "质量词": [
            "masterpiece", "best quality", "highly detailed", "ultra detailed",
            "sharp focus", "absurdres", "highres", "8k", "very aesthetic",
            "amazing quality", "professional", "杰作", "极品", "高质量", "最高画质",
        ],
        "人物": [
            "1girl", "1boy", "solo", "girl", "boy", "woman", "man", "female",
            "male", "face", "portrait", "character", "body", "skin", "eyes",
            "女孩", "男孩", "人物", "少女", "肖像", "五官", "眼睛", "皮肤", "身体",
        ],
        "表情": [
            "smile", "expression", "blush", "open mouth", "angry", "sad", "happy",
            "tears", "looking at viewer", "表情", "微笑", "生气", "哭泣", "害羞",
        ],
        "发型": [
            "hair", "bangs", "ponytail", "twintails", "braid", "bun", "bob cut",
            "hime cut", "short hair", "long hair", "发型", "头发", "刘海",
            "双马尾", "辫子", "短发", "长发", "卷发", "丸子头",
        ],
        "衣服": [
            "dress", "shirt", "skirt", "uniform", "jacket", "coat", "sweater",
            "hoodie", "pants", "shorts", "bikini", "swimsuit", "lingerie",
            "underwear", "socks", "stockings", "thighhighs", "gloves", "shoes",
            "boots", "hat", "衣服", "服装", "裙", "衬衫", "制服", "外套", "裤",
            "泳装", "内衣", "袜子", "鞋", "帽",
        ],
        "配饰": [
            "necklace", "earring", "bracelet", "ring", "glasses", "choker",
            "ribbon", "hairband", "jewelry", "配饰", "项链", "耳环", "手链",
            "戒指", "眼镜", "项圈", "发饰", "珠宝",
        ],
        "动作姿势": [
            "standing", "sitting", "lying", "kneeling", "walking", "running",
            "pose", "arms up", "hand on hip", "from side", "from behind",
            "looking back", "姿势", "动作", "站立", "坐着", "躺着", "跪着", "奔跑",
        ],
        "环境": [
            "outdoor", "indoor", "forest", "city", "street", "beach", "ocean",
            "mountain", "sky", "night", "sunset", "room", "bedroom", "classroom",
            "background", "scenery", "water", "snow", "rain", "garden",
            "环境", "背景", "森林", "城市", "街道", "海滩", "海", "山", "天空",
            "夜晚", "黄昏", "房间", "教室", "室内", "室外", "雪", "雨", "花园",
        ],
        "光照": [
            "lighting", "light", "sunlight", "backlight", "rim light", "shadow",
            "golden hour", "volumetric", "光照", "光", "阳光", "逆光", "阴影", "打光",
        ],
        "镜头": [
            "close-up", "medium shot", "full body", "cowboy shot", "depth of field",
            "lens", "wide shot", "dutch angle", "from above", "镜头", "构图",
            "特写", "全身", "半身", "景深", "视角",
        ],
    },
    "fallback": FALLBACK,
}

# Tags that are control words in ComfyUI prompts, not content.
_SKIP_TAGS = {"break", "addcomm", "addrow", "embedding", "clip", "lora"}
_WEIGHT_RE = re.compile(r"^\(\s*(.*?)\s*:\s*[-+]?[0-9.]+?\s*\)$")
_BRACKET_RE = re.compile(r"[\[\]{}]")
# A token boundary for ASCII keywords: "hair" must not match inside "chair".
_BOUNDARY = r"(?<![a-z0-9])%s(?![a-z0-9])"

# How a pasted prompt is cut into entries: ASCII *and* full-width punctuation, so
# a Chinese prompt ("杰作，1girl，长发") splits exactly like an English one.
_SPLIT_RE = re.compile(r"[,\n\r，；、]+")
# Sentence ends inside an over-long chunk - preferred break points over whitespace.
_SENTENCE_RE = re.compile(r"(?<=[.!?。！？;；])\s*")
# Soft ceiling for one entry; mirrors ``presets.MAX_ENTRY_TEXT`` (2000), because
# anything longer could not be stored anyway.  It is a *split* threshold, never a
# silent drop: only a chunk with no sentence end and no whitespace at all is
# reported back in ``dropped``, so the dialog can explain itself instead of
# pretending the input box was empty.
MAX_TAG_CHARS = 2000

_LOCK = threading.Lock()
_CACHE = {"key": None, "data": None}


def _split_long(chunk, limit=MAX_TAG_CHARS):
    """Cut an over-long chunk at sentence ends, then at whitespace, never mid-word."""
    chunk = chunk.strip()
    if not chunk:
        return []
    if len(chunk) <= limit:
        # Short chunks are taken verbatim: sentence splitting must never touch
        # them, or a weighted tag such as "(red dress:1.2)" would break at "1.".
        return [chunk]
    parts = []
    for piece in _SENTENCE_RE.split(chunk):
        piece = piece.strip()
        if not piece:
            continue
        if len(piece) <= limit:
            parts.append(piece)
            continue
        buf = ""
        for word in re.split(r"(\s+)", piece):
            if not word.strip():
                buf += word
                continue
            if buf.strip() and len(buf) + len(word) > limit:
                parts.append(buf.strip())
                buf = word
            else:
                buf += word
        if buf.strip():
            parts.append(buf.strip())
    return parts


def split_tags_ex(text):
    """
    ``(tags, dropped)``: every tag of a prompt, in order, de-duplicated.

    Splits on commas and newlines (the two ways ComfyUI prompts are written, in
    ASCII or full-width form), drops empties and control words, and keeps
    weighted tags as the user wrote them - ``(red dress:1.2)`` stays one entry,
    it just classifies by its body.

    A chunk longer than ``MAX_TAG_CHARS`` is split further rather than thrown
    away: the old 200-char guard dropped pasted prose in silence, and the dialog
    then blamed an empty input box.  ``dropped`` only ever holds text that has
    no break point at all.
    """
    out = []
    seen = set()
    dropped = []
    for chunk in _SPLIT_RE.split(str(text or "")):
        for tag in _split_long(chunk):
            if tag.strip("()[]{} ").lower() in _SKIP_TAGS:
                continue
            if len(tag) > MAX_TAG_CHARS:
                dropped.append(tag[:120])
                continue
            if tag in seen:
                continue
            seen.add(tag)
            out.append(tag)
    return out, dropped


def split_tags(text):
    """Just the tags of :func:`split_tags_ex`."""
    return split_tags_ex(text)[0]


def _match_text(tag):
    """The part of a tag keywords are matched against: no weights/brackets."""
    text = str(tag or "").strip()
    for _ in range(3):
        match = _WEIGHT_RE.match(text)
        if not match:
            break
        text = match.group(1).strip()
    text = _BRACKET_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def load_rules():
    """The rule table: the JSON file when readable, else the built-in one."""
    try:
        stamp = (int(os.path.getmtime(RULES_FILE)), os.path.getsize(RULES_FILE))
    except OSError:
        return dict(BUILTIN_RULES), "builtin"
    with _LOCK:
        if _CACHE["key"] == stamp:
            return _CACHE["data"]

    data = None
    try:
        with open(RULES_FILE, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        categories = (raw or {}).get("categories")
        if isinstance(categories, dict):
            cleaned = {}
            for name, words in categories.items():
                if str(name).startswith("_"):
                    continue
                values = words if isinstance(words, list) else [words]
                hits = [str(w).strip().lower() for w in values
                        if isinstance(w, (str, int, float)) and str(w).strip()]
                if hits:
                    cleaned[str(name)] = hits
            if cleaned:
                fallback = str((raw or {}).get("fallback") or FALLBACK)
                data = ({"categories": cleaned, "fallback": fallback}, "file")
    except Exception:
        data = None

    if data is None:
        data = (dict(BUILTIN_RULES), "builtin")
    with _LOCK:
        _CACHE["key"] = stamp
        _CACHE["data"] = data
    return data


def rules():
    return load_rules()[0]


def classify_tag(tag, table=None):
    """The category a single tag belongs to (never empty; falls back)."""
    table = table if table is not None else rules()
    categories = table.get("categories") or {}
    text = _match_text(tag)
    if not text:
        return table.get("fallback") or FALLBACK

    best = None          # (tier, length, order, category)
    order = 0
    for name, words in categories.items():
        for word in words:
            keyword = str(word).strip().lower()
            if not keyword or keyword not in text:
                continue
            if re.search(_BOUNDARY % re.escape(keyword), text):
                tier = 2                       # on a token boundary: strongest
            else:
                tier = 1                       # inside a longer token: weaker
            score = (tier, len(keyword), -order)
            if best is None or score > best[0]:
                best = (score, name)
        order += 1
    return best[1] if best else (table.get("fallback") or FALLBACK)


def plan(text, model=None):
    """
    ``{"tags": [{"text","category"}], "counts": {category: n}, ...}``.

    Pure function of the text and the rule table: no files are written, which is
    what lets the dialog show the classification before saving it.
    """
    table, source = load_rules()
    split, dropped = split_tags_ex(text)
    tags = []
    counts = {}
    for tag in split:
        category = classify_tag(tag, table)
        tags.append({"text": tag, "category": category})
        counts[category] = counts.get(category, 0) + 1
    return {
        "tags": tags,
        "counts": counts,
        "total": len(tags),
        "dropped": dropped,
        "source": source,
        "rules_file": RULES_FILE,
        "categories": list((table.get("categories") or {}).keys()),
        "fallback": table.get("fallback") or FALLBACK,
        "model": model,
    }


def info():
    table, source = load_rules()
    return {
        "rules_file": RULES_FILE,
        "exists": os.path.isfile(RULES_FILE),
        "source": source,
        "categories": list((table.get("categories") or {}).keys()),
        "fallback": table.get("fallback") or FALLBACK,
        "keywords": sum(len(v) for v in (table.get("categories") or {}).values()),
    }


def clear_cache():
    with _LOCK:
        _CACHE["key"] = None
        _CACHE["data"] = None
    return True
