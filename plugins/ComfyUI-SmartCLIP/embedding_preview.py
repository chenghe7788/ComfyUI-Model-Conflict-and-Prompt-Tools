# -*- coding: utf-8 -*-
"""
SmartCLIP 词嵌入预览 API
=======================
嵌入弹窗（web/js/embedding_picker.js）与「选择提示词」弹窗共用的一层数据：

  GET /smart_clip/embeddings?family=sdxl
      -> {"total": N, "withPreview": M, "family": "sdxl",
          "familySource": "client" | "workflow" | "none",
          "familyRequested": "sdxl",
          "states": {"ok": 3, "incompatible": 1, ...},
          "items": [{"name": "EasyNegative", "hasPreview": false,
                     "preview": true,
                     "compat": {"state": "ok", "short": "SDXL",
                                "why": "与当前 SDXL 兼容（SDXL）"}}, ...]}
      ``family`` 是判定时真正用的底模族，``familySource`` 说明它从哪来：
      客户端（弹窗自己的识别结果）> 工作流（服务端从 ComfyUI 最近一次跑的
      图里认出来的底模，见 workflow_model.py）> 谁都不知道。
      ``compat`` 字段直接来自 embedding_compat 的同一套判定 —— 与提示词
      弹窗里那个徽标完全同源，不再各写一套。

      兜底为什么存在：前端要沿 CLIP 连线回溯到加载器才能认出底模，而
      连线中间隔一个 LoRA 堆叠节点、页面在 ComfyUI 还没启动完时加载、
      或者浏览器拿着旧缓存，都会让前端只能报 generic —— 那样每个词嵌入
      都只剩「未知」，弹窗等于没标注。前端说不出话时改由服务端回答。

  GET /smart_clip/embeddings/img?name=EasyNegative
      -> 同名侧车预览图（png/webp/jpg/jpeg/jfif/gif），没有则 404。

为什么必须有这一层
------------------
合并前 ComfyUI_EmbeddingHelper 自带一套（/embeddinghelper/list、/img），
ComfyUI_SmartCLIP 的弹窗又自己算一遍兼容性。同一个 embedding 的
「装没装 / 能不能用」在两个文件里各判一次，是这个插件包被拆成两份的
根本原因。现在文件解析统一走 embedding_compat.resolve()（支持子目录、
裸名、缺扩展名），图片只按解析出来的路径找同名侧车图。

安全：请求的名字必须先解析成 embedding_compat 索引里的真实文件，
所以路径穿越到 embeddings 目录之外是不可能的。

Keep this file ASCII-only.
"""

import logging
import os
import os.path as osp

try:                       # ComfyUI 里按包导入
    from . import embedding_compat as compat
    from . import workflow_model
except ImportError:        # 独立导入（测试 / 工具）
    import embedding_compat as compat
    import workflow_model

try:
    from aiohttp import web
except Exception:          # pragma: no cover
    web = None

log = logging.getLogger(__name__)

# 侧车预览图的后缀组合："<name>.png" 与 "<name>.preview.png" 都有人用。
PREVIEW_SUFFIXES = ("", ".preview")
PREVIEW_EXTS = (".png", ".webp", ".jpg", ".jpeg", ".jfif", ".gif")

_MIME = {
    ".png": "image/png",
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".jfif": "image/jpeg",
    ".gif": "image/gif",
}


def image_path(name):
    """解析出的 embedding 文件路径；解析不到返回 ``None``。"""
    return compat.resolve(name)


def preview_path(name):
    """
    某个 embedding 的预览图绝对路径，没有则 ``None``。

    ``name`` 允许写裸名或 ``embedding:名前缀`` 的裸名；文件名先用
    embedding_compat.resolve() 定案，再在它旁边找同名侧车图 —— 这样
    「图片找不到」永远只意味着「图没放」，不会变成「模型名和文件名对不上」。
    """
    path = image_path(name)
    if not path:
        return None
    folder = osp.dirname(path)
    stem = osp.basename(path)
    if stem.lower().endswith(compat._EXTENSIONS):
        stem = osp.splitext(stem)[0]
    for suffix in PREVIEW_SUFFIXES:
        for ext in PREVIEW_EXTS:
            candidate = osp.join(folder, stem + suffix + ext)
            if osp.isfile(candidate):
                return candidate
        # 有些下载器把大小写改了（.PNG / .Png）。
        try:
            entries = os.listdir(folder)
        except OSError:
            entries = []
        wanted = (stem + suffix).lower()
        for entry in entries:
            base, ext = osp.splitext(entry)
            if base.lower() == wanted and ext.lower() in PREVIEW_EXTS:
                return osp.join(folder, entry)
    return None


