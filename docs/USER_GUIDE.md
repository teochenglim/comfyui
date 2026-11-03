# End-user guide

## 1. Start / stop

| Do | Command |
|---|---|
| Start (builds first time, ~5–10 min) | `make up` |
| Open the canvas | http://localhost:8188 |
| Stop (keeps your files) | `make down` |
| Apply `.env` changes | `make restart` |
| See logs | `make logs` |
| Fix a broken state | `make clean && make up` |

Colima must be running; `make up` starts it if needed.

## 2. Keys (`.env`)

| Variable | Used for |
|---|---|
| `ZAI_API_KEY` | z.ai GLM (LLM) |
| `OPENROUTER_API_KEY` | free LLM/VLM (`:free` models) and optional paid video |
| `NVIDIA_API_KEY` | free NVIDIA VLM/LLM |
| `OPENROUTER_ALLOW_PAID` | `false` = only `:free` models. `true` = allow paid video |

`make check-env` shows which keys are set (never prints values). `make models P=zai|openrouter|nvidia|openrouter-video` lists model ids you can use.

## 3. Nodes (category **RemoteLLM**)

| Node | What it does |
|---|---|
| Remote LLM Chat | prompt → text. `provider`: `zai`, `openrouter`, `nvidia`. Empty `model` = default from `.env` |
| Remote VLM Chat | image + question → text. `provider`: `openrouter`, `nvidia` |
| Placeholder Clip (free, local) | makes a 2 s animated WebP from a prompt, or zooms on an input image |
| OpenRouter Video (PAID) | real video; blocked unless `OPENROUTER_ALLOW_PAID=true` |

Core **Preview Any** shows text output. Results are saved to `output/`.

## 4. Try it (canvas)

1. Press `w` (Workflows sidebar) and open **basic_llm_to_clip** — a ready-made graph: **Remote LLM Chat → Placeholder Clip → Preview Any** (source: `workflows/ui/`). `workflows/templates/*.json` are API-format for the CLI/MCP, not for the canvas.
2. Set `provider` (`openrouter` or `nvidia` are free), edit the idea text.
3. Press **Run** (Ctrl+Enter).
4. The clip appears on the node and in `output/placeholder/`.

## 5. Try it (command line)

```bash
make templates                                   # what's available
make smoke                                       # free end-to-end
uv run --no-project python scripts/run_workflow.py --template llm_expand \
    --override provider=zai --override prompt="a fox in snow" --wait
uv run --no-project python scripts/run_workflow.py --template vlm_caption \
    --image ~/Pictures/cat.png --override provider=nvidia --wait
make run T=llm_to_clip P="a fox in snow"         # downloads files to output/cli
```

Exit codes: `0` ok, `2` bad input / missing key, `3` ComfyUI unreachable, `4` execution error, `5` timeout.

## 6. Real video (costs money)

1. `.env`: `OPENROUTER_ALLOW_PAID=true`, then `make restart`.
2. Run `llm_to_video_paid` (default 480p, 2 s). Check prices first: `make models P=openrouter-video`.
3. Set it back to `false` afterwards.

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `Missing ZAI_API_KEY` | add to `.env`, `make restart` |
| `not a free OpenRouter model` | use a `:free` model, or allow paid (section 6) |
| HTTP 429 from a `:free` model | shared upstream limit (Google Gemma `:free` is often saturated). Nodes retry 3×; otherwise set `OPENROUTER_LLM_MODEL` / `OPENROUTER_VLM_MODEL` to another `:free` id (`make models P=openrouter`) or use `provider=nvidia` |
| z.ai HTTP 401/403/1113 | key/plan issue; try `ZAI_BASE_URL=https://api.z.ai/api/paas/v4` |
| `make up` hangs | `colima status`; `make logs` |
| Port 8188 busy | set `COMFYUI_PORT` in `.env` |
