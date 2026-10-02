# -*- coding: utf-8 -*-
"""Engine self-test against the real model files on this machine."""
import os
import sys

try:  # a GBK console cannot print model names that contain U+2011 etc.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

PLUGIN = os.environ.get(
    "MCM_PLUGIN",
    r"C:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_ModelImagePicker")
sys.path.insert(0, PLUGIN)

import model_conflict as mc  # noqa: E402


def pick(items, name):
    """Look a name up regardless of the separator style used on Windows."""
    key = name.replace("\\", "/").lower()
    for k, v in items.items():
        if k.replace("\\", "/").lower() == key:
            return v
    return None


# (kind, name, expected arch) -- "SDXL*" means "any arch of the sdxl family"
CASES = [
    # ---- checkpoints -------------------------------------------------
    ("checkpoints", "majicmixRealistic_v7.safetensors", "SD15"),
    ("checkpoints", "sd1.5\\anything-v5.safetensors", "SD15"),
    ("checkpoints", "ponyDiffusionV6XL_v6StartWithThisOne.safetensors", "PONY"),
    ("checkpoints", "hassakuXLIllustrious_v13StyleA.safetensors", "ILLUSTRIOUS"),
    ("checkpoints", "waiNSFWIllustrious_v100.safetensors", "ILLUSTRIOUS"),
    ("checkpoints", "boleromixPony_v170.safetensors", "PONY"),
    ("checkpoints", "ceiiAnimePDXL_v12Pony.safetensors", "PONY*"),
    ("checkpoints", "jewelry_v10.safetensors", "SDXL"),
    # ---- loras -------------------------------------------------------
    ("loras", "add-detail-xl.safetensors", "SDXL"),
    ("loras", "privet-part.safetensors", "SDXL"),
    ("loras", "Kittew-4RCH0N.safetensors", "SDXL"),
    ("loras", "SkindentationSlider.safetensors", "SDXL"),
    ("loras", "灰原哀\\DetailedEyes_V3.safetensors", "SDXL"),
    ("loras", "Jewel_pendant_BS.safetensors", "SDXL"),
    ("loras", "约尔4V.safetensors", "SD15"),
    ("loras", "futaveiny6.safetensors", "SD15"),
    ("loras", "写实\\snofs_krea_v1_4文件超级大.safetensors", "KREA2"),
    ("loras", "写实\\ass_v2_krea2_loraholic.safetensors", "KREA2"),
    ("loras", "写实\\TeeKaysTittyTime_SkiSlopeTiddies_SteepSlopeTiddies_XXL_Kr2胸部.safetensors", "KREA2"),
    ("loras", "灰原哀\\ponyv6_noobV1_2_adamW-000017.safetensors", "SDXL*"),
    ("loras", "写实/PROFESSIONAL_PORNOGRAPHIC_PHOTOSHOOT4摄影模型.safetensors", "KREA2"),
    # ---- vae ---------------------------------------------------------
    ("vae", "color101VAE_v1.safetensors", "SDVAE"),
    ("vae", "sd1.5\\vae-ft-mse-840000-ema-pruned.safetensors", "SDVAE"),
    ("vae", "vae-ft-mse-840000-ema-pruned.safetensors", "SDVAE"),   # subfolder, bare name
    ("vae", "animevae.pt", "SDVAE"),                                # subfolder, .pt
    ("vae", "anythingModelVAEV40_v10.pt", "SDVAE"),
    ("vae", "ultrafluxVAEImproved_v10.safetensors", "FLUXVAE"),
    # exactly what the downloaded workflow.json contains: U+2011 non-breaking
    # hyphens instead of "-", which ComfyUI itself cannot resolve
    ("vae", "vae\u2011ft\u2011mse\u2011840000\u2011ema\u2011pruned.safetensors", "SDVAE"),
    # ---- embeddings --------------------------------------------------
    ("embeddings", "EasyNegative.safetensors", "TI_SD15"),
    ("embeddings", "EasyNegativeV2.safetensors", "TI_SD15"),
    ("embeddings", "ng_deepnegative_v1_75t.safetensors", "TI_SD15"),
    ("embeddings", "deep_negative_pony.safetensors", "TI_SDXL"),
    ("embeddings", "badhandv4.pt", "TI_SD15"),
    ("embeddings", "NegfeetV2.pt", "TI_SD15*"),
    # ---- neutral kinds ----------------------------------------------
    ("upscale_models", "RealESRGAN_x4plus.pth", "UNIVERSAL"),
    ("sams", "sam_vit_b_01ec64.pth", "UNIVERSAL"),
]

fail = 0
print("=" * 86)
print("A. per-file architecture detection")
print("=" * 86)
for kind, name, want in CASES:
    got, reason = mc.detect_arch(kind, name)
    if want.endswith("*"):
        ok = mc.arch_family(got) == mc.arch_family(want.rstrip("*"))
    else:
        ok = got == want
    fail += 0 if ok else 1
    print("%-4s %-15s %-58s %-12s %s" % (
        "OK" if ok else "FAIL", kind, name[:58], got, "" if ok else "want " + want))

