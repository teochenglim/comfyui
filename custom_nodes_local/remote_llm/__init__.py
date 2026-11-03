"""Remote LLM / VLM / video nodes. No local inference; API keys come from container env vars only.

  Remote LLM Chat       provider: zai | openrouter | nvidia      (text -> text)
  Remote VLM Chat       provider: openrouter | nvidia            (image + text -> text)
  Placeholder Clip      free, local, zero-cost stand-in for a video model (animated WebP)
  OpenRouter Video      paid; refuses to run unless OPENROUTER_ALLOW_PAID=true
OpenRouter nodes only accept ':free' models unless OPENROUTER_ALLOW_PAID=true.
"""
import base64
import io
import json
import os
import time
import urllib.error
import urllib.request

import numpy as np
from PIL import Image, ImageDraw

# provider: (key env, base-url env, default base url, model env, default model)
LLM = {
    "zai": ("ZAI_API_KEY", "ZAI_BASE_URL", "https://api.z.ai/api/coding/paas/v4", "ZAI_MODEL", "glm-4.7"),
    "openrouter": ("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1",
                   "OPENROUTER_LLM_MODEL", "nvidia/nemotron-3.5-lightning:free"),
    "nvidia": ("NVIDIA_API_KEY", "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1",
               "NVIDIA_LLM_MODEL", "nvidia/nemotron-3.5-super-vl-120b-a12b"),
}
VLM = {
    "openrouter": ("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1",
                   "OPENROUTER_VLM_MODEL", "nvidia/nemotron-3.5-super-vl:free"),
    "nvidia": ("NVIDIA_API_KEY", "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1",
               "NVIDIA_VLM_MODEL", "nvidia/nemotron-3.5-super-vl-120b-a12b"),
}


def _env(name):
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing {name}. Set it in .env and run `make restart`.")
    return v


def _free_guard(provider, model):
    if provider != "openrouter" or model.endswith(":free"):
        return
    if os.environ.get("OPENROUTER_ALLOW_PAID", "").lower() in ("1", "true", "yes"):
        return
    raise RuntimeError(f"'{model}' is not a free OpenRouter model (:free). Use a :free model, or set "
                       "OPENROUTER_ALLOW_PAID=true in .env and `make restart` to spend credits.")


def _call(url, key, payload=None, timeout=60, retries=3):
    data = None if payload is None else json.dumps(payload).encode()
    hdr = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "comfyui-remote-llm/1.0"}
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=hdr), timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:500]
            # transient upstream limits: back off and retry (not account errors such as z.ai 1113)
            if e.code in (429, 502, 503) and '"1113"' not in body and attempt < retries:
                time.sleep(4 * (attempt + 1))
                continue
            raise RuntimeError(f"{url} -> HTTP {e.code}: {body}") from None
        except urllib.error.URLError as e:
            raise RuntimeError(f"{url} unreachable: {e.reason}") from None


def _chat(table, provider, model, messages, max_tokens, extra=None):
    key_env, base_env, base_def, model_env, model_def = table[provider]
    key = _env(key_env)
    name = model.strip() or os.environ.get(model_env, model_def)
    _free_guard(provider, name)
    payload = {"model": name, "messages": messages, "max_tokens": max_tokens, **(extra or {})}
    body = _call(os.environ.get(base_env, base_def).rstrip("/") + "/chat/completions", key, payload, 180)
    try:
        text = (body["choices"][0]["message"].get("content") or "").strip()
    except (KeyError, IndexError):
        raise RuntimeError(f"Unexpected response from {provider}: {str(body)[:500]}") from None
    if not text:
        raise RuntimeError(f"{provider}/{name} returned empty content (a reasoning model may have used all "
                           f"{max_tokens} max_tokens); raise max_tokens or pick another model.")
    return text


