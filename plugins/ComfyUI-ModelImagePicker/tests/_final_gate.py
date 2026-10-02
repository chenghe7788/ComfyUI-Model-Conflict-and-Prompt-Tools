# -*- coding: utf-8 -*-
"""Final gate: every check against one freshly started ComfyUI, with timings.

Run it from anywhere; the child suites are located relative to this file.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.environ.get(
    "MCM_PYTHON",
    r"C:\ComfyUI_windows_portable\python_embeded\python.exe")
BASE = "http://127.0.0.1:8189"


def wait_for_server(timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(BASE + "/system_stats", timeout=5).read()
            return True
        except Exception:
            time.sleep(2)
    return False


def post(path, payload):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode("utf-8"))


print("waiting for ComfyUI ...")
if not wait_for_server():
    print("server did not come up")
    sys.exit(1)
print("server up\n")

idx = json.loads(urllib.request.urlopen(BASE + "/modelconflict/index", timeout=60).read())
names = idx["kinds"]
print("index:", {k: len(v) for k, v in names.items()})

find = lambda kind, *frags: [n for n in names.get(kind, []) if all(f.lower() in n.lower() for f in frags)]
picks = {
    "checkpoints": find("checkpoints", "majicmix"),
    "vae": find("vae", "vae-ft-mse"),
    "loras": (find("loras", "snofs") + find("loras", "privet-part") + find("loras", "add-detail-xl")
              + find("loras", "krea2_loraholic") + find("loras", "PROFESSIONAL_PORNOGRAPHIC")
              + find("loras", "TeeKays")),
    "embeddings": (find("embeddings", "deep_negative_pony") + find("embeddings", "EasyNegative")
                   + find("embeddings", "badhandv4")),
}

print("\n[cold scan timing]")
t0 = time.time()
res = post("/modelconflict/check", {"kind": "checkpoints", "names": names["checkpoints"], "picks": picks})
cold = time.time() - t0
t0 = time.time()
post("/modelconflict/check", {"kind": "checkpoints", "names": names["checkpoints"], "picks": picks})
warm = time.time() - t0
print("  16 checkpoints: cold %.2fs, cached %.3fs" % (cold, warm))
t0 = time.time()
for kind in ("loras", "vae", "embeddings"):
    post("/modelconflict/check", {"kind": kind, "names": names[kind], "picks": picks})
warm = time.time() - t0
print("  loras+vae+embeddings (cold, %d+%d+%d files): %.2fs"
      % (len(names["loras"]), len(names["vae"]), len(names["embeddings"]), warm))

print("\n[cached repeat of the full picker sets]")
t0 = time.time()
for kind in ("checkpoints", "loras", "vae", "embeddings"):
    post("/modelconflict/check", {"kind": kind, "names": names[kind], "picks": picks})
print("  all four kinds: %.3fs" % (time.time() - t0))

print("\n[child suites]")
fail = 0
# Inherit the real environment (a stripped one stops Windows from loading the
# native safetensors extension, which silently degrades every model to UNKNOWN).
child_env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
for label, cmd in [
    ("python engine self-test", [PY, os.path.join(HERE, "_test_conflict.py")]),
    ("served-JS encoding", [PY, os.path.join(HERE, "_verify_js_encoding.py")]),
]:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          env=child_env)
    tail = [ln for ln in proc.stdout.splitlines() if ln.startswith("FAILURES") or ln.startswith("FAIL")]
    print("  %-24s exit=%s %s" % (label, proc.returncode, " ".join(tail)))
    if proc.returncode != 0:
        fail += 1

proc = subprocess.run(["node", "run.mjs"], cwd=os.path.join(HERE, "_jscheck"), capture_output=True,
                      text=True, encoding="utf-8")
tail = [ln for ln in proc.stdout.splitlines() if ln.startswith("FAIL") or ln.startswith("  FAIL")]
print("  %-24s exit=%s %s" % ("frontend harness", proc.returncode,
                              " ".join(tail) if tail else "(no failures)"))
if proc.returncode != 0:
    fail += 1

print("\nGRAND TOTAL FAILURES:", fail)
sys.exit(1 if fail else 0)
