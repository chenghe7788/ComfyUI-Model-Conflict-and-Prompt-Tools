# -*- coding: utf-8 -*-
"""
Route-registration regression test for SmartCLIP.

WHY THIS EXISTS
---------------
On 2026-09-16 the dialog gained 删除词条 / 重命名分类 / 删除分类, and
``smart_clip_api.py`` got the three handlers appended to the END of the file -
i.e. *after* the ``return True`` that closes ``register_routes()``.  The source
looked complete, but the decorators never executed, so every one of those
requests got HTTP 405 from the running server.  Nothing in the test suite
noticed, because the suite only ever exercised the paths it already knew about.

This test therefore does the only thing that actually proves the point: it
imports the module, hands it a fake ``RouteTableDef``, calls
``register_routes()`` and asserts that every route the frontend uses is really
declared.  Dead code after a ``return`` cannot pass it.

RUN
---
    <ComfyUI>\\python_embeded\\python.exe tests\\test_routes.py

(needs aiohttp, which the embedded interpreter already ships; with plain system
Python the module falls back to ``web = None`` and the test reports SKIP.)
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# SMARTCLIP_SRC lets the test point at a scratch copy - used to prove the test
# really fails on the 2026-09-16 variant (routes after the body-level return).
SRC = os.environ.get("SMARTCLIP_SRC") or os.path.join(os.path.dirname(HERE), "src")
sys.path.insert(0, SRC)

import smart_clip_api  # noqa: E402  (path is set up above)
import presets as ps   # noqa: E402  (same module object smart_clip_api uses)

FAILS = []

# route -> HTTP methods the frontend actually calls (web/js/prompt_dialog.js)
EXPECTED = {
    "/smart_clip/presets": ("GET",),
    "/smart_clip/text": ("GET",),
    "/smart_clip/info": ("GET",),
    "/smart_clip/detect": ("GET",),
    "/smart_clip/embeddings": ("GET",),
    "/smart_clip/embeddings/img": ("GET",),
    "/smart_clip/presets/save": ("POST",),
    "/smart_clip/presets/save_many": ("POST",),
    "/smart_clip/presets/delete": ("POST",),
    "/smart_clip/presets/delete_category": ("POST",),
    "/smart_clip/presets/rename_category": ("POST",),
    "/smart_clip/presets/create_category": ("POST",),
    "/smart_clip/classify": ("POST",),
    "/smart_clip/reload": ("POST",),
}


class FakeRouteTable(object):
    """Mimics aiohttp's RouteTableDef: the decorator registers and returns fn."""

    def __init__(self):
        self.items = []          # (method, path)
        self._items = []         # what register_routes() looks at for "already?"
        self.handlers = {}       # (method, path) -> the async handler itself

    def _register(self, method, path):
        self.items.append((method, path))
        self._items.append(type("R", (), {"path": path})())

        def decorator(handler):
            self.handlers[(method, path)] = handler
            return handler

        return decorator

    def get(self, path):
        return self._register("GET", path)

    def post(self, path):
        return self._register("POST", path)


class FakePromptServer(object):
    instance = None


# ----------------------------------------------------------------------
# 真实调用路由处理器（不启动 ComfyUI、不碰 8188）
# ----------------------------------------------------------------------

class FakeRequest(object):
    def __init__(self, body=None, query=None):
        self._body = body
        self.rel_url = type("RelUrl", (), {"query": dict(query or {})})()

    async def json(self):
        if self._body is None:
            raise ValueError("no json body")
        return self._body


async def _invoke(routes, method, path, body=None, query=None):
    """Call one registered handler the way aiohttp would, return (status, json)."""
    handler = routes.handlers.get((method, path))
    if handler is None:
        return 0, {"error": "handler not registered"}
    response = await handler(FakeRequest(body, query))
    return response.status, json.loads(response.body.decode("utf-8"))


