# -*- coding: utf-8 -*-
"""
Probe every pack we intend to install: does the archive exist, which branch,
what does its requirements.txt contain (and does it try to touch torch?).

Run this BEFORE installing so the installer never guesses a URL or silently
reinstalls torch.
"""

import json
import urllib.error
import urllib.request

PACKS = [
    ("ComfyUI-LivePortraitKJ", "kijai/ComfyUI-LivePortraitKJ"),
    ("comfyui_controlnet_aux", "Fannovel16/comfyui_controlnet_aux"),
    ("ComfyUI-BRIA_AI-RMBG", "ZHO-ZHO-ZHO/ComfyUI-BRIA_AI-RMBG"),
    ("ComfyUI-Gemini", "Visionatrix/ComfyUI-Gemini"),
    ("ComfyUI-Gemini (ZHO 原版)", "ZHO-ZHO-ZHO/ComfyUI-Gemini"),
    ("ComfyUI-Qwen", "SXQBW/ComfyUI-Qwen"),
    ("ComfyUI-VideoHelperSuite", "Kosinkadink/ComfyUI-VideoHelperSuite"),
    ("comfyui-portrait-master-zh-cn", "ZHO-ZHO-ZHO/comfyui-portrait-master-zh-cn"),
    ("ComfyUI-ArtGallery", "ZHO-ZHO-ZHO/ComfyUI-ArtGallery"),
    ("rgthree-comfy", "rgthree/rgthree-comfy"),
    ("ComfyUI-Flowty-TripoSR-ZHO", "ZHO-ZHO-ZHO/ComfyUI-Flowty-TripoSR-ZHO"),
    ("ComfyUI-3D-Pack", "MrForExample/ComfyUI-3D-Pack"),
]

UA = {"User-Agent": "Mozilla/5.0 (probe)"}


def head_bytes(url, n=2048, timeout=25):
    """Open a URL and read only the first bytes: proves the archive is really there."""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        chunk = resp.read(n)
        return resp.status, len(chunk), resp.headers.get("Content-Type", "")


def fetch_text(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception:
        return None


rows = []
for title, repo in PACKS:
    branch = None
    size_hint = ""
    for candidate in ("main", "master"):
        url = "https://github.com/%s/archive/refs/heads/%s.zip" % (repo, candidate)
        try:
            status, got, ctype = head_bytes(url)
            branch = candidate
            size_hint = "%d bytes read" % got
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            size_hint = "HTTP %s" % exc.code
        except Exception as exc:
            size_hint = type(exc).__name__

    req_text = None
    for candidate in ([branch] if branch else []) + ["main", "master"]:
        req_text = fetch_text("https://raw.githubusercontent.com/%s/%s/requirements.txt" % (repo, candidate))
        if req_text is not None:
            break

    req_lines = [ln.strip() for ln in (req_text or "").splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
    torch_lines = [ln for ln in req_lines if "torch" in ln.lower()]

    rows.append({
        "title": title,
        "repo": repo,
        "branch": branch,
        "probe": size_hint,
        "requirements": req_lines,
        "touches_torch": torch_lines,
    })
    print("%-30s %-52s branch=%-6s %s" % (title, repo, branch or "??", size_hint))
    if req_lines:
        print("      requirements: %d 条%s" % (len(req_lines), "   ⚠ 含 torch: " + ", ".join(torch_lines) if torch_lines else ""))
    else:
        print("      requirements: 无")

with open("probe_packs.json", "w", encoding="utf-8") as handle:
    json.dump(rows, handle, ensure_ascii=False, indent=2)
print("\nwritten probe_packs.json")
