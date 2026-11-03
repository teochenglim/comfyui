# ComfyUI (CPU, uv, Colima) with remote LLM / VLM

ComfyUI in a container on an Apple-silicon Mac. **No local models.** Text and vision come from z.ai, OpenRouter (`:free`) and NVIDIA. See [prd.md](prd.md).

## Quickstart

```bash
make init          # creates .env — add ZAI_API_KEY, OPENROUTER_API_KEY, NVIDIA_API_KEY
make up            # builds (uv, CPU torch) and waits until healthy
make verify-nodes  # custom nodes registered?
make smoke         # free end-to-end test (OpenRouter :free LLM -> Placeholder Clip)
open http://localhost:8188
```

`make` alone prints the full menu. Docs: [end-user guide](docs/USER_GUIDE.md) · [agent / MCP guide](docs/AGENT.md).

## Layout

| Path | Purpose |
|---|---|
| `Dockerfile`, `docker-compose.yml`, `versions.env` | image (uv, pinned ComfyUI SHA) |
| `custom_nodes_local/remote_llm/` | our nodes: LLM, VLM, Placeholder Clip, OpenRouter Video (paid) |
| `workflows/templates/` | parameterised API-format workflows with a `_meta` block |
| `scripts/` | `run_workflow.py`, `verify_nodes.py`, `mcp_doctor.mjs` |
| `k8s/` | optional k3s deployment (`make k8s-up`) |

## Video: read this

No free real video model exists on OpenRouter or NVIDIA (verified by listing both APIs). So:

- **Default:** `Placeholder Clip` — a free animated WebP (slow zoom), proves the whole pipeline.
- **Real video (paid):** set `OPENROUTER_ALLOW_PAID=true` in `.env`, `make restart`, use `llm_to_video_paid` (default `alibaba/wan-3.0`, 480p, 2 s, no audio ≈ US$0.10).

## Notes

- Keys live only in `.env` (gitignored) and reach the container as environment variables. Workflows contain no secrets.
- After editing `.env`: `make restart`.
- z.ai Coding Plan keys are meant for supported coding tools. If z.ai rejects ComfyUI use, set `ZAI_BASE_URL=https://api.z.ai/api/paas/v4` or pass `provider=openrouter`.

## Release (GitHub Container Registry)

`.github/workflows/release.yml` builds `linux/amd64,arm64` on every push to `main` (`:main`, `:sha-…`) and on tags:

```bash
git tag v0.1.0 && git push origin v0.1.0   # -> ghcr.io/<owner>/<repo>:0.1.0, :0.1, :latest + GitHub Release
docker run -p 127.0.0.1:8188:8188 --env-file .env ghcr.io/<owner>/<repo>:0.1.0
```

Versions come from `versions.env`. Actions are pinned by SHA. The package inherits the repo's visibility; make it public in the repo's *Packages* settings if you want anonymous pulls.
