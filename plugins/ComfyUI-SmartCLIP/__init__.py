# -*- coding: utf-8 -*-
"""
ComfyUI SmartCLIP
=================
CLIP 文本编码（智能）：接口与原生 CLIPTextEncode 完全一致，并额外把输入 CLIP 的
架构上报给前端，让「选择提示词」弹窗自动切换到对应的词库
（SD1.5 / SDXL / Pony 评分标签 / Illustrious / SD3 / FLUX）。

本插件同时是「提示词 + 词嵌入」两个弹窗的唯一宿主：
提示词弹窗给出每个 embedding 词条的兼容徽标，嵌入弹窗（图片选择器、
打字补全、撤销插入）直接复用同一套 embedding_compat 判定 —— 两个弹窗
不再各有一份嵌入列表，所以原 ComfyUI_EmbeddingHelper 已并入这里。

Contents
--------
nodes.py                  SmartCLIPTextEncode 节点（原生编码路径 + ui 载荷）
model_detector.py         运行时 CLIP 检测 + 执行前的文件头检测
presets.py                词库加载 / 归一化 / 缓存
embedding_compat.py       词嵌入安装/架构判定（弹窗徽标 + 兼容匹配的唯一来源）
embedding_preview.py      /smart_clip/embeddings 列表与侧车预览图
smart_clip_api.py         /smart_clip/* HTTP 接口（幂等注册）
prompt_presets/presets.json  可编辑词库
web/js/                   前端：提示词弹窗、嵌入弹窗、模型追踪、节点扩展

No third-party Python dependencies: only ComfyUI's own server/aiohttp and the
safetensors package ComfyUI already ships with.
"""

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

# ComfyUI serves this folder at /extensions/ComfyUI_SmartCLIP/
WEB_DIRECTORY = "./web/js"

# Register the HTTP routes used by the frontend.
try:
    from . import smart_clip_api

    smart_clip_api.register_routes()
except Exception as exc:  # pragma: no cover - never block node loading
    print(f"[SmartCLIP] route registration failed: {exc}")

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
