# -*- coding: utf-8 -*-
"""
SmartCLIP HTTP API
==================
Routes used by web/js/*.js:

  GET  /smart_clip/presets?model=sdxl&role=positive
       -> {"model","role","categories":{...},"source","models","roles",
           "shared":[...],"annotations":{...},"embedding_stats":{...}}
          "shared" = 用户自建（全局）分类名：它们不属于任何模型族，所有弹窗都显示，
          见 presets.SHARED_MODEL（_shared 段）。

  POST /smart_clip/presets/save
       body {"model","role","category","text"}
       -> {"ok":true,"duplicate":false,"category","count","backup",...}
          (the dialog's "入库" button; writes prompt_presets/presets.json)

  POST /smart_clip/classify
       body {"text":"masterpiece, 1girl, long hair, red dress, forest"}
       -> {"tags":[{"text","category"}...],"counts":{...},"total":N,...}
          (dry run: splits a prompt and says where each tag belongs)

  POST /smart_clip/presets/save_many
       body {"model","role","entries":[{"category","text"}...]}
         or {"model","role","text":"..."}   (classified server-side first)
       -> {"ok":true,"added":N,"duplicates":M,"categories":{...},"skipped":[...]}
          (one backup, one atomic write for the whole batch)

  GET  /smart_clip/text?model=&role=&category=
       -> the joined text of one category (copy/paste friendly)

  GET  /smart_clip/detect?names=a.safetensors|b.safetensors&kind=checkpoints
       -> per-file architecture, so the dialog can pick the right word list
          *before* the node has ever executed

  GET  /smart_clip/info
       -> node version, preset file location, available models

  POST /smart_clip/reload
       -> drop the preset + file caches

  GET  /smart_clip/embeddings?family=sdxl
       -> 词嵌入弹窗的数据：名字 + 有没有预览图 + 兼容判定
          （合并自原 ComfyUI_EmbeddingHelper 的 /embeddinghelper/list，
           判定与提示词弹窗的徽标同源，见 embedding_preview.py）

  GET  /smart_clip/embeddings/img?name=EasyNegative
       -> 该词嵌入的侧车预览图，没有则 404
          （合并自原 /embeddinghelper/img）

Registration is explicit and idempotent: the draft this replaces used
``@PromptServer.instance.routes.get`` at import time, which raises
AttributeError when the server instance does not exist yet, and raises
"Added route will never be executed" if the module is ever imported twice.
"""

import json
import logging
import os

try:                       # normal case: loaded as a package by ComfyUI
    from . import classify, embedding_preview, model_detector, presets, workflow_model
except ImportError:        # standalone import (tests / tooling)
    import classify
    import embedding_preview
    import model_detector
    import presets
    import workflow_model

try:
    from aiohttp import web
except Exception:          # pragma: no cover
    web = None

log = logging.getLogger(__name__)

VERSION = "0.1.0"
_REGISTERED = False


def _plugin_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _clean_names(raw, limit=24):
    if isinstance(raw, str):
        raw = [part for part in raw.replace("\n", "|").split("|")]
    if not isinstance(raw, (list, tuple)):
        return []
    out = []
    for item in raw[:limit]:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def _split_names(raw, limit=24):
    """Accept both "a|b" and ["a", "b"] (the query string form uses '|')."""
    return _clean_names(raw, limit)


def _payload():
    """Everything the UI needs to describe itself, in one round trip."""
    return {
        "version": VERSION,
        "plugin_dir": _plugin_dir(),
        "families": {key: value for key, value in model_detector.FAMILY_INFO.items()},
        "presets": presets.info(),
        # Which base model the server can prove from ComfyUI's own queue /
        # history - the fallback the embedding verdicts use when the frontend
        # cannot identify one (see workflow_model.py).
        "workflow": workflow_model.info(),
    }


