# Agent guide — control ComfyUI over MCP

The ComfyUI container exposes plain HTTP on `127.0.0.1:8188`. An MCP server (`comfyui-mcp`, npm, pinned in `versions.env`) runs **on your Mac** (stdio, spawned by the agent) and talks to that URL. Nothing extra runs in the container.

```
Claude Code / ZCode ──stdio──> npx comfyui-mcp ──HTTP──> localhost:8188 (container)
```

## 1. Prerequisites

`make up` is healthy · Node ≥ 22 (`node -v`) · keys in `.env`.

## 2. Connect

**Claude Code (one command):**

```bash
make mcp-add          # = claude mcp add comfyui -s user -e COMFYUI_URL=... -- npx -y comfyui-mcp@<pinned>
claude mcp list       # comfyui ✓ Connected
```

**Any other client (ZCode, Claude Desktop, Cursor…)** — `make mcp-config` prints this, paste into the client's MCP config:

```json
{
  "mcpServers": {
    "comfyui": {
      "command": "npx",
      "args": ["-y", "comfyui-mcp@0.52.206"],
      "env": {
        "COMFYUI_URL": "http://localhost:8188",
        "COMFYUI_MCP_FORCE_REMOTE": "1"
      }
    }
  }
}
```

`COMFYUI_MCP_FORCE_REMOTE=1` is needed because the server cannot see the container's filesystem; it tells `comfyui-mcp` to treat ComfyUI as a remote install (no local-path auto-detection, no model/node installers that touch disk).

**Verify:** `make mcp-doctor` — handshakes, prints the tool list, exits non-zero if fewer than 5 tools.

## 3. What to ask the agent

Our nodes are in the `RemoteLLM` category; there are no local checkpoints, so tell the agent not to build checkpoint/KSampler graphs.

> "Using ComfyUI, list the RemoteLLM nodes. Build a workflow: Remote LLM Chat (provider openrouter) expands 'a fox in snow' into a video prompt, then Placeholder Clip renders it. Run it and tell me the output file."

> "Run the template in workflows/templates/vlm_caption.json on ~/Pictures/cat.png with provider nvidia."

Good system hint to give the agent:

```
ComfyUI here is CPU-only with no models. Use only RemoteLLM nodes (RemoteLLMChat, RemoteVLMChat,
PlaceholderClip) plus core PreviewAny/LoadImage. Never use OpenRouterVideo unless I say paid is OK.
Prefer provider=openrouter or nvidia (free); zai only when asked.
```

## 4. Deterministic fallback (no MCP)

An agent with a shell can skip MCP entirely; JSON in, JSON out:

```bash
uv run --no-project python scripts/run_workflow.py --list
uv run --no-project python scripts/run_workflow.py --template llm_to_clip \
    --override provider=openrouter --override prompt="a fox in snow" --out output/cli
```

Exit codes: `0` ok · `2` invalid input / missing key · `3` unreachable · `4` execution error · `5` timeout.

## 5. Troubleshooting

| Symptom | Fix |
|---|---|
| `make mcp-doctor`: Node too old | `brew install node` (≥ 22) |
| Tools list but calls fail with connection refused | `make up`; check `curl localhost:8188/system_stats` |
| Agent tries to download checkpoints / install nodes | expected to fail in remote mode; add the hint above |
| Agent runs a paid node | keep `OPENROUTER_ALLOW_PAID=false`; the node refuses |
| Changed `.env` | `make restart` (MCP needs no restart) |
