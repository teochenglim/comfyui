#!/usr/bin/env python3
"""Run a workflow template against ComfyUI (stdlib only). JSON result on stdout.

Exit: 0 ok | 2 bad template/override/missing secret | 3 unreachable | 4 execution error | 5 timeout
"""
import argparse, json, mimetypes, os, sys, time, uuid
import urllib.error, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def die(code, msg, **kw):
    print(json.dumps({"ok": False, "error": msg, **kw}))
    sys.exit(code)


def http(url, data=None, headers=None, method=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:2000]}")
    except urllib.error.URLError as e:
        die(3, f"ComfyUI unreachable at {url}: {e.reason}")


def env_has(name):
    if os.environ.get(name):
        return True
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == name and v.strip():
                return True
    return False


def upload(base, path):
    boundary = uuid.uuid4().hex
    p = Path(path)
    if not p.is_file():
        die(2, f"image not found: {path}")
    ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{p.name}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n").encode() + p.read_bytes() + (
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{boundary}--\r\n").encode()
    r = http(f"{base}/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.loads(r)["name"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--template", help="template id (workflows/templates/<id>.json)")
    ap.add_argument("--list", action="store_true", help="list templates and overridable fields")
    ap.add_argument("--override", "-o", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--image", help="local image to upload (sets the template's 'image' field)")
    ap.add_argument("--wait", action="store_true", help="wait for completion")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--out", help="download output files into this dir (implies --wait)")
    ap.add_argument("--url", default=os.environ.get("COMFYUI_URL", "http://localhost:8188"))
    a = ap.parse_args()
    base = a.url.rstrip("/")
    tdir = ROOT / "workflows" / "templates"

    if a.list:
        out = [{k: json.loads(f.read_text())["_meta"].get(k) for k in ("id", "description", "required_secrets", "overridable_fields")}
               for f in sorted(tdir.glob("*.json"))]
        print(json.dumps(out, indent=2)); return
    if not a.template:
        ap.error("--template or --list required")
    tf = tdir / f"{a.template}.json"
    if not tf.exists():
        die(2, f"unknown template '{a.template}'", available=[f.stem for f in sorted(tdir.glob('*.json'))])
    wf = json.loads(tf.read_text())
    meta = wf.pop("_meta", {})
    fields = meta.get("overridable_fields", {})
    ov = dict(kv.split("=", 1) if "=" in kv else die(2, f"bad override '{kv}'") for kv in a.override)
    if a.image:
        ov["image"] = upload(base, a.image)
    for k, v in ov.items():
        if k not in fields:
            die(2, f"field '{k}' not overridable", overridable=sorted(fields))
        for path in fields[k]:
            nid, _, key = path.split(".", 2)
            cur = wf[nid]["inputs"][key]
            wf[nid]["inputs"][key] = type(cur)(v) if isinstance(cur, (int, float)) and not isinstance(cur, bool) else v

    keys = {"zai": "ZAI_API_KEY", "openrouter": "OPENROUTER_API_KEY", "nvidia": "NVIDIA_API_KEY"}
    need = set(meta.get("required_secrets", []))
    for n in wf.values():
        if n["class_type"] == "OpenRouterVideo":
            need.add("OPENROUTER_API_KEY")
        elif "provider" in n["inputs"]:
            need.add(keys[n["inputs"]["provider"]])
    for k in sorted(need):
        if not env_has(k):
            die(2, f"missing required secret {k} (set it in .env, then `make restart`)")
    try:
        r = json.loads(http(f"{base}/prompt", json.dumps({"prompt": wf, "client_id": uuid.uuid4().hex}).encode(),
                            {"Content-Type": "application/json"}))
    except RuntimeError as e:
        die(2, f"ComfyUI rejected workflow: {e}")
    pid = r["prompt_id"]
    if not (a.wait or a.out):
        print(json.dumps({"ok": True, "prompt_id": pid, "status": "queued"})); return

    t0 = time.time()
    while True:
        h = json.loads(http(f"{base}/history/{pid}")).get(pid)
        if h and h.get("status", {}).get("completed") is not None and (h["outputs"] or h["status"]["status_str"] == "error"):
            break
        if h and h["status"].get("status_str") == "error":
            break
        if time.time() - t0 > a.timeout:
            die(5, f"timeout after {a.timeout}s", prompt_id=pid)
        time.sleep(2)
    if h["status"].get("status_str") == "error":
        msgs = [m[1] for m in h["status"].get("messages", []) if m[0] == "execution_error"]
        die(4, "execution error", prompt_id=pid, details=msgs)

    texts, files = [], []
    for nid, o in h["outputs"].items():
        texts += [t for t in o.get("text", [])]
        for kind in ("images", "gifs", "videos", "audio"):
            for f in o.get(kind, []):
                q = urllib.parse.urlencode({"filename": f["filename"], "subfolder": f.get("subfolder", ""), "type": f.get("type", "output")})
                files.append({"node": nid, "filename": f["filename"], "subfolder": f.get("subfolder", ""), "view_url": f"{base}/view?{q}"})
    if a.out:
        Path(a.out).mkdir(parents=True, exist_ok=True)
        for f in files:
            dst = Path(a.out) / f["filename"]; dst.write_bytes(http(f["view_url"], timeout=300)); f["saved"] = str(dst)
    print(json.dumps({"ok": True, "prompt_id": pid, "text": texts, "files": files, "seconds": round(time.time() - t0, 1)}, indent=2))


if __name__ == "__main__":
    main()
