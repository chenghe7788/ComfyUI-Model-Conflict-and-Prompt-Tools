# -*- coding: utf-8 -*-
"""
Which third-party modules does each pack really need at import time?

requirements.txt is not a safe guide here: LivePortraitKJ pins numpy<=1.26.4,
TripoSR-ZHO pins Pillow==10.1.0 / transformers==4.35.0.  Blindly running
`pip install -r` would DOWNGRADE libraries the rest of ComfyUI depends on.

So: scan the pack's own sources for top-level imports, drop stdlib / local files
/ ComfyUI's own modules, and test each remaining module with find_spec.
The output is the minimal, verified dependency list per pack.
"""

import ast
import importlib.util
import os
import sys

NODES = r"C:\ComfyUI_windows_portable\ComfyUI\custom_nodes"
PACKS = ["ComfyUI-LivePortraitKJ", "ComfyUI-Gemini", "ComfyUI-Qwen",
         "ComfyUI-Flowty-TripoSR-ZHO", "ComfyUI-VideoHelperSuite", "ComfyUI-ArtGallery"]

# modules provided by ComfyUI itself or by this pack, not pip packages
COMFY_MODULES = {
    "comfy", "comfy_extras", "nodes", "folder_paths", "node_helpers", "server",
    "model_management", "utils", "execution", "latent_preview", "comfy_api",
    "comfy_execution", "cli_args", "app", "protocol", "comfy_config",
}
# module name -> pip package (when they differ)
PIP_NAME = {
    "PIL": "Pillow", "cv2": "opencv-python", "yaml": "pyyaml", "skimage": "scikit-image",
    "sklearn": "scikit-learn", "google": "google-generativeai", "onnxruntime": "onnxruntime-gpu",
    "torchmcubes": "git+https://github.com/tatsy/torchmcubes.git", "imageio_ffmpeg": "imageio-ffmpeg",
    "numpy": "numpy", "rembg": "rembg", "trimesh": "trimesh", "omegaconf": "omegaconf",
    "einops": "einops", "modelscope": "modelscope", "transformers": "transformers",
    "accelerate": "accelerate", "huggingface_hub": "huggingface-hub", "mediapipe": "mediapipe",
    "onnx2torch": "onnx2torch", "pykalman": "pykalman", "fvcore": "fvcore", "ftfy": "ftfy",
    "addict": "addict", "yacs": "yacs", "albatross": "albatross", "albumentations": "albumentations",
    "dateutil": "python-dateutil", "filelock": "filelock", "scipy": "scipy", "matplotlib": "matplotlib",
}


def local_modules(pack_dir):
    names = set()
    for root, _dirs, files in os.walk(pack_dir):
        for fn in files:
            if fn.endswith(".py"):
                names.add(fn[:-3])
        for d in os.listdir(root):
            if os.path.isdir(os.path.join(root, d)) and os.path.isfile(os.path.join(root, d, "__init__.py")):
                names.add(d)
    return names


def scan_imports(pack_dir):
    found = set()
    for root, _dirs, files in os.walk(pack_dir):
        if "node_modules" in root or ".git" in root:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            try:
                tree = ast.parse(open(os.path.join(root, fn), "r", encoding="utf-8", errors="replace").read())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        found.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.level == 0 and node.module:
                        found.add(node.module.split(".")[0])
    return found


stdlib = set(sys.stdlib_module_names)
all_missing = {}
for pack in PACKS:
    pack_dir = os.path.join(NODES, pack)
    if not os.path.isdir(pack_dir):
        print("%-30s MISSING ON DISK" % pack)
        continue
    local = local_modules(pack_dir)
    imports = scan_imports(pack_dir)
    third_party = sorted(m for m in imports
                         if m not in stdlib and m not in local and m not in COMFY_MODULES)
    missing = []
    for mod in third_party:
        try:
            present = importlib.util.find_spec(mod) is not None
        except (ImportError, ValueError):
            present = False
        if not present:
            missing.append(mod)
    all_missing[pack] = missing
    print("%-30s 第三方依赖 %2d 个, 缺 %d 个" % (pack, len(third_party), len(missing)))
    if missing:
        print("      缺失模块   : %s" % ", ".join(missing))
        print("      pip 安装名 : %s" % " ".join(PIP_NAME.get(m, m) for m in missing))

print()
print("=== 需要在你那侧执行的最小 pip 安装（不含任何降级/换 torch 的固定版本）===")
seen = []
for pack, missing in all_missing.items():
    if not missing:
        continue
    pkgs = [PIP_NAME.get(m, m) for m in missing]
    line = " ".join(p for p in pkgs if not p.startswith("torch"))
    if line:
        print("  # %s" % pack)
        print("  pip install %s" % line)
        seen.extend(pkgs)
print()
print("（注意：LivePortraitKJ 的 requirements 里 numpy<=1.26.4、TripoSR-ZHO 的 Pillow==10.1.0 /")
print("  transformers==4.35.0 / torchmcubes(git) 都会改动共享库或需要编译，本清单刻意不含它们）")