# ---------------------------------------------------------------------
# The real workflow: workflow.json -- SD1.5 base + a Krea2/SDXL LoRA stack.
# ---------------------------------------------------------------------
PICKS = {
    "checkpoints": ["majicmixRealistic_v7.safetensors"],
    "vae": ["vae-ft-mse-840000-ema-pruned.safetensors"],
    "loras": [
        "写实\\snofs_krea_v1_4文件超级大.safetensors",
        "privet-part.safetensors",
        "add-detail-xl.safetensors",
        "写实\\ass_v2_krea2_loraholic.safetensors",
        "写实\\breast_size_v2_krea2_loraholic.safetensors",
        "写实\\PROFESSIONAL_PORNOGRAPHIC_PHOTOSHOOT4摄影模型.safetensors",
        "写实\\TeeKaysTittyTime_SkiSlopeTiddies_SteepSlopeTiddies_XXL_Kr2胸部.safetensors",
    ],
    "embeddings": [
        "deep_negative_pony.safetensors", "EasyNegative.safetensors",
        "EasyNegativeV2.safetensors", "badhandv4.pt",
        "ng_deepnegative_v1_75t.pt",
    ],
}

print()
print("=" * 86)
print("B. workflow-level check (base = SD1.5 majicmix, stack mixes Krea2/SDXL)")
print("=" * 86)

res = mc.check("loras", mc.list_models("loras").get("loras", []), PICKS)
ref = res["reference"] or {}
print("LoRA picker  -> ref=%s from %s | counts=%s" % (ref.get("label"), ref.get("source_name"), res["counts"]))
for name, want in [("add-detail-xl.safetensors", "conflict"),
                   ("privet-part.safetensors", "conflict"),
                   ("Kittew-4RCH0N.safetensors", "conflict"),
                   ("约尔4V.safetensors", "ok"),
                   ("写实\\snofs_krea_v1_4文件超级大.safetensors", "conflict")]:
    it = pick(res["items"], name) or {}
    flag = "OK" if it.get("state") == want else "FAIL"
    fail += 0 if flag == "OK" else 1
    print("  %-4s %-9s %-8s %s" % (flag, it.get("state"), it.get("short"), it.get("why")))

res = mc.check("vae", mc.list_models("vae").get("vae", []), PICKS)
ref = res["reference"] or {}
print("\nVAE picker   -> ref=%s | counts=%s" % (ref.get("label"), res["counts"]))
for name, want in [("ultrafluxVAEImproved_v10.safetensors", "conflict"),
                   ("color101VAE_v1.safetensors", "ok"),
                   ("sd1.5\\vae-ft-mse-840000-ema-pruned.safetensors", "ok"),
                   ("anythingModelVAEV40_v10.pt", "ok")]:
    it = pick(res["items"], name) or {}
    flag = "OK" if it.get("state") == want else "FAIL"
    fail += 0 if flag == "OK" else 1
    print("  %-4s %-9s %-9s %-30s %s" % (flag, it.get("state"), it.get("short"), name, it.get("why")))

res = mc.check("embeddings", mc.list_models("embeddings").get("embeddings", []), PICKS)
ref = res["reference"] or {}
print("\nEmbedding    -> ref=%s | counts=%s" % (ref.get("label"), res["counts"]))
for name, want in [("deep_negative_pony.safetensors", "conflict"),
                   ("EasyNegative.safetensors", "ok"),
                   ("badhandv4.pt", "ok")]:
    it = pick(res["items"], name) or {}
    flag = "OK" if it.get("state") == want else "FAIL"
    fail += 0 if flag == "OK" else 1
    print("  %-4s %-9s %-9s %-30s %s" % (flag, it.get("state"), it.get("short"), name, it.get("why")))

# checkpoint picker: the graph contains Krea2 + SDXL LoRAs, so an SD1.5
# checkpoint is the one that serves nobody and must come out red.
res = mc.check("checkpoints", mc.list_models("checkpoints").get("checkpoints", []), PICKS)
ref = res["reference"] or {}
print("\nCheckpoint   -> ref=%s families=%s | counts=%s" % (ref.get("label"), ref.get("families"), res["counts"]))
for name, want in [("majicmixRealistic_v7.safetensors", "conflict"),
                   ("hassakuXLIllustrious_v13StyleA.safetensors", "ok"),
                   ("ponyDiffusionV6XL_v6StartWithThisOne.safetensors", "ok")]:
    it = pick(res["items"], name) or {}
    flag = "OK" if it.get("state") == want else "FAIL"
    fail += 0 if flag == "OK" else 1
    print("  %-4s %-9s %-9s %-30s %s" % (flag, it.get("state"), it.get("short"), name, it.get("why")))
print("  graph histogram:", mc.graph_families(PICKS))

print()
print("FAILURES:", fail)
sys.exit(1 if fail else 0)
