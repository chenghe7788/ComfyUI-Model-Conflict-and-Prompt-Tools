# -*- coding: utf-8 -*-
"""
SmartCLIP self-test (no ComfyUI needed).

    python tests\\test_smartclip.py

Covers: runtime CLIP detection (class name / tokenizer fallback), file-based
detection against the real checkpoints on this machine, preset normalisation
drift, and the node's ui+result contract - including a literal replay of the
flattening line from execution.py that decides whether the frontend can read the
payload at all.
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
# Normal layout: tests/ sits next to the plugin files (deployed).  In the source
# copy the plugin files live in tests/../src.  MCM_PLUGIN overrides both.
PLUGIN = os.environ.get("MCM_PLUGIN")
if not PLUGIN:
    for candidate in (os.path.join(os.path.dirname(HERE), "src"), os.path.dirname(HERE)):
        if os.path.isfile(os.path.join(candidate, "nodes.py")):
            PLUGIN = candidate
            break
if not PLUGIN:
    PLUGIN = r"C:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_SmartCLIP"
sys.path.insert(0, PLUGIN)

import model_detector as md          # noqa: E402
import embedding_compat as ec        # noqa: E402
import presets as ps                 # noqa: E402
import nodes as smart_nodes          # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILS.append("%s: got %r want %r" % (label, got, want))
    print("  %-4s %-58s %s" % ("OK" if ok else "FAIL", label, got if ok else "got %r want %r" % (got, want)))


def check_true(label, value):
    check(label, bool(value), True)


# ======================================================================
# 1. runtime detection
# ======================================================================

print("=" * 92)
print("1. runtime CLIP detection")
print("=" * 92)


class SD1ClipModel:  # noqa: N801 - the real class names are what matters
    pass


class SDXLClipModel:  # noqa: N801
    pass


class SD3ClipModel:  # noqa: N801
    pass


class FluxClipModel:  # noqa: N801
    pass


class SD2ClipModel:  # noqa: N801
    pass


class SomeThirdPartyWrapper:  # noqa: N801
    pass


class TokenizerL:
    clip_name = "l"


class TokenizerH:
    clip_name = "h"


class TokenizerXL:
    clip_name = "l"
    clip_l = object()

    def __init__(self):
        self.clip_g = object()


class TokenizerT5:
    clip_l = object()

    def __init__(self):
        self.t5xxl = object()


class FakeClip:
    def __init__(self, model=None, tokenizer=None, patcher_model=None):
        if model is not None:
            self.cond_stage_model = model
        self.tokenizer = tokenizer
        if patcher_model is not None:
            class _P:
                pass
            p = _P()
            p.model = patcher_model
            self.patcher = p

    def tokenize(self, text):
        return {"l": text}

    def encode_from_tokens_scheduled(self, tokens):
        return [[("cond",), {"pooled_output": "pooled"}]]


check("SD1ClipModel -> sd15", md.detect_clip_arch(FakeClip(SD1ClipModel(), TokenizerL()))["family"], "sd15")
check("SDXLClipModel -> sdxl", md.detect_clip_arch(FakeClip(SDXLClipModel(), TokenizerXL()))["family"], "sdxl")
check("SD3ClipModel -> sd3", md.detect_clip_arch(FakeClip(SD3ClipModel(), TokenizerT5()))["family"], "sd3")
check("FluxClipModel -> flux", md.detect_clip_arch(FakeClip(FluxClipModel(), TokenizerT5()))["family"], "flux")
check("SD2ClipModel -> sd21", md.detect_clip_arch(FakeClip(SD2ClipModel(), TokenizerH()))["family"], "sd21")

# third-party wrapper: class name unknown, tokenizer must save us
wrapped = md.detect_clip_arch(FakeClip(SomeThirdPartyWrapper(), TokenizerXL()))
check("unknown class + clip_g tokenizer -> sdxl", wrapped["family"], "sdxl")
check("...and it says so in the evidence", "tokenizer" in wrapped["source"], True)

# unknown class + patcher model class name
class FakePatcher:
    pass


check("unknown class + patcher.model -> flux",
      md.detect_clip_arch(FakeClip(SomeThirdPartyWrapper(), None, FluxClipModel()))["family"], "flux")
check("totally unknown -> unknown", md.detect_clip_arch(FakeClip())["family"], "unknown")
check("None clip -> unknown", md.detect_clip_arch(None)["family"], "unknown")
check("empty fake object -> unknown", md.detect_clip_arch(object())["family"], "unknown")

# detection must never raise, even when attributes explode
class Exploding:
    @property
    def cond_stage_model(self):
        raise RuntimeError("boom")

    @property
    def tokenizer(self):
        raise RuntimeError("boom")


check("exploding attributes -> unknown (no raise)", md.detect_clip_arch(Exploding())["family"], "unknown")


# ======================================================================
# 2. the node contract
# ======================================================================

print()
print("=" * 92)
print("2. node contract (ui payload must survive execution.py)")
print("=" * 92)

node = smart_nodes.SmartCLIPTextEncode()
result = node.encode(FakeClip(SDXLClipModel(), TokenizerXL()), "masterpiece, 1girl", "auto", "质量词")

check_true("returns a dict", isinstance(result, dict))
check_true("has ui and result", "ui" in result and "result" in result)
check("result carries CONDITIONING", result["result"][0], [[("cond",), {"pooled_output": "pooled"}]])
check("result carries the model label", result["result"][1], "SDXL")

ui = result["ui"]
check_true("ui values are lists", isinstance(ui["smart_clip"], list))
check("ui payload is a single dict", len(ui["smart_clip"]), 1)
check("payload family", ui["smart_clip"][0]["family"], "sdxl")
check("payload category annotation", ui["smart_clip"][0]["category"], "质量词")

# literal replay of execution.py:
#   ui = {k: [y for x in uis for y in x[k]] for k in uis[0].keys()}
uis = [ui]
flattened = {k: [y for x in uis for y in x[k]] for k in uis[0].keys()}
check("after execution.py flattening", flattened["smart_clip"][0]["family"], "sdxl")

# the trap the draft fell into: a bare string would be split into characters
bad_uis = [{"smart_clip": "sdxl"}]
bad_flat = {k: [y for x in bad_uis for y in x[k]] for k in bad_uis[0].keys()}
check("(demonstration) a bare string would become", bad_flat["smart_clip"], ["s", "d", "x", "l"])

check("IS_CHANGED is not overridden", hasattr(smart_nodes.SmartCLIPTextEncode, "IS_CHANGED"), False)
check("RETURN_TYPES keeps drop-in compatibility",
      smart_nodes.SmartCLIPTextEncode.RETURN_TYPES[0], "CONDITIONING")
check("node registers under SmartCLIPTextEncode",
      "SmartCLIPTextEncode" in smart_nodes.NODE_CLASS_MAPPINGS, True)
check("INPUT_TYPES declares clip/text like the core node",
      [k for k in smart_nodes.SmartCLIPTextEncode.INPUT_TYPES()["required"]][:2], ["clip", "text"])


# ======================================================================
# 3. file-based detection against the real checkpoints
# ======================================================================

print()
print("=" * 92)
print("3. pre-execution detection (real files on this machine)")
print("=" * 92)

CASES = [
    ("checkpoints", "majicmixRealistic_v7.safetensors", "sd15", "sd15"),
    ("checkpoints", "sd1.5\\anything-v5.safetensors", "sd15", "sd15"),
    ("checkpoints", "hassakuXLIllustrious_v13StyleA.safetensors", "sdxl", "illustrious"),
    ("checkpoints", "waiNSFWIllustrious_v100.safetensors", "sdxl", "illustrious"),
    ("checkpoints", "ponyDiffusionV6XL_v6StartWithThisOne.safetensors", "sdxl", "pony"),
    ("checkpoints", "boleromixPony_v170.safetensors", "sdxl", "pony"),
    ("checkpoints", "jewelry_v10.safetensors", "sdxl", "sdxl"),
    ("checkpoints", "anijed_v10.safetensors", "sdxl", "sdxl"),
    ("checkpoints", "does_not_exist_pony_v1.safetensors", "pony", "pony"),
]
for kind, name, want_family, want_preset in CASES:
    got = md.detect_checkpoint(kind, name)
    check("%-52s -> %s/%s" % (name[:52], want_family, want_preset),
          (got["family"], got["preset"]), (want_family, want_preset))

check("cached second call is marked", md.detect_checkpoint(
    "checkpoints", "jewelry_v10.safetensors").get("cached"), True)

# name hints
check("hint pony", md.hint_from_name("ponyDiffusionV6XL.safetensors"), "pony")
check("hint illustrious", md.hint_from_name("hassakuXLIllustrious_v2.safetensors"), "illustrious")
check("hint krea", md.hint_from_name("snofs_krea_v1_4.safetensors"), "krea2")
check("hint flux", md.hint_from_name("flux1-dev-fp8.safetensors"), "flux")
check("hint none", md.hint_from_name("jewelry_v10.safetensors"), "")
check("preset_key_for(sdxl, pony)", md.preset_key_for("sdxl", "pony"), "pony")
check("preset_key_for(sd15, pony) keeps the architecture",
      md.preset_key_for("sd15", "pony"), "sd15")
check("preset_key_for(unknown, krea2)", md.preset_key_for("unknown", "krea2"), "generic")


# ======================================================================
# 4. presets
# ======================================================================

print()
print("=" * 92)
print("4. presets (shape stability)")
print("=" * 92)

# 词库现在会在读取时把用户自建分类收拢进 _shared（见第 8 节），所以这一段
# 以及后面几节一律跑在真实词库的一个**临时拷贝**上——测试永远不许改写真文件。
import shutil                        # noqa: E402
import tempfile                      # noqa: E402

_REAL_PRESET = ps.PRESET_FILE
_PRESET_COPY = os.path.join(tempfile.mkdtemp(prefix="smartclip-presets-"), "presets.json")
if os.path.isfile(_REAL_PRESET):
    shutil.copyfile(_REAL_PRESET, _PRESET_COPY)
ps.PRESET_FILE = _PRESET_COPY
ps.clear_cache()
print("  (working on a copy of %s)" % _REAL_PRESET)

pony = ps.load("pony", "positive")
check("pony/positive comes from the json", pony["source"], "file")
check_true("pony has categories", len(pony["categories"]) >= 3)
check_true("pony has score tags", any("score_9" in p for v in pony["categories"].values() for p in v))
check("roles offered", pony["roles"], ["positive", "negative"])
check_true("models list is populated", "sdxl" in pony["models"] and "generic" in pony["models"])

neg = ps.load("sd15", "negative")
check("sd15/negative source", neg["source"], "file")
check_true("sd15 negative mentions embeddings",
           any("embedding:" in p for v in neg["categories"].values() for p in v))

unknown_model = ps.load("no_such_model", "positive")
check_true("unknown model still has categories", len(unknown_model["categories"]) > 0)
check("unknown model is normalised to a key", unknown_model["model"], "no_such_model")
check("unknown model falls back to the generic built-ins",
      all(name in unknown_model["categories"] for name in ("质量词", "光照", "镜头")), True)
check("unknown model gets no family-only presets",
      "评分标签" in unknown_model["categories"], False)

bad_role = ps.load("pony", "sideways")
check("bad role falls back to positive", bad_role["role"], "positive")

text = ps.text_for("pony", "positive", "评分标签")
check_true("text_for joins a category", "score_9" in text["text"])
check("text_for on a missing category", ps.text_for("pony", "positive", "nope")["found"], False)

info = ps.info()
check_true("info lists the preset file", info["preset_file"].endswith("presets.json"))

# ---- drift tolerance: every shape the file might contain -------------
SHAPES = {
    "str": "single string",
    "list": ["a", "b"],
    "dict_prompts": {"prompts": ["c", "d"]},
    "dict_words": {"words": "e, f"},
    "nested": [["g"], {"prompts": ["h"]}],
    "mixed_junk": [1, 2, None, "i"],
    "empty": [],
}
for label, value in SHAPES.items():
    normalised = ps._normalise_role({"cat": value})
    if label == "empty":
        # 显式空分类要**保留**而不是丢掉：「+ 新建分类」建出来的就是空分类，
        # 丢掉它左侧就不会出现那一行，也就没有对象可以右键改名/删除。
        check("shape %-14s -> kept as empty category" % label, normalised, {"cat": []})
    else:
        check_true("shape %-14s -> list of strings" % label,
                   isinstance(normalised["cat"], list)
                   and all(isinstance(x, str) for x in normalised["cat"]))

check("non-dict role is tolerated", ps._normalise_role("nonsense"), {})

# ---- a broken json file must not break the endpoint ------------------
original = ps.PRESET_FILE
import tempfile  # noqa: E402

try:
    fd, tmp = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write("{ this is not json ]")
    ps.PRESET_FILE = tmp
    ps.clear_cache()
    broken = ps.load("pony", "positive")
    check("broken json -> builtin fallback", broken["source"], "builtin")
    check_true("broken json still yields categories", len(broken["categories"]) > 0)
finally:
    ps.PRESET_FILE = original
    ps.clear_cache()
    try:
        os.remove(tmp)
    except OSError:
        pass


# ======================================================================
print()
print("=" * 92)
print("5. embedding compatibility (installed? same text encoder?)")
print("=" * 92)

import json as _json                 # noqa: E402
import shutil                        # noqa: E402
import tempfile                      # noqa: E402

_EMB_DIR = tempfile.mkdtemp(prefix="smartclip-emb-")


def _write_safetensors(path, tensors):
    """A real safetensors header: 8-byte little-endian length + JSON."""
    header = {name: {"dtype": "F32", "shape": list(shape), "data_offsets": [0, 0]}
              for name, shape in tensors.items()}
    blob = _json.dumps(header).encode("utf-8")
    with open(path, "wb") as handle:
        handle.write(len(blob).to_bytes(8, "little"))
        handle.write(blob)


try:
    _write_safetensors(os.path.join(_EMB_DIR, "sd15_ti.safetensors"), {"emb_params": [1, 768]})
    _write_safetensors(os.path.join(_EMB_DIR, "sd2_ti.safetensors"), {"emb_params": [1, 1024]})
    _write_safetensors(os.path.join(_EMB_DIR, "sdxl_ti.safetensors"),
                       {"clip_g": [1, 1280], "clip_l": [1, 768]})
    _write_safetensors(os.path.join(_EMB_DIR, "weird_ti.safetensors"), {"foo": [1, 2]})
    # a .pt textual inversion: torch.save writes the key names into the head
    with open(os.path.join(_EMB_DIR, "oldstyle.pt"), "wb") as handle:
        handle.write(b"PK\x03\x04" + b"\x00" * 32 +
                     b"sd_checkpoint_name" + b"\x00" * 16 + b"emb_params" + b"\x00" * 32)
    # a truncated/corrupt safetensors must never raise
    with open(os.path.join(_EMB_DIR, "broken.safetensors"), "wb") as handle:
        handle.write((1 << 40).to_bytes(8, "little") + b"not json")

    os.environ["SMARTCLIP_EMBEDDINGS_DIR"] = _EMB_DIR
    ec.clear_cache()
    ps.clear_cache()

    check("embedding dirs honour the override", ec.embedding_dirs()[0], _EMB_DIR)
    check("installed embeddings indexed", len(ec.embedding_index()), 6)
    check("768-dim emb_params -> SD1.5",
          ec.classify(os.path.join(_EMB_DIR, "sd15_ti.safetensors"))["arch"], ec.TI_SD15)
    check("1024-dim emb_params -> SD2.x",
          ec.classify(os.path.join(_EMB_DIR, "sd2_ti.safetensors"))["arch"], ec.TI_SD21)
    check("clip_g -> SDXL",
          ec.classify(os.path.join(_EMB_DIR, "sdxl_ti.safetensors"))["arch"], ec.TI_SDXL)
    check("unreadable header -> unknown (no raise)",
          ec.classify(os.path.join(_EMB_DIR, "broken.safetensors"))["arch"], ec.TI_UNKNOWN)
    check("headerless safetensors -> unknown",
          ec.classify(os.path.join(_EMB_DIR, "weird_ti.safetensors"))["arch"], ec.TI_UNKNOWN)
    check(".pt without an SDXL marker -> SD1.5",
          ec.classify(os.path.join(_EMB_DIR, "oldstyle.pt"))["arch"], ec.TI_SD15)

    check("a name without its extension resolves",
          bool(ec.resolve("sd15_ti")), True)
    check("a subfolder-style name resolves",
          bool(ec.resolve("sd15_ti.safetensors")), True)
    check("a folder-qualified reference is not reduced to its basename",
          ec.resolve("some/nonexistent/dir/sd15_ti.safetensors"), None)
    check("a missing embedding does not resolve", ec.resolve("nope"), None)

    check("embedding_name() extracts the reference",
          ec.embedding_name("embedding:EasyNegative"), "EasyNegative")
    check("embedding_name() ignores ordinary words",
          ec.embedding_name("masterpiece"), "")
    check("a bare installed name is recognised as a reference",
          ec.reference_name("sd15_ti"), "sd15_ti")
    check("...with the extension too",
          ec.reference_name("sd15_ti.safetensors"), "sd15_ti.safetensors")
    check("an ordinary word is not a reference",
          ec.reference_name("masterpiece"), "")
    check("a phrase is never mistaken for a name",
          ec.reference_name("EasyNegative, blurry"), "")
    check("annotate() ignores ordinary words", ec.annotate("masterpiece", "sd15"), None)

    check("SD1.5 TI on SD1.5 -> ok",
          ec.annotate("embedding:sd15_ti", "sd15")["state"], "ok")
    check("SD1.5 TI on SDXL -> partial (CLIP-L takes it, CLIP-G drops it)",
          ec.annotate("embedding:sd15_ti", "sdxl")["state"], "partial")
    check("...on pony / illustrious too",
          [ec.annotate("embedding:sd15_ti", f)["state"] for f in ("pony", "illustrious")],
          ["partial", "partial"])
    check("...and the reason names the encoder that drops it",
          "CLIP-G" in ec.annotate("embedding:sd15_ti", "sdxl")["why"], True)
    check("an unidentified base family claims nothing",
          ec.annotate("embedding:sd15_ti", "unknown")["state"], "unknown")
    check("...nor does generic",
          ec.annotate("embedding:sdxl_ti", "generic")["state"], "unknown")
    check("SDXL TI on SDXL -> ok",
          ec.annotate("embedding:sdxl_ti", "sdxl")["state"], "ok")
    check("SDXL TI on SD1.5 -> incompatible",
          ec.annotate("embedding:sdxl_ti", "sd15")["state"], "incompatible")
    check("...and the reason names both sides",
          "SDXL" in ec.annotate("embedding:sdxl_ti", "sd15")["why"]
          and "SD 1.5" in ec.annotate("embedding:sdxl_ti", "sd15")["why"], True)
    check("SD2 TI on SD1.5 -> incompatible",
          ec.annotate("embedding:sd2_ti", "sd15")["state"], "incompatible")
    check("not installed -> missing",
          ec.annotate("embedding:ghost", "sd15")["state"], "missing")
    check("SD1.5 TI on SD3 -> partial (only the 768 CLIP-L takes it)",
          ec.annotate("embedding:sd15_ti", "sd3")["state"], "partial")
    check("SD1.5 TI on FLUX -> partial (only the 768 CLIP-L takes it)",
          ec.annotate("embedding:sd15_ti", "flux")["state"], "partial")
    check("SDXL TI on SD3 -> ok (SD3 has the 1280 encoder too)",
          ec.annotate("embedding:sdxl_ti", "sd3")["state"], "ok")
    check("SDXL TI on FLUX -> incompatible (no 1280 encoder there)",
          ec.annotate("embedding:sdxl_ti", "flux")["state"], "incompatible")
    check("unknown architecture is not a claim",
          ec.annotate("embedding:weird_ti", "sd15")["state"], "unknown")
    check("a bare name gets the same verdict",
          ec.annotate("sdxl_ti", "sd15")["state"], "incompatible")
    check("...and is marked as a bare reference",
          ec.annotate("sdxl_ti", "sd15")["reference"], "bare")
    check("an explicit reference is marked as such",
          ec.annotate("embedding:sdxl_ti", "sd15")["reference"], "embedding:")
    # ComfyUI weight syntax must not be read as part of the file name, or a
    # perfectly installed embedding is reported as "未安装".
    check("a weighted reference keeps its name",
          ec.embedding_name("embedding:sd15_ti:1.2"), "sd15_ti")
    check("...and is judged, not called missing",
          ec.annotate("(embedding:sd15_ti:1.2)", "sd15")["state"], "ok")
    check("...inside a long prompt too",
          ec.annotate("masterpiece, (embedding:sdxl_ti:0.8)", "sd15")["state"],
          "incompatible")
    check("a weight is not a name",
          ec.annotate("(embedding:sd15_ti:-0.5)", "sd15")["name"], "sd15_ti")
    check("a closing bracket is not part of the name",
          ec.annotate("embedding:sd15_ti)", "sd15")["name"], "sd15_ti")

    # a whole negative prompt that quotes embeddings inside it
    check("a prompt quoting an SDXL embedding is judged by its worst one",
          ec.annotate("masterpiece, embedding:sdxl_ti, blurry", "sd15")["state"],
          "incompatible")
    check("...and reports how many it saw",
          ec.annotate("masterpiece, embedding:sdxl_ti, embedding:sd15_ti", "sd15")["name"],
          "2 个词嵌入")
    check("...with the offender named in the reason",
          "sdxl_ti" in ec.annotate("masterpiece, embedding:sdxl_ti", "sd15")["why"], True)
    check("a prompt with only compatible references is ok",
          ec.annotate("best quality, embedding:sd15_ti", "sd15")["state"], "ok")
    check("a plain prompt gets no badge",
          ec.annotate("masterpiece, best quality", "sd15"), None)

    annotations, stats = ec.annotate_categories(
        {"词嵌入": ["embedding:sd15_ti", "embedding:sdxl_ti", "masterpiece", "sd15_ti"],
         "其它": ["embedding:ghost"]}, "sd15")
    check("only embedding entries are annotated", sorted(annotations),
          ["embedding:ghost", "embedding:sd15_ti", "embedding:sdxl_ti", "sd15_ti"])
    check("stats count each state",
          (stats["total"], stats["ok"], stats["incompatible"], stats["missing"]), (4, 2, 1, 1))

    # the shipped word lists, resolved against this controlled folder
    shipped = ps.load("sd15", "negative")
    check_true("presets.load carries annotations", bool(shipped["annotations"]))
    check_true("presets.load carries stats", shipped["embedding_stats"]["total"] >= 1)
    check("their shipped embeddings are reported missing here",
          shipped["annotations"]["embedding:EasyNegative"]["state"], "missing")
    check("info() exposes the embedding index",
          ps.info()["embeddings"]["count"] >= 1, True)
finally:
    os.environ.pop("SMARTCLIP_EMBEDDINGS_DIR", None)
    ec.clear_cache()
    ps.clear_cache()
    shutil.rmtree(_EMB_DIR, ignore_errors=True)


# ======================================================================
print()
print("=" * 92)
print("6. add_entry (弹窗里的「入库」)")
print("=" * 92)

_ADD_DIR = tempfile.mkdtemp(prefix="smartclip-add-")
_ADD_FILE = os.path.join(_ADD_DIR, "presets.json")
_ORIG_PRESET = ps.PRESET_FILE

try:
    with open(_ADD_FILE, "w", encoding="utf-8") as _handle:
        _json.dump({"_readme": ["keep me"],
                    "sd15": {"negative": {"旧分类": ["old", "word"]}}},
                   _handle, ensure_ascii=False)
    ps.PRESET_FILE = _ADD_FILE
    ps.clear_cache()

    report = ps.add_entry("sd15", "negative", "旧分类", "new word")
    check("appends to an existing category",
          (report["ok"], report["duplicate"], report["count"]), (True, False, 3))
    check("...and load() sees it immediately",
          "new word" in ps.load("sd15", "negative")["categories"]["旧分类"], True)
    check("自建分类被收进共享段（所有弹窗都能看到）",
          report["stored_in"], ps.SHARED_MODEL)

    report = ps.add_entry("sd15", "negative", "新分类", "fresh")
    check("creates a category", report["count"], 1)
    check("...which then shows up",
          "新分类" in ps.load("sd15", "negative")["categories"], True)

    ps.add_entry("sdxl", "positive", "我的库", "hello, world")
    check("creates the family + role when needed",
          ps.load("sdxl", "positive")["categories"].get("我的库"), ["hello, world"])

    report = ps.add_entry("sd15", "negative", "旧分类", "new word")
    check("a duplicate is reported, not stored", report["duplicate"], True)
    check("...and the count does not grow", report["count"], 3)

    with open(_ADD_FILE, "r", encoding="utf-8") as _handle:
        _raw = _json.load(_handle)
    check("unrelated keys survive the write", _raw.get("_readme"), ["keep me"])
    check("the entry really is in the file",
          _raw[ps.SHARED_MODEL]["negative"]["旧分类"][-1], "new word")
    check("a rolling backup is kept", os.path.isfile(_ADD_FILE + ps.BACKUP_SUFFIX), True)
    check("no temp file is left behind",
          [f for f in os.listdir(_ADD_DIR) if f.startswith(".presets.json.tmp")], [])

    for _label, _args in (
        ("empty text", ("sd15", "negative", "旧分类", "   ")),
        ("empty category", ("sd15", "negative", "", "x")),
        ("comment-like model", ("_notes", "negative", "c", "x")),
        ("over-long text", ("sd15", "negative", "旧分类", "x" * (ps.MAX_ENTRY_TEXT + 1))),
    ):
        try:
            ps.add_entry(*_args)
            check("rejects %s" % _label, "wrote it anyway", "ValueError")
        except ValueError:
            check("rejects %s" % _label, "ValueError", "ValueError")

    # a broken file must never be silently overwritten
    with open(_ADD_FILE, "w", encoding="utf-8") as _handle:
        _handle.write("{ not json ]")
    ps.clear_cache()
    try:
        ps.add_entry("sd15", "negative", "旧分类", "should not land")
        check("refuses to write into a broken file", "wrote", "refused")
    except ValueError:
        check("refuses to write into a broken file", "refused", "refused")
    with open(_ADD_FILE, "r", encoding="utf-8") as _handle:
        check("...and leaves it exactly as it was", _handle.read(), "{ not json ]")

    # a missing file is created rather than refused
    os.remove(_ADD_FILE)
    ps.clear_cache()
    ps.add_entry("generic", "positive", "临时", "first")
    with open(_ADD_FILE, "r", encoding="utf-8") as _handle:
        _created = _json.load(_handle)
    check("creates the word list when there is none",
          _created[ps.SHARED_MODEL]["positive"]["临时"], ["first"])

    check("info() advertises the writable path", ps.info()["editable"], True)

    # the dialog only enables its write button when the backend says so
    check("load() advertises the write route",
          ps.load("sd15", "negative")["writable"], True)
finally:
    ps.PRESET_FILE = _ORIG_PRESET
    ps.clear_cache()
    shutil.rmtree(_ADD_DIR, ignore_errors=True)


# ======================================================================
print()
print("=" * 92)
print("7. 拆分入库 (classify + add_entries)")
print("=" * 92)

import classify as cl                 # noqa: E402

check("splits on commas",
      cl.split_tags("masterpiece, 1girl , long hair"),
      ["masterpiece", "1girl", "long hair"])
check("splits on newlines too",
      cl.split_tags("masterpiece\n1girl\r\nlong hair"), ["masterpiece", "1girl", "long hair"])
check("drops empties and duplicates",
      cl.split_tags("a,, a ,,b"), ["a", "b"])
check("drops BREAK",
      cl.split_tags("masterpiece, BREAK, 1girl"), ["masterpiece", "1girl"])
check("keeps weighted tags as written",
      cl.split_tags("(red dress:1.2), [long hair]"), ["(red dress:1.2)", "[long hair]"])
check("splits on full-width commas too",
      cl.split_tags("杰作，1girl，长发"), ["杰作", "1girl", "长发"])
check("splits on full-width semicolons too",
      cl.split_tags("杰作；1girl"), ["杰作", "1girl"])

# 一段没有 ASCII 逗号的英文散文：旧版按 200 字静默丢弃，前端还报「先输入要入库的提示词」
_prose = ("A photorealistic cinematic photograph of a young woman standing alone in a rain "
          "soaked street at night while neon reflections ripple across the wet asphalt")
check("pasted prose gives entries instead of nothing", cl.plan(_prose)["total"], 1)

# 超过 MAX_TAG_CHARS 的长段会被切开，内容一个字都不能丢
_words = " ".join("w%03d" % i for i in range(700))          # > 2000 字、有空格可断
_parts, _dropped = cl.split_tags_ex(_words)
check("an over-long chunk is split, not dropped", len(_parts) > 1, True)
check("...and nothing is reported as dropped", _dropped, [])
check("...and every piece fits the ceiling",
      max(len(p) for p in _parts) <= cl.MAX_TAG_CHARS, True)
check("...and no word is lost",
      "".join(_parts).replace(" ", ""), _words.replace(" ", ""))

# 只有完全无断点的一整块（超长且无空白）才会进 dropped，并如实上报
_blob = "x" * (cl.MAX_TAG_CHARS + 50)
check("an unbreakable blob produces no tag", cl.split_tags_ex(_blob)[0], [])
check("...and is reported instead of vanishing", len(cl.split_tags_ex(_blob)[1]), 1)
check("plan carries the dropped chunks", cl.plan(_blob)["dropped"] != [], True)
check("a normal plan reports nothing dropped", cl.plan("1girl, long hair")["dropped"], [])

for tag, want in (
    ("masterpiece", "质量词"),
    ("best quality", "质量词"),
    ("1girl", "人物"),
    ("solo", "人物"),
    ("long hair", "发型"),
    ("双马尾", "发型"),
    ("red dress", "衣服"),
    ("白色衬衫", "衣服"),
    ("thighhighs", "衣服"),
    ("necklace", "配饰"),
    ("smile", "表情"),
    ("standing", "动作姿势"),
    ("forest", "环境"),
    ("城市夜景", "环境"),
    ("soft lighting", "光照"),
    ("逆光", "光照"),
    ("close-up", "镜头"),
    ("(red dress:1.2)", "衣服"),
    ("[long hair]", "发型"),
    ("zzz nothing matches", "其它"),
):
    check("classify %-20s -> %s" % (tag[:20], want), cl.classify_tag(tag), want)

# a keyword on a token boundary beats one buried inside a longer word
check("boundary match wins (hairband -> 配饰)", cl.classify_tag("hairband"), "配饰")
check("substring match still classifies (hairstyle)", cl.classify_tag("hairstyle"), "发型")

result = cl.plan("masterpiece, 1girl, long hair, red dress, forest, zzz")
check("plan counts per category",
      result["counts"], {"质量词": 1, "人物": 1, "发型": 1, "衣服": 1, "环境": 1, "其它": 1})
check("plan total", result["total"], 6)
check("plan lists the categories", result["fallback"], "其它")
check("empty text plans nothing", cl.plan("   ")["total"], 0)
check_true("info() describes the rules",
           cl.info()["source"] in ("file", "builtin") and cl.info()["keywords"] > 0)

# the shipped rules file must not silently disagree with the built-in table
if cl.info()["source"] == "file":
    check("shipped rules cover the built-in categories",
          sorted(cl.rules()["categories"]), sorted(cl.BUILTIN_RULES["categories"]))
else:
    check("rules file ships with the plugin", cl.info()["exists"], True)

# ---- a user rule file overrides the built-in table -------------------
_ORIG_RULES = cl.RULES_FILE
try:
    _rule_file = os.path.join(tempfile.mkdtemp(prefix="smartclip-rules-"), "classify_rules.json")
    with open(_rule_file, "w", encoding="utf-8") as _handle:
        _json.dump({"fallback": "未分类",
                    "categories": {"我的分类": ["1girl", "superstar"]}}, _handle, ensure_ascii=False)
    cl.RULES_FILE = _rule_file
    cl.clear_cache()
    check("a user rule file is used", cl.info()["source"], "file")
    check("...and its categories apply", cl.classify_tag("1girl"), "我的分类")
    check("...with its own fallback", cl.classify_tag("masterpiece"), "未分类")

    with open(_rule_file, "w", encoding="utf-8") as _handle:
        _handle.write("{ broken ]")
    cl.clear_cache()
    check("a broken rule file falls back to builtin", cl.info()["source"], "builtin")
    check("...and still classifies", cl.classify_tag("1girl"), "人物")
finally:
    cl.RULES_FILE = _ORIG_RULES
    cl.clear_cache()

# ---- the batch writer -------------------------------------------------
_BATCH_DIR = tempfile.mkdtemp(prefix="smartclip-batch-")
_BATCH_FILE = os.path.join(_BATCH_DIR, "presets.json")
_ORIG_BATCH = ps.PRESET_FILE
try:
    with open(_BATCH_FILE, "w", encoding="utf-8") as _handle:
        _json.dump({"_readme": ["keep"], "sd15": {"positive": {"质量词": ["masterpiece"]}}},
                   _handle, ensure_ascii=False)
    ps.PRESET_FILE = _BATCH_FILE
    ps.clear_cache()

    report = ps.add_entries("sd15", "positive", [
        {"category": "质量词", "text": "masterpiece"},          # duplicate
        {"category": "人物", "text": "1girl"},
        {"category": "发型", "text": "long hair"},
        {"category": "环境", "text": "forest"},
        {"category": "人物", "text": "   "},                     # invalid -> skipped
    ])
    check("writes the valid entries", (report["added"], report["duplicates"]), (3, 1))
    check("...per category counts", report["categories"], {"人物": 1, "发型": 1, "环境": 1})
    check("...reports what it skipped", len(report["skipped"]), 1)
    check("...with a reason", report["skipped"][0]["error"], "提示词不能为空")
    check("...one backup for the whole batch",
          os.path.isfile(_BATCH_FILE + ps.BACKUP_SUFFIX), True)

    loaded = ps.load("sd15", "positive")["categories"]
    check("every category is readable afterwards",
          [loaded.get("人物"), loaded.get("发型"), loaded.get("环境")],
          [["1girl"], ["long hair"], ["forest"]])
    check("the untouched category is intact", loaded.get("质量词"), ["masterpiece"])

    again = ps.add_entries("sd15", "positive", [{"category": "人物", "text": "1girl"}])
    check("an all-duplicate batch changes nothing",
          (again["added"], again["changed"]), (0, False))

    try:
        ps.add_entries("sd15", "positive", [{"category": "人物", "text": ""}])
        check("a fully invalid batch raises", "wrote", "ValueError")
    except ValueError:
        check("a fully invalid batch raises", "ValueError", "ValueError")

    with open(_BATCH_FILE, "r", encoding="utf-8") as _handle:
        _raw_batch = _json.load(_handle)
    check("other keys survive a batch write", _raw_batch.get("_readme"), ["keep"])
finally:
    ps.PRESET_FILE = _ORIG_BATCH
    ps.clear_cache()
    shutil.rmtree(_BATCH_DIR, ignore_errors=True)


# ======================================================================
print()
print("=" * 92)
print("8. 全局分类（_shared）：新建的分类在所有的提示词弹窗都能看到")
print("=" * 92)

_G_DIR = tempfile.mkdtemp(prefix="smartclip-global-")
_G_FILE = os.path.join(_G_DIR, "presets.json")
_ORIG_GLOBAL = ps.PRESET_FILE
try:
    with open(_G_FILE, "w", encoding="utf-8") as _handle:
        _json.dump({"_readme": ["keep"],
                    "pony": {"positive": {"评分标签": ["score_9"]}},
                    "sdxl": {"positive": {"用户的东西": ["mine"]},
                             "negative": {"用户负面": ["bad"]}}},
                   _handle, ensure_ascii=False)
    ps.PRESET_FILE = _G_FILE
    ps.clear_cache()

    # ---- 老文件：散落在模型族下面的自建分类，读取时自动收拢 -----------
    categories = ps.load("illustrious", "positive")["categories"]
    check("别的族能看到 sdxl 下建的自建分类", "用户的东西" in categories, True)
    check("...内容也在", categories.get("用户的东西"), ["mine"])
    check("方向是隔离的：反向分类不进正向", "用户负面" in categories, False)
    check("...反向弹窗里能看到", "用户负面" in ps.load("pony", "negative")["categories"], True)
    check("族内预设在别的族里不出现", "评分标签" in categories, False)
    check("...在本族里还在", "评分标签" in ps.load("pony", "positive")["categories"], True)

    with open(_G_FILE, "r", encoding="utf-8") as _handle:
        _raw_g = _json.load(_handle)
    check("文件里出现 _shared 段", isinstance(_raw_g.get(ps.SHARED_MODEL), dict), True)
    check("...自建分类搬过去了",
          _raw_g[ps.SHARED_MODEL]["positive"].get("用户的东西"), ["mine"])
    check("...空的模型族被清掉了", "sdxl" in _raw_g, False)
    check("...族内预设原地不动", _raw_g["pony"]["positive"]["评分标签"], ["score_9"])
    check("迁移留了一次性备份", os.path.isfile(_G_FILE + ps.MIGRATION_SUFFIX), True)
    check("迁移是幂等的", ps._promote_user_categories(), [])
    check("注释键没被弄丢", _raw_g.get("_readme"), ["keep"])

    # ---- 新建分类：进共享段，处处可见 -------------------------------
    created = ps.create_category("flux", "positive", "我的新分类")
    check("新建分类 -> 共享段", created["stored_in"], ps.SHARED_MODEL)
    check("...标成全局", created["global"], True)
    created_again = ps.create_category("illustrious", "positive", "我的新分类")
    check("同一个分类不会被建第二遍", (created_again["created"], created_again["count"]),
          (False, 0))
    for _fam in ("generic", "sd15", "sdxl", "pony", "illustrious", "sd3", "flux"):
        check("%-12s 弹窗能看到它" % _fam,
              "我的新分类" in ps.load(_fam, "positive")["categories"], True)
    check("load() 把它标成全局分类",
          "我的新分类" in ps.load("sd15", "positive")["shared"], True)

    # ---- 族内预设仍然只属于那个族 -----------------------------------
    builtin = ps.add_entry("pony", "positive", "评分标签", "score_10")
    check("族内预设分类写回本族", builtin["stored_in"], "pony")
    check("...本族可见", "score_10" in ps.load("pony", "positive")["categories"]["评分标签"], True)
    check("...不污染别的族的同名列表",
          "score_10" in ps.load("illustrious", "positive")["categories"].get("评分标签", []),
          False)
    with open(_G_FILE, "r", encoding="utf-8") as _handle:
        _raw_g2 = _json.load(_handle)
    check("...文件里确实写在 pony 下面",
          _raw_g2["pony"]["positive"]["评分标签"], ["score_9", "score_10"])

    # ---- 改名 / 删除是全局的 ----------------------------------------
    ps.rename_category("generic", "positive", "我的新分类", "改名分类")
    check("改名后在别的族也生效",
          "改名分类" in ps.load("sdxl", "positive")["categories"], True)
    check("...旧名字彻底消失",
          "我的新分类" in ps.load("pony", "positive")["categories"], False)
    ps.delete_category("illustrious", "positive", "改名分类")
    check("删除后在别的族也消失",
          "改名分类" in ps.load("sd15", "positive")["categories"], False)

    ps.add_entry("generic", "positive", "用户的东西", "another")
    ps.delete_entry("flux", "positive", "用户的东西", "another")
    check("删词条后在别的族也看不到",
          "another" in ps.load("sd15", "positive")["categories"].get("用户的东西", []), False)
    check("...同分类别的词条不受影响",
          ps.load("sd15", "positive")["categories"].get("用户的东西"), ["mine"])

    # ---- 同名并集：共享分类撞上族内预设时两边都不丢 ------------------
    with open(_G_FILE, "r", encoding="utf-8") as _handle:
        _raw_g3 = _json.load(_handle)
    _raw_g3[ps.SHARED_MODEL]["positive"]["质量词"] = ["my own word"]
    with open(_G_FILE, "w", encoding="utf-8") as _handle:
        _json.dump(_raw_g3, _handle, ensure_ascii=False)
    ps.clear_cache()
    _merged = ps.load("pony", "positive")["categories"]["质量词"]
    check("共享分类与族内同名分类合并（不互相顶掉）",
          ("my own word" in _merged, "score_9" in ps.load("pony", "positive")["categories"]["评分标签"]),
          (True, True))
    check("...族内预设在合并里也没丢",
          ps.load("pony", "positive")["categories"]["质量词"][:1], ["masterpiece"])
finally:
    ps.PRESET_FILE = _ORIG_GLOBAL
    ps.clear_cache()
    shutil.rmtree(_G_DIR, ignore_errors=True)


# ======================================================================
# 9. workflow_model：前端说不出底模时，服务端从最近的图里兜底
# ======================================================================

print()
print("=" * 92)
print("9. workflow_model (底模兜底：ComfyUI 队列/历史 -> 词嵌入判定)")
print("=" * 92)

import types                          # noqa: E402
import embedding_preview as ep        # noqa: E402
import workflow_model as wm           # noqa: E402

# 真实文件里的 sdxl/illustrious：与第 3 节同一份期望
_CKPT = "hassakuXLIllustrious_v13StyleA.safetensors"


def _prompt_graph(ckpt=_CKPT):
    """用户那张图的形状：CheckpointLoaderSimple -> JosiaLoraStack -> CLIPTextEncode."""
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "92": {"class_type": "JosiaLoraStack",
               "inputs": {"clip": ["1", 1], "lora_name_1": "None"}},
        "21": {"class_type": "CLIPTextEncode",
               "inputs": {"clip": ["92", 1], "text": "worst quality, embedding:sd15_ti"}},
    }


class _FakeQueue:
    """The three places ComfyUI keeps prompt graphs."""

    def __init__(self, running=(), queued=(), history=()):
        self.currently_running = dict(running)
        self.queue = list(queued)
        self.history = dict(history)


def _entry(number, prompt):
    """(number, prompt_id, prompt, extra_data, outputs) - PromptQueue's tuple."""
    return (number, "prompt-%d" % number, prompt, {}, [])