def _jpeg_data_url(img_tensor, max_side=1024):
    arr = (img_tensor[0].cpu().numpy().clip(0, 1) * 255).astype(np.uint8)
    im = Image.fromarray(arr).convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


class _Volatile:
    @classmethod
    def IS_CHANGED(cls, **kw):
        return float("nan")  # remote/non-deterministic: never cache


class RemoteLLMChat(_Volatile):
    CATEGORY = "RemoteLLM"
    FUNCTION = "run"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "prompt": ("STRING", {"multiline": True, "default": ""}),
            "system_prompt": ("STRING", {"multiline": True, "default": "You are a helpful assistant."}),
            "provider": (list(LLM), {"default": "zai"}),
            "model": ("STRING", {"default": ""}),  # empty -> provider default from env
            "temperature": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 1.5, "step": 0.05}),
            "max_tokens": ("INT", {"default": 1024, "min": 16, "max": 16384}),
        }}

    def run(self, prompt, system_prompt, provider, model, temperature, max_tokens):
        extra = {"temperature": temperature}
        if provider == "zai":
            extra["thinking"] = {"type": "disabled"}  # GLM: plain answer, no reasoning trace
        msgs = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
        return (_chat(LLM, provider, model, msgs, max_tokens, extra),)


class RemoteVLMChat(_Volatile):
    CATEGORY = "RemoteLLM"
    FUNCTION = "run"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "prompt": ("STRING", {"multiline": True, "default": "Describe this image in detail for use as a video prompt."}),
            "provider": (list(VLM), {"default": "openrouter"}),
            "model": ("STRING", {"default": ""}),
            "max_tokens": ("INT", {"default": 1024, "min": 16, "max": 16384}),
            "max_side": ("INT", {"default": 1024, "min": 256, "max": 4096}),
        }}

    def run(self, image, prompt, provider, model, max_tokens, max_side):
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": _jpeg_data_url(image, max_side)}}]}]
        return (_chat(VLM, provider, model, msgs, max_tokens),)


def _save_out(sub, name, data):
    import folder_paths
    d = os.path.join(folder_paths.get_output_directory(), sub)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "wb") as f:
        f.write(data)
    return f"{sub}/{name}"


class PlaceholderClip(_Volatile):
    """Free stand-in for a video model: slow zoom over the first frame (or a card with the prompt) -> animated WebP."""
    CATEGORY = "RemoteLLM"
    FUNCTION = "run"
    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("clip_path",)

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "prompt": ("STRING", {"multiline": True, "default": ""}),
            "duration": ("INT", {"default": 2, "min": 1, "max": 10}),
            "fps": ("INT", {"default": 8, "min": 2, "max": 24}),
            "width": ("INT", {"default": 640, "min": 128, "max": 1280}),
            "height": ("INT", {"default": 360, "min": 128, "max": 1280}),
        }, "optional": {"first_frame": ("IMAGE",)}}

    def run(self, prompt, duration, fps, width, height, first_frame=None):
        if first_frame is not None:
            base = Image.fromarray((first_frame[0].cpu().numpy().clip(0, 1) * 255).astype(np.uint8)).convert("RGB")
            base = base.resize((width * 2, height * 2))
        else:
            base = Image.new("RGB", (width * 2, height * 2), (24, 28, 40))
            d = ImageDraw.Draw(base)
            words, line, y = prompt.split(), "", 40
            for w in words:
                if len(line) + len(w) > 48:
                    d.text((40, y), line, fill=(230, 230, 240)); y += 18; line = ""
                line += w + " "
            d.text((40, y), line, fill=(230, 230, 240))
        n = duration * fps
        frames = []
        for i in range(n):
            z = 1.0 + 0.5 * i / max(n - 1, 1)
            w, h = base.width / z, base.height / z
            l, t = (base.width - w) / 2, (base.height - h) / 2
            frames.append(base.resize((width, height), Image.LANCZOS, box=(l, t, l + w, t + h)))
        buf = io.BytesIO()
        frames[0].save(buf, "WEBP", save_all=True, append_images=frames[1:], duration=int(1000 / fps), loop=0, quality=80)
        name = f"clip_{int(time.time() * 1000)}.webp"
        rel = _save_out("placeholder", name, buf.getvalue())
        return {"ui": {"images": [{"filename": name, "subfolder": "placeholder", "type": "output"}],
                       "animated": (True,), "text": [rel]}, "result": (rel,)}


