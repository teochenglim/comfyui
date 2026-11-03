#!/usr/bin/env python3
"""Assert the expected remote nodes are registered in ComfyUI /object_info. Exit 1 on failure."""
import argparse, json, os, sys, urllib.request

EXPECT = {
    "remote_llm": ["RemoteLLMChat", "RemoteVLMChat", "PlaceholderClip", "OpenRouterVideo"],
    "core": ["PreviewAny", "LoadImage"],
}
ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--url", default=os.environ.get("COMFYUI_URL", "http://localhost:8188"))
a = ap.parse_args()
try:
    info = json.load(urllib.request.urlopen(a.url.rstrip("/") + "/object_info", timeout=30))
except Exception as e:
    sys.exit(f"cannot reach {a.url}: {e}")
bad = 0
for pack, names in EXPECT.items():
    for n in names:
        ok = n in info
        bad += not ok
        print(f"{'OK  ' if ok else 'MISS'} [{pack}] {n}")
sys.exit(1 if bad else 0)