def _install_server(queue):
    """Fake the ``server`` module ComfyUI provides, so no ComfyUI is needed."""
    module = types.ModuleType("server")
    module.PromptServer = types.SimpleNamespace(
        instance=types.SimpleNamespace(prompt_queue=queue))
    sys.modules["server"] = module


_ORIGINAL_SERVER = sys.modules.pop("server", None)

# ---- 没有任何 ComfyUI 上下文（独立运行 / 测试机）时不许抛 -------------
check("no server module -> nothing claimed", wm.resolve_preset("generic"),
      ("generic", "none"))
check("...but the caller's own verdict still wins", wm.resolve_preset("sdxl"),
      ("sdxl", "client"))
check("...and info() survives too", wm.info()["model"], None)

try:
    # ---- 空队列 -------------------------------------------------------
    _install_server(_FakeQueue())
    check("empty queue -> nothing claimed", wm.resolve_preset(""), ("generic", "none"))
    check("empty queue -> no loader", wm.workflow_loaders(), [])

    # ---- 最近一张已完成的图 -------------------------------------------
    _install_server(_FakeQueue(history={"p1": {"prompt": _entry(1, _prompt_graph())}}))
    check("the last run supplies the family", wm.resolve_preset("generic"),
          ("illustrious", "workflow"))
    check("...including when the request had no family at all",
          wm.resolve_preset(""), ("illustrious", "workflow"))
    check("the checkpoint is what counts, not a LoRA slot",
          [row[2] for row in wm.workflow_loaders()], [_CKPT])
    # family 可能是 sdxl（读到文件头）也可能是 illustrious（读不到文件、只按
    # 文件名猜）—— 取决于这次跑的是源码仓还是对部署目录跑（MCM_PLUGIN）。
    # 判定用的 preset 两条路一样，所以只断言这一点。
    check("info() reports what the server thinks is loaded",
          (wm.info()["model"]["family"] in ("sdxl", "illustrious"),
           wm.info()["model"]["class_type"]),
          (True, "CheckpointLoaderSimple"))
    check("a real verdict is never overridden", wm.resolve_preset("sd15"),
          ("sd15", "client"))

    # ---- 正在跑的 / 排队中的都比历史新 --------------------------------
    _install_server(_FakeQueue(
        running={0: _entry(2, _prompt_graph("majicmixRealistic_v7.safetensors"))},
        history={"p1": {"prompt": _entry(1, _prompt_graph())}}))
    check("a running prompt beats history", wm.resolve_preset("generic"),
          ("sd15", "workflow"))

    _install_server(_FakeQueue(
        queued=[_entry(3, _prompt_graph("ponyDiffusionV6XL_v6StartWithThisOne.safetensors"))]))
    check("a queued prompt is used when nothing has run yet",
          wm.resolve_preset("generic"), ("pony", "workflow"))

    # ---- 认不出来的文件不许让兜底说谎 ---------------------------------
    _install_server(_FakeQueue(
        history={"p1": {"prompt": _entry(1, _prompt_graph("no_idea_what_this_is.gguf"))}}))
    check("an unreadable loader claims nothing", wm.resolve_preset("generic"),
          ("generic", "none"))

    # ---- 词嵌入弹窗与词条徽标真拿到的判定 -----------------------------
    _FB_DIR = tempfile.mkdtemp(prefix="smartclip-wf-emb-")
    try:
        _write_safetensors(os.path.join(_FB_DIR, "sd15_ti.safetensors"),
                           {"emb_params": [1, 768]})
        _write_safetensors(os.path.join(_FB_DIR, "sdxl_ti.safetensors"),
                           {"clip_g": [1, 1280], "clip_l": [1, 768]})
        os.environ["SMARTCLIP_EMBEDDINGS_DIR"] = _FB_DIR
        ec.clear_cache()

        _install_server(_FakeQueue(history={"p1": {"prompt": _entry(1, _prompt_graph())}}))
        _data = ep.list_embeddings("generic")
        check("the picker is told which family was judged with",
              (_data["family"], _data["familySource"], _data["familyRequested"]),
              ("illustrious", "workflow", "generic"))
        check("...so the 768-dim TI stops being 'unknown'",
              _data["states"], {"partial": 1, "ok": 1})
        check("...and the half-compatible one says why",
              "CLIP-G" in _data["items"][0]["compat"]["why"], True)
        check("...while the SDXL one is plainly compatible",
              _data["items"][1]["compat"]["state"], "ok")

        _client = ep.list_embeddings("sd15")
        check("a client verdict is passed through unchanged",
              (_client["family"], _client["familySource"]), ("sd15", "client"))
        check("...and gives the SD1.5 verdicts",
              _client["states"], {"ok": 1, "incompatible": 1})

        _install_server(_FakeQueue())
        _none = ep.list_embeddings("generic")
        check("with nothing to fall back on the badges stay honest",
              (_none["family"], _none["familySource"], _none["states"]),
              ("generic", "none", {"unknown": 2}))

        _install_server(_FakeQueue(history={"p1": {"prompt": _entry(1, _prompt_graph())}}))
        _judged = ps.load("generic", "negative", verdict_model="illustrious")
        check("presets.load reports the family it judged against",
              _judged["embedding_family"], "illustrious")
        check("...without changing which word list it returned",
              _judged["model"], "generic")
        _unjudged = ps.load("generic", "negative")
        check("omitting verdict_model keeps the old behaviour",
              _unjudged["embedding_family"], "generic")
    finally:
        os.environ.pop("SMARTCLIP_EMBEDDINGS_DIR", None)
        ec.clear_cache()
        shutil.rmtree(_FB_DIR, ignore_errors=True)
finally:
    if _ORIGINAL_SERVER is None:
        sys.modules.pop("server", None)
    else:
        sys.modules["server"] = _ORIGINAL_SERVER


# ======================================================================
print()
print("=" * 92)
if FAILS:
    print("FAILURES: %d" % len(FAILS))
    for line in FAILS:
        print("  -", line)
    sys.exit(1)
print("FAILURES: 0")