def global_category_flow(routes):
    """「新建的分类在所有的提示词弹窗都能看到」——走真实 HTTP 处理器验一遍。"""
    import asyncio
    import shutil
    import tempfile

    fails = []

    def check(label, got, want):
        ok = got == want
        if not ok:
            fails.append("%s: got %r want %r" % (label, got, want))
        print("  %-4s %-58s %s" % ("OK" if ok else "FAIL", label,
                                   got if ok else "got %r want %r" % (got, want)))

    work = tempfile.mkdtemp(prefix="smartclip-http-")
    target = os.path.join(work, "presets.json")
    with open(target, "w", encoding="utf-8") as handle:
        json.dump({"_readme": ["keep"],
                   "pony": {"positive": {"评分标签": ["score_9"]}},
                   "sdxl": {"positive": {"蝴蝶忍": ["score_9, 1girl"]}}},
                  handle, ensure_ascii=False)
    original = ps.PRESET_FILE
    ps.PRESET_FILE = target
    ps.clear_cache()

    async def scenario():
        # ---- 老文件：sdxl 下建的自建分类，在别的族的弹窗里也要出现 ----
        status, data = await _invoke(routes, "GET", "/smart_clip/presets",
                                     query={"model": "illustrious", "role": "positive"})
        check("HTTP 200", status, 200)
        check("别的族能看到自建分类", "蝴蝶忍" in data["categories"], True)
        check("...并且被标成全局", data["shared"], ["蝴蝶忍"])
        check("族内预设在别的族里不出现", "评分标签" in data["categories"], False)

        status, neg = await _invoke(routes, "GET", "/smart_clip/presets",
                                    query={"model": "pony", "role": "negative"})
        check("正向分类不进反向弹窗", "蝴蝶忍" in neg["categories"], False)

        # ---- 新建分类：任何族的弹窗都能看到 ----
        status, created = await _invoke(routes, "POST", "/smart_clip/presets/create_category",
                                        body={"model": "flux", "role": "positive",
                                              "category": "新分类"})
        check("新建分类返回 stored_in=_shared", created.get("stored_in"), ps.SHARED_MODEL)
        status, data = await _invoke(routes, "GET", "/smart_clip/presets",
                                     query={"model": "pony", "role": "positive"})
        check("pony 弹窗立刻能看到它", "新分类" in data["categories"], True)
        check("...并出现在 shared 列表里", "新分类" in data["shared"], True)

        # ---- 入库 / 读取 / 删除 ----
        status, saved = await _invoke(routes, "POST", "/smart_clip/presets/save",
                                      body={"model": "illustrious", "role": "positive",
                                            "category": "新分类", "text": "abc"})
        check("入库落在共享段", saved.get("stored_in"), ps.SHARED_MODEL)
        status, text = await _invoke(routes, "GET", "/smart_clip/text",
                                     query={"model": "sd15", "role": "positive",
                                            "category": "新分类"})
        check("别的族能读到内容", (text["found"], text["text"]), (True, "abc"))

        status, dropped = await _invoke(routes, "POST", "/smart_clip/presets/delete_category",
                                        body={"model": "generic", "role": "positive",
                                              "category": "新分类"})
        check("删除分类成功", dropped.get("ok"), True)
        status, data = await _invoke(routes, "GET", "/smart_clip/presets",
                                     query={"model": "pony", "role": "positive"})
        check("...别的族里也消失了", "新分类" in data["categories"], False)

        status, info = await _invoke(routes, "GET", "/smart_clip/info")
        check("info 说明了共享段", info["presets"].get("shared_key"), ps.SHARED_MODEL)

    try:
        asyncio.run(scenario())
    finally:
        ps.PRESET_FILE = original
        ps.clear_cache()
        shutil.rmtree(work, ignore_errors=True)
    return fails


def main():
    if smart_clip_api.web is None:
        print("SKIP: aiohttp not importable - run this with python_embeded")
        return 0

    routes = FakeRouteTable()
    server = FakePromptServer()
    server.routes = routes
    server.instance = server

    fake = type(sys)("server")
    fake.PromptServer = server
    sys.modules["server"] = fake

    smart_clip_api._REGISTERED = False
    ok = smart_clip_api.register_routes()
    if not ok:
        FAILS.append("register_routes() returned %r" % (ok,))

    got = set(routes.items)
    for path, methods in sorted(EXPECTED.items()):
        for method in methods:
            present = (method, path) in got
            print("  %-4s %-6s %s" % ("OK" if present else "FAIL", method, path))
            if not present:
                FAILS.append("route not declared: %s %s" % (method, path))

    # The exact bug this file exists for: a decorator after the *body-level*
    # `return`.  Checked textually too, so a future edit that re-orders the
    # function is caught even if someone re-adds a route somewhere unreachable.
    # Only 4-space-indented returns matter: the nested `return True` guards
    # ("already declared") are legitimate early exits.
    source = os.path.join(SRC, "smart_clip_api.py")
    with open(source, "r", encoding="utf-8") as handle:
        lines = handle.readlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("def register_routes")), None)
    if start is None:
        FAILS.append("register_routes() not found in smart_clip_api.py")
    else:
        end = len(lines)
        for i in range(start + 1, len(lines)):
            line = lines[i]
            if line.strip() and not line.startswith((" ", "\t")):
                end = i
                break
        body = lines[start:end]
        decorators = [i for i, line in enumerate(body) if line.lstrip().startswith("@routes.")]
        returns = [i for i, line in enumerate(body) if line.startswith("    return")]
        print("  register_routes(): %d decorators, %d body-level returns"
              % (len(decorators), len(returns)))
        if decorators and returns and max(decorators) > min(returns):
            after = len(decorators) - sum(1 for i in decorators if i < min(returns))
            FAILS.append("%d @routes decorator(s) sit after the first body-level return "
                         "in register_routes() - they are dead code" % after)

    print()
    print("2. 真实调用：自建分类（_shared）在任何族的弹窗里都能看到")
    FAILS.extend(global_category_flow(routes))

    print()
    if FAILS:
        print("FAILURES: %d" % len(FAILS))
        for line in FAILS:
            print("  -", line)
        return 1
    print("FAILURES: 0  (%d routes declared)" % len(got))
    return 0


if __name__ == "__main__":
    sys.exit(main())
