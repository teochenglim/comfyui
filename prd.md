# PRD — Local ComfyUI Canvas with Remote LLM/VLM and MCP Control Plane

Status: v2.0 (rewrite). Supersedes v1.0, which assumed Atlas Cloud and Docker Desktop.

## 1. Summary

A reproducible, **CPU-only, containerized ComfyUI** on an Apple-silicon MacBook Pro that does **no local model inference**. The container is only the node canvas, workflow orchestration and HTTP API. Intelligence is remote:

| Capability | Provider | Cost |
|---|---|---|
| LLM (prompt expansion) | z.ai GLM (Coding Plan / Pro subscription) | subscription |
| LLM / VLM (test + fallback) | OpenRouter `:free` models, NVIDIA build (`integrate.api.nvidia.com`) | free |
| Video | **Placeholder Clip** (free, local animated WebP) by default; OpenRouter video (paid) by explicit opt-in | free / paid |
| Control plane | `comfyui-mcp` (stdio, on the host) + `scripts/run_workflow.py` | free |

Atlas Cloud is **out of scope** (cost). It was removed.

### Provider findings (probed 2026-11-03 with live keys)

- NVIDIA hosted API (`/v1/models`, 85 models): **no video generator**, no Cosmos 3 Super. Only understanding models (`nvidia/cosmos-reason2-8b`, `nvidia/vila`, `nvidia/nemotron-3.5-super-vl-120b-a12b`, Llama-3.2 vision). Cosmos 3 generation is NIM-only (needs a GPU).
- OpenRouter `/api/v1/videos/models` (31 models): **none free**. `:free` models exist only for text / image→text.
- Therefore a real *free* video model does not exist in the chosen providers. The workflow is proven end-to-end with the Placeholder Clip; real video is a paid opt-in.

## 2. Goals

| ID | Goal | Measure |
|---|---|---|
| G1 | One-command environment | `make up` from clean clone → `http://localhost:8188` healthy < 180 s |
| G2 | Zero local inference | image has no model weights; `models/` not mounted |
| G3 | Free end-to-end test | `make smoke` runs LLM → Placeholder Clip using only `:free` models, exit 0, file in `output/` |
| G4 | z.ai LLM works | `llm_expand` template returns text with `provider=zai` |
| G5 | Free VLM works | `vlm_caption` returns a caption (OpenRouter `:free` or NVIDIA) |
| G6 | Agent-controllable | `make mcp-doctor` lists ≥ 5 MCP tools; agent can run a template |
| G7 | Secret hygiene | keys only in gitignored `.env`; never in workflow JSON, image layers or logs |
| G8 | No accidental spend | OpenRouter nodes refuse non-`:free` models unless `OPENROUTER_ALLOW_PAID=true` |

## 3. Non-goals

Local GPU/MPS inference; training; multi-user auth/TLS/public exposure; Windows/NVIDIA-host support; Atlas Cloud.

## 4. Environment

- macOS, Apple silicon, **Colima** (`docker + k3s`), Docker CLI, `kubectl`, `uv`, Node ≥ 22 (host, for MCP), GNU make.
- Container: `python:3.12-slim`, **uv**-managed venv, torch from the PyTorch **CPU** index, ComfyUI pinned by commit SHA, `--cpu`.
- Runs as the host uid so bind mounts on Colima/virtiofs are writable.
- Bound to `127.0.0.1:8188` only.

## 5. Architecture

```
Host (macOS)                                   Colima VM
 Agent (Claude Code / ZCode)                    ┌──────────────────────────────┐
   └─ stdio ─> npx comfyui-mcp ── HTTP :8188 ──>│ container comfyui (CPU)      │
 make / run_workflow.py ───────── HTTP :8188 ──>│  ComfyUI + custom_nodes/     │
                                                │   remote_llm (our pack)      │
                                                └───────┬───────────┬──────────┘
                                                  HTTPS │           │ HTTPS
                                            z.ai (GLM)  │           │ OpenRouter / NVIDIA
```

Optional: the same image deploys to the Colima k3s cluster (`make k8s-up`).

## 6. Functional requirements

