# syntax=docker/dockerfile:1.7
# CPU-only ComfyUI "canvas" – all inference is remote (z.ai, OpenRouter, NVIDIA).
ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.12.1
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:${PYTHON_VERSION}-slim
COPY --from=uv /uv /uvx /usr/local/bin/

ARG COMFYUI_REF
ARG MANAGER_REF
ARG INSTALL_MANAGER=false

ENV UV_CACHE_DIR=/root/.cache/uv UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never \
    VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 HOME=/tmp

RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl ca-certificates libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# Fetch a pinned commit (works for any SHA, shallow).
RUN <<'S'
set -eu
fetch() { # url sha dest
  git init -q "$3" && git -C "$3" remote add origin "$1" \
   && git -C "$3" fetch -q --depth 1 origin "$2" && git -C "$3" checkout -q FETCH_HEAD && rm -rf "$3/.git"
}
mkdir -p /app
fetch https://github.com/comfyanonymous/ComfyUI.git "${COMFYUI_REF}" /app/ComfyUI
if [ "${INSTALL_MANAGER}" = "true" ]; then
  fetch https://github.com/Comfy-Org/ComfyUI-Manager.git "${MANAGER_REF}" /app/ComfyUI/custom_nodes/comfyui-manager
fi
S

# Python deps with uv. torch from the CPU index (no CUDA wheels), rest from PyPI.
RUN --mount=type=cache,target=/root/.cache/uv <<'S'
set -eu
uv venv /opt/venv
uv pip install --index-url https://download.pytorch.org/whl/cpu \
   --extra-index-url https://pypi.org/simple --index-strategy unsafe-best-match \
   torch torchvision torchaudio
uv pip install -r /app/ComfyUI/requirements.txt
if [ -f /app/ComfyUI/custom_nodes/comfyui-manager/requirements.txt ]; then
  uv pip install -r /app/ComfyUI/custom_nodes/comfyui-manager/requirements.txt
fi
S

# Local nodes: z.ai GLM (LLM), VLM (OpenRouter/NVIDIA), OpenRouter video. Last layer => fast rebuilds.
COPY custom_nodes_local/remote_llm /app/ComfyUI/custom_nodes/remote_llm

# Runs as the host uid (compose `user:`) so bind mounts stay writable.
RUN mkdir -p /app/ComfyUI/output /app/ComfyUI/input /app/ComfyUI/user /tmp/comfy \
 && chmod -R a+rwX /app/ComfyUI/output /app/ComfyUI/input /app/ComfyUI/user /tmp/comfy

WORKDIR /app/ComfyUI
EXPOSE 8188
ENV LOG_LEVEL=INFO
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=12 \
  CMD curl -fsS http://localhost:8188/system_stats >/dev/null || exit 1
CMD ["sh", "-c", "exec python main.py --listen 0.0.0.0 --port 8188 --cpu --disable-auto-launch --temp-directory /tmp/comfy --verbose ${LOG_LEVEL}"]