def _display_names(index):
    """
    索引里的文件名 -> 提示词里写的显示名（去扩展名、去重）。

    直接从 embedding_index() 的键推导，而不是另外问一次 folder_paths：
    列表里出现的每个名字，resolve() 都一定能解析回同一个文件。
    """
    names = []
    seen = set()
    for key in index:
        base, ext = osp.splitext(key)
        if ext.lower() not in compat._EXTENSIONS:
            continue
        if base in seen:
            continue
        seen.add(base)
        names.append(base)
    return names


def list_embeddings(family=""):
    """
    弹窗要的全部数据：名字、有没有图、以及兼容判定。已按名字排序。

    名字来自 embedding_compat.embedding_index()，与 resolve()/annotate()
    用的是同一份索引 —— 列表里点得动的名字，判定和插图一定找得到。

    ``family`` 是前端自己认出来的底模族。``""`` / ``"generic"`` / ``"unknown"``
    都表示「前端说不出话」，这时用服务端从 ComfyUI 最近一张图里认出来的底模
    （workflow_model.resolve_preset）—— 否则每个条目都会退化成「未知」，
    与提示词弹窗的徽标也就无从对齐。
    """
    index = compat.embedding_index()
    requested = str(family or "").strip().lower()
    preset, source = workflow_model.resolve_preset(requested)

    items = []
    for name in sorted(_display_names(index), key=lambda n: n.lower()):
        has_image = preview_path(name) is not None
        entry = {
            "name": name,
            "hasPreview": has_image,
            "preview": True,          # 前端用它区分「无图」是占位还是服务不可用
        }
        try:
            entry["compat"] = compat.annotate("embedding:" + name, preset)
        except Exception as exc:          # 单个条目失败不影响列表
            log.warning("[SmartCLIP] compat failed for %s: %s", name, exc)
        items.append(entry)

    states = {}
    for entry in items:
        state = (entry.get("compat") or {}).get("state")
        if state:
            states[state] = states.get(state, 0) + 1

    return {
        "items": items,
        "total": len(items),
        "withPreview": sum(1 for i in items if i["hasPreview"]),
        "family": preset or "generic",
        "familyRequested": requested,
        "familySource": source,
        "states": states,
    }


def register_routes(routes):
    """
    把两个只读接口挂到 PromptServer.routes 上。

    ``routes`` 由 smart_clip_api.register_routes() 传入，注册时机与
    /smart_clip/* 其余路由保持一致（custom_nodes 加载完、add_routes 之前）。
    """
    if web is None:
        log.warning("[SmartCLIP] aiohttp unavailable, embedding routes skipped")
        return False

    @routes.get("/smart_clip/embeddings")
    async def smart_clip_embeddings(request):
        family = request.rel_url.query.get("family", "")
        try:
            data = list_embeddings(family)
        except Exception as exc:
            log.warning("[SmartCLIP] embedding list failed: %s", exc)
            return web.json_response({"error": str(exc)[:200], "items": []}, status=500)
        return web.json_response(data)

    @routes.get("/smart_clip/embeddings/img")
    async def smart_clip_embeddings_img(request):
        name = request.rel_url.query.get("name", "")
        if not name:
            return web.Response(status=400)
        path = preview_path(name)
        if path is None:
            return web.Response(status=404)
        return web.FileResponse(path, headers={
            "Content-Type": _MIME.get(osp.splitext(path)[1].lower(),
                                       "application/octet-stream"),
            "Cache-Control": "public, max-age=86400",
        })

    log.info("[SmartCLIP] embedding routes registered: "
             "/smart_clip/embeddings, /smart_clip/embeddings/img")
    return True