| FR | Requirement | Pri |
|---|---|---|
| FR-1 | Dockerfile with uv; ComfyUI pinned in `versions.env`; healthcheck on `/system_stats`; `--cpu` | P0 |
| FR-2 | `custom_nodes_local/remote_llm` provides `RemoteLLMChat` (zai/openrouter/nvidia), `RemoteVLMChat` (openrouter/nvidia), `PlaceholderClip`, `OpenRouterVideo` (paid) | P0 |
| FR-3 | Keys come from container env (`.env` → compose `env_file`); never written into workflows | P0 |
| FR-4 | Free-only guard for OpenRouter unless `OPENROUTER_ALLOW_PAID=true` | P0 |
| FR-5 | Persistence: `./output`, `./input`, `./user` bind-mounted; no `models/` mount | P0 |
| FR-6 | Makefile: bare `make` prints a menu; targets for build/up/down/logs/shell, verify, smoke, run, models, mcp, k8s | P0 |
| FR-7 | Templates in `workflows/templates` with `_meta` (`id`, `description`, `overridable_fields`): `llm_expand`, `vlm_caption`, `llm_to_clip`, `vlm_to_clip`, `llm_to_video_paid` | P0 |
| FR-8 | `scripts/run_workflow.py` (stdlib only): `--template --override --image --wait --out`; JSON on stdout; exit 0 ok / 2 invalid or missing secret / 3 unreachable / 4 execution error / 5 timeout | P0 |
| FR-9 | MCP: `make mcp-config`, `make mcp-add`, `make mcp-doctor` (≥ 5 tools); pinned `comfyui-mcp` version | P0 |
| FR-10 | Docs: `README.md`, `docs/USER_GUIDE.md` (end user), `docs/AGENT.md` (MCP) | P0 |
| FR-11 | Optional k3s manifests in `k8s/` | P1 |

## 7. Acceptance criteria

| # | Check | Expected |
|---|---|---|
| AC-1 | `docker compose config` | valid |
| AC-2 | `make up` | healthy; `curl localhost:8188/system_stats` 200 |
| AC-3 | `make verify-nodes` | exit 0; four `remote_llm` classes present |
| AC-4 | `make smoke` | exit 0; text + `placeholder/*.webp` in `output/` (free models only) |
| AC-5 | `run_workflow.py --template llm_expand --override provider=zai` | exit 0, text |
| AC-6 | `run_workflow.py --template vlm_caption --image <png>` | exit 0, caption |
| AC-7 | `make mcp-doctor` | exit 0, ≥ 5 tools |
| AC-8 | `llm_to_video_paid` with `OPENROUTER_ALLOW_PAID=false` | exit 4, message names the flag |
| AC-9 | key unset for chosen provider | exit 2, message names the variable |
| AC-10 | `make down && make up` | `output/` and `user/` survive |
| AC-11 | `git grep` for key-shaped strings | no hits in tracked files |

## 8. Non-functional

Image < 3 GB; cold build < 15 min; `make up` < 180 s; everything third-party pinned (SHA or exact version); all scripts have `--help` and fail loudly.

## 9. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | z.ai **Coding Plan** is licensed for supported coding tools; a ComfyUI node may be outside its terms | `ZAI_BASE_URL` is configurable; switch to `https://api.z.ai/api/paas/v4` (pay-as-you-go) if refused; free providers are a drop-in fallback via `provider=` |
| R2 | `:free` models are rate-limited (≈ 50 req/day) and rotate | model ids in `.env`; `make models P=openrouter` lists current ones |
| R3 | No free real video model | Placeholder Clip default; paid opt-in is explicit and guarded |
| R4 | `comfyui-mcp` is "limited maintenance"; in remote mode local-filesystem tools are unavailable | pinned version; `run_workflow.py` is the deterministic fallback |
| R5 | Bind-mount permissions on Colima | container runs as host uid |
| R6 | Free model ids drift | defaults are env-configurable, not hard-coded in workflows |

## 10. Decisions vs v1.0

| v1.0 | v2.0 | Why |
|---|---|---|
| Docker Desktop | Colima | host reality |
| pip | uv | requested |
| Atlas Cloud video/VLM | removed; OpenRouter + NVIDIA free VLM, Placeholder Clip | Atlas cost; no free real video exists |
| secret render pipeline (`{{KEY}}` placeholders) | env vars read by nodes | no secret ever enters a workflow, so no render step is needed |
| ComfyUI-GLM4 pack | own small `remote_llm` pack | upstream name unverified; OpenAI-compatible API is trivial and keeps keys in env |
