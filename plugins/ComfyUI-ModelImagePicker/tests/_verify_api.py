# -*- coding: utf-8 -*-
"""Live end-to-end verification (UTF-8 clean: no shell encoding in the way).

Point it at any running ComfyUI with MCM_BASE, e.g. your own instance:
    set MCM_BASE=http://127.0.0.1:8188
"""
import json
import os
import sys
import urllib.request

BASE = os.environ.get("MCM_BASE", "http://127.0.0.1:8189")
fail = 0


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, payload):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def expect(label, got, want):
    global fail
    ok = got == want
    if not ok:
        fail += 1
    print("  %-4s %-46s %s" % ("OK" if ok else "FAIL", label,
                               got if ok else "got %s want %s" % (got, want)))


idx = get("/modelconflict/index")
names = idx["kinds"]
print("index:", {k: len(v) for k, v in names.items()})

find = lambda kind, *frags: [n for n in names.get(kind, [])
                            if all(f.lower() in n.lower() for f in frags)]

picks = {
    "checkpoints": find("checkpoints", "majicmix"),
    "vae": find("vae", "vae-ft-mse"),
    "loras": (find("loras", "snofs") + find("loras", "privet-part")
              + find("loras", "add-detail-xl") + find("loras", "krea2_loraholic")
              + find("loras", "PROFESSIONAL_PORNOGRAPHIC") + find("loras", "TeeKays")),
    "embeddings": (find("embeddings", "deep_negative_pony") + find("embeddings", "EasyNegative")
                   + find("embeddings", "badhandv4")),
}
print("picks:", {k: len(v) for k, v in picks.items()})

print("\n[loras] workflow = SD1.5 base + Krea2/SDXL stack")
res = post("/modelconflict/check", {"kind": "loras", "names": names["loras"], "picks": picks})
print("  reference: %s (%s from %s)" % (res["reference"]["label"],
                                       res["reference"]["mode"], res["reference"]["source_kind"]))
print("  counts:", res["counts"])
expect("add-detail-xl (SDXL on SD1.5 base) is red",
       res["items"]["add-detail-xl.safetensors"]["state"], "conflict")
expect("privet-part (SDXL) is red",
       res["items"]["privet-part.safetensors"]["state"], "conflict")
expect("krea2 lora is red",
       res["items"][find("loras", "snofs")[0]]["state"], "conflict")
expect("sd1.5 lora is blue",
       res["items"][find("loras", "约尔4V")[0]]["state"], "ok")

print("\n[vae]")
res = post("/modelconflict/check", {"kind": "vae", "names": names["vae"], "picks": picks})
expect("ultraflux VAE (FLUX, 16ch) is red",
       res["items"][find("vae", "ultraflux")[0]]["state"], "conflict")
expect("color101 SD VAE is blue",
       res["items"][find("vae", "color101")[0]]["state"], "ok")

print("\n[embeddings]")
res = post("/modelconflict/check", {"kind": "embeddings", "names": names["embeddings"], "picks": picks})
expect("SDXL embedding deep_negative_pony is red",
       res["items"][find("embeddings", "deep_negative_pony")[0]]["state"], "conflict")
expect("SD1.5 embedding EasyNegative is blue",
       res["items"][find("embeddings", "EasyNegative.safetensors")[0]]["state"], "ok")

print("\n[checkpoints] base picker: what does the graph need?")
res = post("/modelconflict/check", {"kind": "checkpoints", "names": names["checkpoints"], "picks": picks})
print("  reference families:", res["reference"]["families"])
print("  counts:", res["counts"])
expect("majicmix (SD1.5) is red",
       res["items"][find("checkpoints", "majicmix")[0]]["state"], "conflict")
expect("illustrious checkpoint is blue",
       res["items"][find("checkpoints", "hassakuXLIllustrious_v13StyleA")[0]]["state"], "ok")

print("\n[no workflow models at all] -> nothing may be painted")
res = post("/modelconflict/check", {"kind": "loras", "names": names["loras"][:5], "picks": {}})
expect("reference is null", res["reference"], None)
expect("every item unknown", res["counts"]["unknown"], len(names["loras"][:5]))

print("\n[upscale models] never architecture bound")
res = post("/modelconflict/check", {"kind": "upscale_models", "names": names["upscale_models"], "picks": picks})
expect("all blue, none red",
       (res["counts"]["conflict"], res["counts"]["ok"]),
       (0, len(names["upscale_models"])))

print("\n[single model endpoint]")
one = get("/modelconflict/model?kind=loras&name=privet-part.safetensors")
expect("privet-part -> SDXL", one["arch"], "SDXL")

print("\nFAILURES:", fail)
sys.exit(1 if fail else 0)
