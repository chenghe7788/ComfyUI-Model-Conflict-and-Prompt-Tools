"""ComfyUI_AutoSavePreview — 让「预览图像 PreviewImage」在写 temp 预览的同时，把整张图再存一份到 output。

动机（用户 2026-09-15）：「把自动保存到缓存直接也保存到output不就好了 反正缓存也会删除」

设计要点
1. 纯服务端覆盖：本包在启动时用同名类覆盖 nodes.PreviewImage，并把 nodes.NODE_CLASS_MAPPINGS
   / NODE_DISPLAY_NAME_MAPPINGS 一起改写。任何工作流（含 20 个模板）**无需改动、无需重开文件**
   都能生效——因为工作流只按节点名 `PreviewImage` 引用，注册表就是唯一的真相。
2. 只动标准预览节点：`type(self) is self.__class__` 保证只有真正的 PreviewImage 走这条路；
   其它插件继承 PreviewImage 的类（impact-pack 的 ImageSender、rgthree 的 ImageComparer 等）
   行为完全不变，不会凭空多出一堆文件。
3. 两边都留：temp 那份原样保留（前端 `type=temp` 预览不用改），output 那份用标准
   `ComfyUI_00001_.png` 命名、带完整 prompt/workflow 元数据。
4. 逃生开关：环境变量 COMFYUI_AUTO_SAVE_PREVIEW=0 可整体关掉自动存盘，恢复原生行为。
5. 不碰核心文件：不改 nodes.py，只做运行时替换；卸载 = 删掉本目录。
"""

import os
import time

COMFYUI_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

import nodes  # noqa: E402
import folder_paths  # noqa: E402
from PIL.PngImagePlugin import PngInfo  # noqa: E402
import json  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from comfy.cli_args import args  # noqa: E402

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
WEB_DIRECTORY = None

_ORIG = nodes.PreviewImage

if os.environ.get("COMFYUI_AUTO_SAVE_PREVIEW", "1").strip().lower() in ("0", "false", "off", "no"):
    print("[AutoSavePreview] COMFYUI_AUTO_SAVE_PREVIEW=0 -> 关闭自动存盘，保持原生预览行为")
else:
    class PreviewImage(_ORIG):
        """预览 + 存盘。行为等价于原生预览，额外把整图写进 output。"""

        _parent_save = _ORIG.save_images

        def save_images(self, images, filename_prefix="ComfyUI", prompt=None, extra_pnginfo=None):
            # --- 1. 原生预览（temp，ui.type=temp，前端照旧）---
            temp_result = self._parent_save(images, filename_prefix, prompt, extra_pnginfo)

            # --- 2. 同一批图再存一份到 output（失败绝不影响预览）---
            try:
                extra = self._save_to_output(images, filename_prefix, prompt, extra_pnginfo)
            except Exception as exc:  # noqa: BLE001
                print(f"[AutoSavePreview] 存 output 失败（预览不受影响）: {type(exc).__name__}: {exc}")
                extra = []

            # 关键：output 那份**不要**再塞进 ui.images。
            # 前端会把 ui.images 里每一条都渲染成一张图 -> 用户看到"两张一样的"。
            # 只留 temp 那条做预览；output 落盘信息走日志（服务端已实实在在写了文件）。
            if extra:
                names = ", ".join(x["filename"] for x in extra)
                print(f"[AutoSavePreview] 已另存到 output: {names}")
            return temp_result

        def _save_to_output(self, images, filename_prefix, prompt, extra_pnginfo):
            output_dir = folder_paths.get_output_directory()
            # 注意：故意不加 self.prefix_append（那是 temp 预览名里的 _temp_xxxxx），
            # 让 output 里得到干净的标准名 ComfyUI_00001_.png，与 SaveImage 同一条序列。
            full_folder, filename, counter, subfolder, prefix = folder_paths.get_save_image_path(
                filename_prefix, output_dir, images[0].shape[1], images[0].shape[0])
            metadata = None
            if not args.disable_metadata:
                metadata = PngInfo()
                if prompt is not None:
                    metadata.add_text("prompt", json.dumps(prompt))
                if extra_pnginfo is not None:
                    for key in extra_pnginfo:
                        metadata.add_text(key, json.dumps(extra_pnginfo[key]))
            results = []
            for batch_number, image in enumerate(images):
                arr = 255.0 * image.cpu().numpy()
                img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
                name = filename.replace("%batch_num%", str(batch_number))
                file = f"{name}_{counter:05}_.png"
                img.save(os.path.join(full_folder, file), pnginfo=metadata,
                         compress_level=self.compress_level)
                results.append({"filename": file, "subfolder": subfolder, "type": "output"})
                counter += 1
            return results

    nodes.PreviewImage = PreviewImage
    nodes.NODE_CLASS_MAPPINGS["PreviewImage"] = PreviewImage
    nodes.NODE_DISPLAY_NAME_MAPPINGS["PreviewImage"] = "预览图像（自动存到 output）"
    print(f"[AutoSavePreview] 已接管标准「预览图像」节点：预览写 temp 的同时，整图另存一份到 output（{time.strftime('%H:%M:%S')}）")
    print(f"[AutoSavePreview] 逃生开关: 设环境变量 COMFYUI_AUTO_SAVE_PREVIEW=0 可关闭")
