# -*- coding: utf-8 -*-
"""
SmartCLIP live end-to-end check.

Needs a running ComfyUI (default http://127.0.0.1:8189, override with MCM_BASE):

    python tests/live_check.py

It proves the three things that cannot be proven by unit tests alone:
  1. the node registers and the /smart_clip/* routes answer;
  2. the ui payload really reaches the client - by queueing a real workflow and
     reading it back out of /history, in the exact flattened shape the frontend
     consumes;
  3. it still arrives when the execution is served from cache (which is why no
     IS_CHANGED = NaN hack is needed).
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("MCM_BASE", "http://127.0.0.1:8189").rstrip("/")
CHECKPOINT = os.environ.get("MCM_CKPT", "majicmixRealistic_v7.safetensors")
EXPECT_FAMILY = os.environ.get("MCM_FAMILY", "sd15")
EXPECT_LABEL = {"sd15": "SD 1.5", "sdxl": "SDXL", "flux": "FLUX"}.get(EXPECT_FAMILY)

FAILS = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILS.append("%s: got %r want %r" % (label, got, want))
    print("  %-4s %-56s %s" % ("OK" if ok else "FAIL", label,
                               got if ok else "got %r want %r" % (got, want)))


def get(path, timeout=60):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post(path, payload, timeout=120):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_for_server(timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            get("/system_stats", timeout=5)
            return True
        except Exception:
            time.sleep(2)
    return False


print("waiting for ComfyUI at %s ..." % BASE)
if not wait_for_server():
    print("server not reachable")
    sys.exit(1)
print("server up\n")

# ----------------------------------------------------------------------
print("=" * 88)
print("1. node registration")
print("=" * 88)

info = get("/object_info/SmartCLIPTextEncode")
node_info = info.get("SmartCLIPTextEncode", {})
check("node is registered", bool(node_info), True)
required = node_info.get("input", {}).get("required", {})
check("required inputs", [k for k in required][:3], ["clip", "text", "prompt_role"])
check("returns CONDITIONING first", node_info.get("output", [None])[0], "CONDITIONING")
check("has a second (label) output", len(node_info.get("output", [])), 2)
check("display name is localised", node_info.get("display_name"),
      "CLIP Text Encode (Smart) / \u667a\u80fd\u63d0\u793a\u8bcd")
check("category", node_info.get("category"), "conditioning/smart")

# ----------------------------------------------------------------------
print()
print("=" * 88)
print("2. /smart_clip/* routes")
print("=" * 88)

meta = get("/smart_clip/info")
check("info reports the version", meta.get("version"), "0.1.0")
check_true = lambda label, value: check(label, bool(value), True)
check_true("info lists preset models", "pony" in meta["presets"]["models"])
check_true("preset file exists", meta["presets"]["exists"])

pony = get("/smart_clip/presets?model=pony&role=positive")
check("pony/positive comes from the file", pony["source"], "file")
check_true("pony has a rating category", "评分标签" in pony["categories"])
check_true("pony lists score_9", any("score_9" in p for v in pony["categories"].values() for p in v))

bogus = get("/smart_clip/presets?model=nope&role=positive")
check("unknown model falls back to builtin", bogus["source"], "builtin")
check_true("...with categories", len(bogus["categories"]) > 0)

text = get("/smart_clip/text?model=pony&role=positive&category=%E8%AF%84%E5%88%86%E6%A0%87%E7%AD%BE")
check_true("text endpoint joins prompts", "score_9" in text["text"])

detect_names = ["majicmixRealistic_v7.safetensors",
                "hassakuXLIllustrious_v13StyleA.safetensors",
                "ponyDiffusionV6XL_v6StartWithThisOne.safetensors"]
detect = get("/smart_clip/detect?kind=checkpoints&names="
             + urllib.parse.quote("|".join(detect_names)))
got = [(item["family"], item["preset"]) for item in detect["items"]]
check("detect: sd15 / illustrious / pony",
      got, [("sd15", "sd15"), ("sdxl", "illustrious"), ("pony", "pony")])

# ----------------------------------------------------------------------
print()
print("=" * 88)
print("2b. 分类管理：新建 / 重命名 / 删除（presets.json 先备份，最后还原）")
print("=" * 88)

# Regression guard for 2026-09-16: these three routes existed in the file but
# were declared after `return True` in register_routes(), so the live server
# answered 405 and the dialog could never delete or rename a category.
import shutil  # noqa: E402

PRESET_FILE = meta["presets"]["preset_file"]
SAFETY = PRESET_FILE + ".livecheck-save"
shutil.copy2(PRESET_FILE, SAFETY)
FAMILY = "sdxl"
TEST_CAT = "__livecheck_cat__"
TEST_CAT2 = "__livecheck_cat2__"


def categories():
    return get("/smart_clip/presets?model=%s&role=positive" % FAMILY)["categories"]


def probe(path, payload):
    """POST and return (http_status, body) - a 405 must be visible, not raised."""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            body = json.loads(body)
        except Exception:
            pass
        return exc.code, body


try:
    status, body = probe("/smart_clip/presets/create_category",
                         {"model": FAMILY, "role": "positive", "category": TEST_CAT})
    check("create_category: HTTP 200", status, 200)
    check("create_category: ok", body.get("ok"), True)
    check("create_category: created", body.get("created"), True)
    check("created (empty) category shows up in the list", TEST_CAT in categories(), True)

    status, body = probe("/smart_clip/presets/rename_category",
                         {"model": FAMILY, "role": "positive", "old": TEST_CAT, "new": TEST_CAT2})
    check("rename_category: HTTP 200", status, 200)
    check("rename_category: ok", body.get("ok"), True)
    cats = categories()
    check("renamed category is present", TEST_CAT2 in cats, True)
    check("old name is gone", TEST_CAT in cats, False)

    status, body = probe("/smart_clip/presets/save_many",
                         {"model": FAMILY, "role": "positive",
                          "entries": [{"category": TEST_CAT2, "text": "__livecheck_entry__"}]})
    check("save_many into the new category: ok", body.get("ok"), True)
    check("entry landed", any("__livecheck_entry__" in v for v in categories().values()), True)

    status, body = probe("/smart_clip/presets/delete",
                         {"model": FAMILY, "role": "positive",
                          "category": TEST_CAT2, "text": "__livecheck_entry__"})
    check("delete entry: HTTP 200", status, 200)
    check("delete entry: ok", body.get("ok"), True)
    # delete_entry drops a category the moment its last entry goes (presets.py)
    check("emptied category is dropped", TEST_CAT2 in categories(), False)

    # ...so re-create it and delete the category as a whole
    status, body = probe("/smart_clip/presets/create_category",
                         {"model": FAMILY, "role": "positive", "category": TEST_CAT2})
    check("re-create for delete_category", body.get("created"), True)
    status, body = probe("/smart_clip/presets/delete_category",
                         {"model": FAMILY, "role": "positive", "category": TEST_CAT2})
    check("delete_category: HTTP 200", status, 200)
    check("delete_category: ok", body.get("ok"), True)
    check("category is gone", TEST_CAT2 in categories(), False)
finally:
    shutil.copy2(SAFETY, PRESET_FILE)
    os.remove(SAFETY)
    print("  (presets.json restored from %s)" % os.path.basename(SAFETY))

# ----------------------------------------------------------------------
print()
print("=" * 88)
print("3. real execution -> ui payload in /history")
print("=" * 88)

workflow = {
    "1": {"class_type": "CheckpointLoaderSimple",
          "inputs": {"ckpt_name": CHECKPOINT}},
    "2": {"class_type": "SmartCLIPTextEncode",
          "inputs": {"clip": ["1", 1], "text": "masterpiece, best quality, 1girl",
                     "prompt_role": "auto"}},
    "3": {"class_type": "SmartCLIPTextEncode",
          "inputs": {"clip": ["1", 1], "text": "worst quality, low quality",
                     "prompt_role": "negative", "prompt_category": "通用负面"}},
    "5": {"class_type": "EmptyLatentImage",
          "inputs": {"width": 64, "height": 64, "batch_size": 1}},
    "4": {"class_type": "KSampler",
          "inputs": {"model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
                     "latent_image": ["5", 0], "seed": 1, "steps": 1, "cfg": 1.0,
                     "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0}},
    "6": {"class_type": "VAEDecode", "inputs": {"samples": ["4", 0], "vae": ["1", 2]}},
    "7": {"class_type": "PreviewImage", "inputs": {"images": ["6", 0]}},
}


def run_once(label):
    queued = post("/prompt", {"prompt": workflow, "client_id": "smartclip-live-check"})
    prompt_id = queued.get("prompt_id")
    check("%s: queued" % label, bool(prompt_id), True)
    deadline = time.time() + 900
    entry = None
    while time.time() < deadline:
        history = get("/history/%s" % prompt_id)
        if prompt_id in history:
            entry = history[prompt_id]
            if entry.get("status", {}).get("completed") or entry.get("outputs"):
                break
        time.sleep(2)
    if entry is None:
        check("%s: finished" % label, "no history entry", "history entry")
        return None
    status = entry.get("status", {})
    check("%s: execution ok" % label, status.get("status_str"), "success")
    outputs = entry.get("outputs", {})
    payload_ui = outputs.get("2", {}).get("smart_clip")
    check("%s: ui payload present on the positive node" % label, isinstance(payload_ui, list), True)
    if payload_ui:
        payload = payload_ui[0]
        check("%s: flattened list holds one dict" % label, isinstance(payload, dict), True)
        check("%s: detected family" % label, payload.get("family"), EXPECT_FAMILY)
        if EXPECT_LABEL:
            check("%s: label" % label, payload.get("label"), EXPECT_LABEL)
        check_true("%s: evidence recorded" % label, payload.get("evidence"))
        check("%s: role on the positive node" % label, payload.get("role"), "auto")
        neg = outputs.get("3", {}).get("smart_clip", [{}])[0]
        check("%s: negative node role" % label, neg.get("role"), "negative")
        check("%s: category annotation survives" % label, neg.get("category"), "通用负面")
        check_true("%s: text preview carried" % label, payload.get("text_preview"))
    check_true("%s: PreviewImage produced an image" % label,
               outputs.get("7", {}).get("images"))
    return entry


first = run_once("cold run")
second = run_once("second run (cache replay)")

if first and second:
    same = (first.get("outputs", {}).get("2") == second.get("outputs", {}).get("2"))
    check("cache replay delivers the same payload", same, True)

print()
print("=" * 88)
if FAILS:
    print("FAILURES: %d" % len(FAILS))
    for line in FAILS:
        print("  -", line)
    sys.exit(1)
print("FAILURES: 0")