class OpenRouterVideo(_Volatile):
    """PAID text/first-frame-to-video via OpenRouter. Needs OPENROUTER_ALLOW_PAID=true."""
    CATEGORY = "RemoteLLM"
    FUNCTION = "run"
    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("video_path",)

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "prompt": ("STRING", {"multiline": True, "default": ""}),
            "model": ("STRING", {"default": ""}),  # empty -> $OPENROUTER_VIDEO_MODEL
            "duration": ("INT", {"default": 2, "min": 1, "max": 30}),
            "resolution": (["480p", "720p", "1080p"], {"default": "480p"}),
            "aspect_ratio": (["16:9", "9:16", "1:1", "4:3", "3:4"], {"default": "16:9"}),
            "generate_audio": ("BOOLEAN", {"default": False}),
            "timeout_sec": ("INT", {"default": 900, "min": 60, "max": 3600}),
        }, "optional": {"first_frame": ("IMAGE",)}}

    def run(self, prompt, model, duration, resolution, aspect_ratio, generate_audio, timeout_sec, first_frame=None):
        key = _env("OPENROUTER_API_KEY")
        base = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
        name = model.strip() or os.environ.get("OPENROUTER_VIDEO_MODEL", "alibaba/wan-3.0")
        _free_guard("openrouter", name)
        payload = {"model": name, "prompt": prompt, "duration": duration, "resolution": resolution,
                   "aspect_ratio": aspect_ratio, "generate_audio": generate_audio}
        if first_frame is not None:
            payload["frame_images"] = [{"type": "image_url", "frame_type": "first_frame",
                                        "image_url": {"url": _jpeg_data_url(first_frame, 1280)}}]
        jid = _call(f"{base}/videos", key, payload)["id"]
        deadline = time.time() + timeout_sec
        while True:
            st = _call(f"{base}/videos/{jid}", key)
            if st.get("status") == "completed":
                break
            if st.get("status") == "failed":
                raise RuntimeError(f"OpenRouter video job {jid} failed: {st.get('error')}")
            if time.time() > deadline:
                raise RuntimeError(f"OpenRouter video job {jid} timed out ({st.get('status')})")
            time.sleep(5)
        req = urllib.request.Request(f"{base}/videos/{jid}/content?index=0", headers={"Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                rel = _save_out("openrouter", f"{jid}.mp4", r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"download failed HTTP {e.code}") from None
        return {"ui": {"videos": [{"filename": f"{jid}.mp4", "subfolder": "openrouter", "type": "output"}], "text": [rel]},
                "result": (rel,)}


def _font(size):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)  # Pillow >= 10.1: scalable built-in font
    except TypeError:
        return ImageFont.load_default()


def _wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if cur and draw.textlength(trial, font=font) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def _parse_scenes(script):
    import re
    scenes = []
    for ln in script.splitlines():
        ln = re.sub(r"^\s*(?:[-*•]|\d+[.):])\s*", "", ln).strip()
        if ln:
            scenes.append(ln)
    return scenes


class StoryboardVideo(_Volatile):
    """Free: one scene per script line -> captioned, zooming, cross-faded cards -> a real H.264 MP4 (PyAV)."""
    CATEGORY = "RemoteLLM"
    FUNCTION = "run"
    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING", "VIDEO")  # VIDEO feeds core Save Video, which gives the canvas a player
    RETURN_NAMES = ("video_path", "video")

    PALETTES = [((18, 24, 56), (86, 52, 140)), ((10, 52, 64), (30, 120, 110)), ((60, 24, 36), (170, 80, 60)),
                ((22, 30, 48), (60, 110, 170)), ((40, 28, 60), (150, 70, 120)), ((20, 44, 30), (110, 150, 70))]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "script": ("STRING", {"multiline": True, "default": "Scene one\nScene two\nScene three"}),
            "title": ("STRING", {"default": ""}),
            "seconds_per_scene": ("FLOAT", {"default": 2.5, "min": 0.5, "max": 10.0, "step": 0.5}),
            "fps": ("INT", {"default": 24, "min": 8, "max": 30}),
            "width": ("INT", {"default": 1280, "min": 256, "max": 1920, "step": 2}),
            "height": ("INT", {"default": 720, "min": 144, "max": 1080, "step": 2}),
            "max_scenes": ("INT", {"default": 8, "min": 1, "max": 30}),
            "motion": (["auto", "zoom_in", "zoom_out", "pan_left_right", "pan_right_left", "sway"], {"default": "auto"}),
            "crossfade": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.5, "step": 0.1}),
        }, "optional": {"images": ("IMAGE",)}}  # reference images: scene i uses image i (cycled)

    AUTO_MOTION = ["zoom_in", "pan_left_right", "sway", "zoom_out", "pan_right_left", "sway"]

    @staticmethod
    def _camera(kind, p, bw, bh, w, h):
        """Affine params (a,b,c,d,e,f) mapping output px -> base px, for camera move `kind` at progress p in [0,1]."""
        import math
        e = p * p * (3 - 2 * p)
        ox = oy = th = 0.0
        z = 1.25
        if kind == "zoom_in":
            z = 1.0 + 0.25 * e
        elif kind == "zoom_out":
            z = 1.25 - 0.25 * e
        elif kind == "pan_left_right":
            ox = -1 + 2 * e
        elif kind == "pan_right_left":
            ox = 1 - 2 * e
        else:  # sway: gentle handheld drift + slight roll
            z = 1.22
            ox = 0.6 * math.sin(2 * math.pi * 1.3 * p)
            oy = 0.4 * math.sin(2 * math.pi * 1.9 * p + 1.0)
            th = math.radians(1.6) * math.sin(2 * math.pi * 1.1 * p)
        cx = bw / 2 + ox * 0.9 * bw * (1 - 1 / z) / 2
        cy = bh / 2 + oy * 0.9 * bh * (1 - 1 / z) / 2
        s = (bw / w) / z
        co, si = math.cos(th), math.sin(th)
        return (s * co, -s * si, cx - s * (co * w / 2 - si * h / 2),
                s * si, s * co, cy - s * (si * w / 2 + co * h / 2))

    def _card(self, i, n, text, title, w, h, bg=None, layer="both"):
        """layer: 'base' = background only (moves with the camera), 'text' = RGBA caption overlay (stays put)."""
        if layer != "text":
            if bg is not None:
                im = bg.convert("RGB").resize((w, h), Image.LANCZOS)
                arr = np.asarray(im, dtype=np.float32)
                shade = np.clip((np.linspace(0, 1, h, dtype=np.float32) - 0.35) / 0.65, 0, 1)[:, None, None]
                im = Image.fromarray((arr * (1 - 0.7 * shade)).astype(np.uint8))  # darken bottom for caption contrast
            else:
                c0, c1 = self.PALETTES[i % len(self.PALETTES)]
                t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
                g = np.linspace(0, 1, w, dtype=np.float32)[None, :, None]
                mix = (0.7 * t + 0.3 * g)
                arr = (np.array(c0, np.float32) * (1 - mix) + np.array(c1, np.float32) * mix).astype(np.uint8)
                im = Image.fromarray(arr)
            if layer == "base":
                return im
        else:
            im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        big, small = _font(max(18, h // 15)), _font(max(12, h // 32))
        pad = int(w * 0.09)
        lines = _wrap(d, text, big, w - 2 * pad)
        lh = int(big.size * 1.35) if hasattr(big, "size") else 24
        y = int(h * 0.88) - lh * len(lines) if bg is not None else (h - lh * len(lines)) // 2
        for ln in lines:
            d.text((pad + 2, y + 2), ln, font=big, fill=(0, 0, 0))
            d.text((pad, y), ln, font=big, fill=(245, 245, 250))
            y += lh
        d.text((pad, int(h * 0.06)), (title + "  ·  " if title else "") + f"{i + 1}/{n}", font=small, fill=(210, 215, 235))
        d.rectangle((pad, int(h * 0.93), pad + int((w - 2 * pad) * (i + 1) / n), int(h * 0.945)), fill=(245, 245, 250))
        return im

    def run(self, script, title, seconds_per_scene, fps, width, height, max_scenes, motion="auto", crossfade=0.5,
            images=None):
        import av
        import folder_paths
        scenes = _parse_scenes(script)[:max_scenes]
        if not scenes:
            raise RuntimeError("StoryboardVideo: script is empty (need one scene per line).")
        w, h = width - width % 2, height - height % 2
        out_dir = os.path.join(folder_paths.get_output_directory(), "storyboard")
        os.makedirs(out_dir, exist_ok=True)
        name = f"storyboard_{int(time.time() * 1000)}.mp4"
        path = os.path.join(out_dir, name)
        container = av.open(path, "w")
        try:
            try:
                stream = container.add_stream("libx264", rate=fps)
                stream.options = {"crf": "23", "preset": "veryfast"}
            except Exception:
                stream = container.add_stream("mpeg4", rate=fps)
            stream.width, stream.height, stream.pix_fmt = w, h, "yuv420p"
            n_frames = max(2, int(seconds_per_scene * fps))
            fade = max(1, int(0.35 * fps))
            xf = min(int(crossfade * fps), n_frames // 2)  # crossfade replaces the first xf frames of the next scene
            text_in = max(1, int(0.5 * fps))

            def scene_data(i):
                bg = None
                if images is not None and len(images):
                    bg = Image.fromarray((images[i % len(images)].cpu().numpy().clip(0, 1) * 255).astype(np.uint8))
                bw, bh = int(w * 1.5), int(h * 1.5)  # base is 1.5x output so zoom/pan stay sharp
                base = self._card(i, len(scenes), text, title, bw, bh, bg, layer="base")
                ov = np.asarray(self._card(i, len(scenes), text, title, w, h, bg, layer="text"), dtype=np.float32)
                kind = self.AUTO_MOTION[i % len(self.AUTO_MOTION)] if motion == "auto" else motion
                key = (i % len(images)) if images is not None and len(images) else None
                return base, ov, kind, key

            def render(data, f):
                base, ov, kind, _ = data
                p = min(1.0, f / (n_frames - 1))
                m = self._camera(kind, p, base.width, base.height, w, h)
                fr = np.asarray(base.transform((w, h), Image.AFFINE, m, resample=Image.BICUBIC), dtype=np.float32)
                e = min(1.0, (f + 1) / text_in)
                e = e * e * (3 - 2 * e)
                a = ov[..., 3:4] / 255.0 * e
                dy = int((1 - e) * h * 0.03)  # caption slides up as it fades in
                if dy:
                    a, ovc = np.roll(a, dy, axis=0), np.roll(ov[..., :3], dy, axis=0)
                else:
                    ovc = ov[..., :3]
                return fr * (1 - a) + ovc * a

            prev = None
            for i, text in enumerate(scenes):
                cur = scene_data(i)
                for f in range(n_frames):
                    frame = render(cur, f)
                    # blend scenes only when the background differs; the same photo at two camera positions ghosts
                    if prev is not None and f < xf and (cur[3] is None or cur[3] != prev[3]):
                        frame = render(prev, n_frames - 1) * (1 - (f + 1) / (xf + 1)) + frame * ((f + 1) / (xf + 1))
                    k = 1.0
                    if i == 0:
                        k = min(k, (f + 1) / fade)  # fade in from black
                    if i == len(scenes) - 1:
                        k = min(k, (n_frames - f) / fade)  # fade out to black
                    vf = av.VideoFrame.from_ndarray(np.clip(frame * k, 0, 255).astype(np.uint8), format="rgb24")
                    for pkt in stream.encode(vf):
                        container.mux(pkt)
                prev = cur
            for pkt in stream.encode():
                container.mux(pkt)
        finally:
            container.close()
        rel = f"storyboard/{name}"
        from comfy_api.latest import InputImpl
        return {"ui": {"videos": [{"filename": name, "subfolder": "storyboard", "type": "output"}], "text": [rel]},
                "result": (rel, InputImpl.VideoFromFile(path))}


class ReferenceImageGroup(_Volatile):
    """Load a group of reference images from ComfyUI's input/ folder by glob (e.g. 'Sunny*') -> one IMAGE batch."""
    CATEGORY = "RemoteLLM"
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("images", "filenames")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "pattern": ("STRING", {"default": "*"}),  # glob inside input/ (not recursive), e.g. Sunny* or *.png
            "max_images": ("INT", {"default": 4, "min": 1, "max": 16}),
            "width": ("INT", {"default": 1280, "min": 256, "max": 1920, "step": 2}),
            "height": ("INT", {"default": 720, "min": 144, "max": 1080, "step": 2}),
            "fit": (["cover", "contain"], {"default": "cover"}),
        }}

    def run(self, pattern, max_images, width, height, fit):
        import glob
        import folder_paths
        import torch
        root = os.path.realpath(folder_paths.get_input_directory())
        pat = pattern.strip() or "*"
        if not any(c in pat for c in "*?[") and not os.path.splitext(pat)[1]:
            pat += "*"
        files = []
        for p in sorted(glob.glob(os.path.join(root, pat))):
            rp = os.path.realpath(p)
            if (os.path.commonpath([root, rp]) == root and os.path.isfile(rp)
                    and rp.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))):
                files.append(rp)
        files = files[:max_images]
        if not files:
            raise RuntimeError(f"ReferenceImageGroup: no png/jpg/webp in input/ matching '{pattern}'.")
        out = []
        for f in files:
            im = Image.open(f).convert("RGB")
            scale = (max if fit == "cover" else min)(width / im.width, height / im.height)
            im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
            canvas = Image.new("RGB", (width, height), (0, 0, 0))
            canvas.paste(im, ((width - im.width) // 2, (height - im.height) // 2))
            out.append(torch.from_numpy(np.asarray(canvas, dtype=np.float32) / 255.0))
        return (torch.stack(out), "\n".join(os.path.basename(f) for f in files))


NODE_CLASS_MAPPINGS = {"RemoteLLMChat": RemoteLLMChat, "RemoteVLMChat": RemoteVLMChat,
                       "PlaceholderClip": PlaceholderClip, "OpenRouterVideo": OpenRouterVideo,
                       "StoryboardVideo": StoryboardVideo, "ReferenceImageGroup": ReferenceImageGroup}
NODE_DISPLAY_NAME_MAPPINGS = {"RemoteLLMChat": "Remote LLM Chat (z.ai/OpenRouter/NVIDIA)",
                              "RemoteVLMChat": "Remote VLM Chat (OpenRouter/NVIDIA)",
                              "PlaceholderClip": "Placeholder Clip (free, local)",
                              "OpenRouterVideo": "OpenRouter Video (PAID)",
                              "StoryboardVideo": "Storyboard Video (free, local MP4)",
                              "ReferenceImageGroup": "Reference Image Group (input/ folder)"}