def register_routes():
    """Attach the routes to the running PromptServer. Safe to call more than once."""
    global _REGISTERED
    if web is None:
        log.warning("[SmartCLIP] aiohttp unavailable, routes not registered")
        return False
    try:
        from server import PromptServer
    except Exception as exc:
        log.warning("[SmartCLIP] cannot reach PromptServer: %s", exc)
        return False

    routes = getattr(PromptServer.instance, "routes", None)
    if routes is None:
        log.warning("[SmartCLIP] PromptServer.instance.routes unavailable")
        return False

    if _REGISTERED:
        return True

    # Refuse to double-register.  Custom node routes are declared on a
    # RouteTableDef that main.py materialises into the app *after* custom nodes
    # load (main.py: init_extra_nodes() then add_routes()), so the decorator form
    # below is the mechanism that actually works; adding to the router directly
    # is impossible in aiohttp 3.13 (RouteTableDef has no .router).
    def _already(path):
        for item in getattr(routes, "_items", None) or []:
            if getattr(item, "path", None) == path:
                return True
        return False

    if _already("/smart_clip/presets"):
        _REGISTERED = True
        log.info("[SmartCLIP] routes already declared, nothing to do")
        return True

    # ---- presets -----------------------------------------------------
    @routes.get("/smart_clip/presets")
    async def smart_clip_presets(request):
        model = request.rel_url.query.get("model", "generic")
        role = request.rel_url.query.get("role", "positive")
        try:
            # The word list stays whatever the dialog asked for; only the
            # textual-inversion verdicts get the family the server can prove
            # (ComfyUI's last run) when the frontend could not identify one.
            verdict, _source = workflow_model.resolve_preset(model)
            data = presets.load(model, role, verdict_model=verdict)
        except Exception as exc:
            log.warning("[SmartCLIP] presets failed: %s", exc)
            return web.json_response({"error": str(exc)[:200], "categories": {}}, status=500)
        return web.json_response(data)

    @routes.get("/smart_clip/text")
    async def smart_clip_text(request):
        model = request.rel_url.query.get("model", "generic")
        role = request.rel_url.query.get("role", "positive")
        category = request.rel_url.query.get("category", "")
        return web.json_response(presets.text_for(model, role, category))

    # ---- write back: the dialog's "入库" button ------------------------
    @routes.post("/smart_clip/presets/save")
    async def smart_clip_presets_save(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "请求体必须是 JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "请求体必须是 JSON 对象"}, status=400)
        try:
            report = presets.add_entry(
                body.get("model"), body.get("role"), body.get("category"), body.get("text"))
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:                      # disk full, permissions, ...
            log.warning("[SmartCLIP] presets save failed: %s", exc)
            return web.json_response(
                {"ok": False, "error": "写入词库失败：%s" % type(exc).__name__}, status=500)
        return web.json_response(report)

    # ---- split a prompt and say where each tag belongs (no write) -------
    @routes.post("/smart_clip/classify")
    async def smart_clip_classify(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "请求体必须是 JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "请求体必须是 JSON 对象"}, status=400)
        try:
            result = classify.plan(body.get("text"), body.get("model"))
        except Exception as exc:
            log.warning("[SmartCLIP] classify failed: %s", exc)
            return web.json_response(
                {"ok": False, "error": "分类失败：%s" % type(exc).__name__}, status=500)
        result["ok"] = True
        return web.json_response(result)

    # ---- save a whole classified batch in one write --------------------
    @routes.post("/smart_clip/presets/save_many")
    async def smart_clip_presets_save_many(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "请求体必须是 JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "请求体必须是 JSON 对象"}, status=400)

        entries = body.get("entries")
        if not isinstance(entries, list) or not entries:
            # No explicit plan: classify the raw text here, so a script can post
            # just {"model","role","text"} and get the same result as the dialog.
            text = body.get("text")
            if not text:
                return web.json_response(
                    {"ok": False, "error": "需要 entries 或 text"}, status=400)
            entries = [{"category": item["category"], "text": item["text"]}
                       for item in classify.plan(text, body.get("model"))["tags"]]
            if not entries:
                return web.json_response({"ok": False, "error": "没有可入库的词条"}, status=400)

        try:
            report = presets.add_entries(body.get("model"), body.get("role"), entries)
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            log.warning("[SmartCLIP] presets save_many failed: %s", exc)
            return web.json_response(
                {"ok": False, "error": "写入词库失败：%s" % type(exc).__name__}, status=500)
        return web.json_response(report)

    # ---- pre-execution model detection -------------------------------
    @routes.get("/smart_clip/detect")
    async def smart_clip_detect(request):
        names = _split_names(request.rel_url.query.get("names", ""))
        kind = request.rel_url.query.get("kind", "checkpoints")
        if not names:
            return web.json_response({"items": [], "error": "no names"}, status=400)
        items = []
        for name in names:
            try:
                items.append(model_detector.detect_checkpoint(kind, name))
            except Exception as exc:
                items.append({"name": name, "family": "unknown",
                              "evidence": "detect failed: %s" % type(exc).__name__})
        return web.json_response({"kind": kind, "items": items})

    # ---- misc --------------------------------------------------------
    @routes.get("/smart_clip/info")
    async def smart_clip_info(request):
        return web.json_response(_payload())

    @routes.post("/smart_clip/reload")
    async def smart_clip_reload(request):
        presets.clear_cache()
        model_detector.clear_cache()
        return web.json_response({"ok": True, "presets": presets.info()})

    # ---- 词嵌入弹窗（原 ComfyUI_EmbeddingHelper 的接口，已并入本插件） ----
    # 与 /smart_clip/* 共用同一个 routes 表，因此注册时机完全一致；
    # 解析/兼容判定统一走 embedding_compat，不再有第二套列表实现。
    try:
        embedding_preview.register_routes(routes)
    except Exception as exc:
        log.warning("[SmartCLIP] embedding routes failed: %s", exc)

    # ---- 删除 / 重命名 / 新建分类 -------------------------------------
    # Every @routes.* decorator below must be reached BEFORE the `return True`
    # at the very bottom of this function.  The 2026-09-16 patch appended these
    # four routes *after* that return, so they were dead code: the dialog's
    # 删除分类 / 重命名分类 / 删除词条 always hit HTTP 405 from the running
    # server even though the handlers looked present in the source.
    # ---- 删除词条 ----
    @routes.post("/smart_clip/presets/delete")
    async def smart_clip_presets_delete(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "请求体必须是JSON"}, status=400)
        try:
            report = presets.delete_entry(
                body.get("model"), body.get("role"), body.get("category"), body.get("text"))
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            log.warning("[SmartCLIP] delete entry failed: %s", exc)
            return web.json_response({"ok": False, "error": "删除失败：%s" % type(exc).__name__}, status=500)
        return web.json_response(report)

    # ---- 重命名分类 ----
    @routes.post("/smart_clip/presets/rename_category")
    async def smart_clip_presets_rename_category(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "请求体必须是JSON"}, status=400)
        try:
            report = presets.rename_category(
                body.get("model"), body.get("role"), body.get("old"), body.get("new"))
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            log.warning("[SmartCLIP] rename category failed: %s", exc)
            return web.json_response({"ok": False, "error": "重命名失败：%s" % type(exc).__name__}, status=500)
        return web.json_response(report)

    # ---- 删除分类 ----
    @routes.post("/smart_clip/presets/delete_category")
    async def smart_clip_presets_delete_category(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "请求体必须是JSON"}, status=400)
        try:
            report = presets.delete_category(
                body.get("model"), body.get("role"), body.get("category"))
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            log.warning("[SmartCLIP] delete category failed: %s", exc)
            return web.json_response({"ok": False, "error": "删除分类失败：%s" % type(exc).__name__}, status=500)
        return web.json_response(report)

    # ---- 新建分类 ----
    # Creating the (empty) category on disk is what makes the dialog's
    # "+ 新建分类" row show up immediately - and therefore what makes it
    # renamable/deletable.  Without it the name only lived in the input box
    # and had no row to right-click.
    @routes.post("/smart_clip/presets/create_category")
    async def smart_clip_presets_create_category(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "请求体必须是JSON"}, status=400)
        try:
            report = presets.create_category(
                body.get("model"), body.get("role"), body.get("category"))
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            log.warning("[SmartCLIP] create category failed: %s", exc)
            return web.json_response({"ok": False, "error": "新建分类失败：%s" % type(exc).__name__}, status=500)
        return web.json_response(report)

    _REGISTERED = True
    log.info("[SmartCLIP] routes registered: /smart_clip/presets (+/save, +/save_many, "
             "+/delete, +/delete_category, +/rename_category, +/create_category), "
             "/smart_clip/classify, /smart_clip/text, /smart_clip/detect, /smart_clip/info, "
             "/smart_clip/reload, /smart_clip/embeddings (+/img)")
    return True
