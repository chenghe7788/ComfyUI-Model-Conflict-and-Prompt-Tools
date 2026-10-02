# -*- coding: utf-8 -*-
"""
Probe: what can actually be written in a prompt on this machine?

    C:\\ComfyUI_windows_portable\\python_embeded\\python.exe tests\\probe_prompt_syntax.py

Runs the real ComfyUI tokenizer (``comfy.sd1_clip.SDTokenizer``) over a handful of
prompt strings and prints the token groups it produces. It answers two questions
the UI depends on:

  * ``embedding:NAME`` -> real 768-d embedding tensors (works)
  * bare ``name``      -> plain word tokens (silently useless)
  * ``(embedding:NAME:0.8)`` -> embedding tensors carrying weight 0.8 (works)
  * ``<lora:NAME:0.8>`` -> plain word tokens, i.e. ComfyUI has NO lora-in-prompt
    syntax: the tag ends up as literal text in the prompt.

Needs the ComfyUI checkout (not the plugin) on sys.path; SMARTCLIP_COMFYUI
overrides the default path. Read-only: nothing is loaded from disk except the
tokenizer files and the embedding files named below.
"""

import os
import sys

DEFAULT_COMFY = r"C:\ComfyUI_windows_portable\ComfyUI"
COMFY = os.environ.get("SMARTCLIP_COMFYUI", DEFAULT_COMFY)
if not os.path.isdir(os.path.join(COMFY, "comfy")):
    raise SystemExit("cannot find a ComfyUI checkout at %s (set SMARTCLIP_COMFYUI)" % COMFY)
sys.path.insert(0, COMFY)

EMBEDDINGS = [os.path.join(COMFY, "models", "embeddings")]
if os.environ.get("SMARTCLIP_EMBEDDINGS_DIR"):
    EMBEDDINGS = [os.environ["SMARTCLIP_EMBEDDINGS_DIR"]]

from comfy import sd1_clip          # noqa: E402

CASES = [
    "1girl, embedding:EasyNegative, score_9",
    "1girl, easynegative",
    "(embedding:EasyNegative:0.8), 1girl",
    "1girl, <lora:add_detail:0.8>, score_9",
]

# The embedding used above has to exist, otherwise the case proves nothing.
INSTALLED = sorted(
    n for n in os.listdir(EMBEDDINGS[0])
    if os.path.splitext(n)[1].lower() in (".safetensors", ".pt", ".pth", ".ckpt", ".bin")
) if os.path.isdir(EMBEDDINGS[0]) else []


def describe(group):
    out = []
    for item in group:
        token, weight = item[0], item[1]
        if hasattr(token, "shape"):
            out.append("EMB%s x%s" % (tuple(token.shape), weight))
        else:
            out.append("id(%s)x%s" % (token, weight))
    return out


def main():
    print("=" * 92)
    print("comfy:", COMFY)
    print("embeddings dir:", EMBEDDINGS[0])
    print("installed:", ", ".join(INSTALLED) or "(none)")
    print("=" * 92)
    tokenizer = sd1_clip.SDTokenizer(embedding_directory=EMBEDDINGS)
    for text in CASES:
        print("\nTEXT %r" % text)
        try:
            groups = tokenizer.tokenize_with_weights(text)
        except Exception as exc:                       # noqa: BLE001
            print("   RAISED %s: %s" % (type(exc).__name__, exc))
            continue
        tokens = [t for group in groups for t in group]
        tensors = [t for t in tokens if hasattr(t[0], "shape")]
        print("   %d tokens, %d of them embedding tensors" % (len(tokens), len(tensors)))
        print("   first 8:", describe(tokens[:8]))
    print("\nExpected: case 1 and 3 produce tensors; case 2 has none (bare name is not\n"
          "an embedding); case 4 has none either - <lora:...> is NOT parsed by ComfyUI.")


if __name__ == "__main__":
    main()
