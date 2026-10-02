# -*- coding: utf-8 -*-
"""
SmartCLIP websocket check - the path a real browser actually takes.

    python tests/live_ws_check.py

Why this exists
---------------
The history endpoint only carries a cached node's ui payload when the prompt was
submitted with a client_id (execution.py: `if server.client_id is not None:`
around the cached branch, set from extra_data["client_id"]).  A bare HTTP POST
has no client_id, so a cached run reports no ui at all - which looks exactly
like "the payload is lost on cache hits" if you only test over HTTP.

This script connects a websocket with a client_id (like the browser does),
queues the same workflow twice, and checks that:
  * run 1 delivers smart_clip through the node execution;
  * run 2 (fully cached) still delivers it, from the cached entry;
  * the sampler is NOT re-run (the point of not forcing IS_CHANGED).
"""

import asyncio
import json
import os
import sys
import uuid

try:
    import aiohttp
except Exception as exc:  # pragma: no cover
    print("aiohttp is required:", exc)
    sys.exit(1)

BASE = os.environ.get("MCM_BASE", "http://127.0.0.1:8189").rstrip("/")
WS = BASE.replace("https://", "wss://").replace("http://", "ws://") + "/ws"
CHECKPOINT = os.environ.get("MCM_CKPT", "majicmixRealistic_v7.safetensors")

FAILS = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILS.append("%s: got %r want %r" % (label, got, want))
    print("  %-4s %-56s %s" % ("OK" if ok else "FAIL", label, got if ok else "got %r want %r" % (got, want)))


WORKFLOW = {
    "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CHECKPOINT}},
    "2": {"class_type": "SmartCLIPTextEncode",
          "inputs": {"clip": ["1", 1], "text": "masterpiece, best quality", "prompt_role": "auto"}},
    "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 64, "height": 64, "batch_size": 1}},
    "4": {"class_type": "KSampler",
          "inputs": {"model": ["1", 0], "positive": ["2", 0], "negative": ["2", 0],
                     "latent_image": ["5", 0], "seed": 7, "steps": 1, "cfg": 1.0,
                     "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0}},
    "6": {"class_type": "VAEDecode", "inputs": {"samples": ["4", 0], "vae": ["1", 2]}},
    "7": {"class_type": "PreviewImage", "inputs": {"images": ["6", 0]}},
}

# Same idea, but the SmartCLIP node's output goes nowhere: with OUTPUT_NODE the
# node still runs, so the button/dialog can be informative while you are still
# building the graph.
WORKFLOW_UNCONNECTED = {
    "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CHECKPOINT}},
    "9": {"class_type": "SmartCLIPTextEncode",
          "inputs": {"clip": ["1", 1], "text": "unconnected probe", "prompt_role": "positive"}},
    "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 64, "height": 64, "batch_size": 1}},
    "4": {"class_type": "KSampler",
          "inputs": {"model": ["1", 0], "positive": ["9", 0], "negative": ["9", 0],
                     "latent_image": ["5", 0], "seed": 8, "steps": 1, "cfg": 1.0,
                     "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0}},
    "6": {"class_type": "VAEDecode", "inputs": {"samples": ["4", 0], "vae": ["1", 2]}},
    "7": {"class_type": "PreviewImage", "inputs": {"images": ["6", 0]}},
    # a second SmartCLIP node whose output is deliberately not consumed
    "10": {"class_type": "SmartCLIPTextEncode",
           "inputs": {"clip": ["1", 1], "text": "dangling node", "prompt_role": "auto"}},
}


async def run_once(session, ws, client_id, label, workflow=None):
    workflow = workflow or WORKFLOW
    async with session.post(BASE + "/prompt",
                            json={"prompt": workflow, "client_id": client_id}) as resp:
        queued = await resp.json()
    prompt_id = queued.get("prompt_id")
    check("%s: queued" % label, bool(prompt_id), True)

    executed_events = []
    cached_nodes = []
    progress_nodes = []
    deadline = asyncio.get_event_loop().time() + 900

    while True:
        if asyncio.get_event_loop().time() > deadline:
            check("%s: finished in time" % label, "timeout", "done")
            break
        msg = await asyncio.wait_for(ws.receive_json(), timeout=900)
        mtype = msg.get("type")
        data = msg.get("data") or {}
        if mtype == "executed" and data.get("prompt_id") == prompt_id:
            executed_events.append(data)
        elif mtype == "execution_cached" and data.get("prompt_id") == prompt_id:
            cached_nodes = list(data.get("nodes") or [])
        elif mtype == "executing" and data.get("prompt_id") == prompt_id:
            if data.get("node") is None:
                break
            progress_nodes.append(str(data.get("node")))
        elif mtype == "execution_error" and data.get("prompt_id") == prompt_id:
            check("%s: no execution error" % label, data.get("exception_message"), None)
            break

    payloads = {}
    for event in executed_events:
        output = event.get("output") or {}
        if "smart_clip" in output:
            payloads[str(event.get("node"))] = output["smart_clip"]
    print("    [debug] %s: executed events -> %s" % (
        label,
        [(str(e.get("node")), sorted((e.get("output") or {}).keys())) for e in executed_events]))
    print("    [debug] %s: cached=%s ran=%s" % (label, sorted(cached_nodes), sorted(progress_nodes)))
    return {
        "prompt_id": prompt_id,
        "cached": cached_nodes,
        "ran": progress_nodes,
        "payloads": payloads,
        "events": executed_events,
    }


async def main():
    client_id = str(uuid.uuid4())
    print("connecting %s (client_id=%s)\n" % (WS, client_id))
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(WS + "?clientId=" + client_id, heartbeat=30) as ws:
            first = await run_once(session, ws, client_id, "run 1 (cold)")
            second = await run_once(session, ws, client_id, "run 2 (cached)")
            third = await run_once(session, ws, client_id, "run 3 (dangling node)",
                                   WORKFLOW_UNCONNECTED)

    print("\n[run 1]")
    check("smart_clip delivered over the websocket", "2" in first["payloads"], True)
    if "2" in first["payloads"]:
        payload = first["payloads"]["2"][0]
        check("payload is a dict inside a list", isinstance(payload, dict), True)
        check("family", payload.get("family"), "sd15")
    check("sampler ran", "4" in first["ran"], True)

    print("\n[run 2]")
    check("everything was served from cache",
          sorted(second["cached"]), sorted(["1", "2", "4", "5", "6", "7"]))
    check("the sampler did NOT run again", "4" in second["ran"], False)
    check("smart_clip still delivered on the cached run", "2" in second["payloads"], True)
    if "2" in second["payloads"] and "2" in first["payloads"]:
        check("cached payload equals the original", second["payloads"]["2"], first["payloads"]["2"])

    print("\n[run 3: a node whose output is wired nowhere]")
    check("the dangling SmartCLIP node still reported", "10" in third["payloads"], True)
    if "10" in third["payloads"]:
        check("...with the right family", third["payloads"]["10"][0].get("family"), "sd15")
        check("...and its own role", third["payloads"]["10"][0].get("role"), "auto")

    print("\n" + "=" * 88)
    if FAILS:
        print("FAILURES: %d" % len(FAILS))
        for line in FAILS:
            print("  -", line)
        sys.exit(1)
    print("FAILURES: 0")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print("websocket check failed:", type(exc).__name__, exc)
        sys.exit(1)
