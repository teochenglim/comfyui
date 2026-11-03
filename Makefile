SHELL := /bin/bash
.DEFAULT_GOAL := help
include versions.env
-include .env
export

export HOST_UID := $(shell id -u)
export HOST_GID := $(shell id -g)
COMFYUI_PORT ?= 8188
export COMFYUI_URL ?= http://localhost:$(COMFYUI_PORT)
DC := docker compose

##@ Setup
.PHONY: help init check-env colima
help: ## Show this menu (default target)
	@awk 'BEGIN{FS=":.*##"; printf "\nComfyUI (remote inference) — make <target>\n"} \
	  /^##@/{printf "\n\033[1m%s\033[0m\n", substr($$0,5)} \
	  /^[a-zA-Z_-]+:.*##/{printf "  \033[36m%-16s\033[0m %s\n",$$1,$$2}' $(MAKEFILE_LIST); echo

init: ## Create .env from .env.example and the data dirs
	@test -f .env || { cp .env.example .env; echo "Created .env — edit it and add your keys"; }
	@mkdir -p output input user

colima: ## Ensure colima (docker + k3s) is running
	@colima status >/dev/null 2>&1 || colima start --cpu 4 --memory 8 --kubernetes
	@docker info >/dev/null

check-env: ## Report which API keys are set (values never printed)
	@for v in ZAI_API_KEY OPENROUTER_API_KEY NVIDIA_API_KEY; do \
	  if [ -n "$${!v}" ]; then echo "  ok      $$v"; else echo "  MISSING $$v  (edit .env)"; fi; done

##@ Docker (Colima)
.PHONY: build up down restart logs shell ps clean
build: init colima ## Build the image (uv, CPU-only, arm64)
	$(DC) build

up: init colima ## Start ComfyUI and wait until healthy -> http://localhost:8188
	$(DC) up -d --build --wait
	@$(MAKE) --no-print-directory check-env
	@echo "Canvas: $(COMFYUI_URL)"

down: ## Stop the container (output/ and user/ are kept)
	$(DC) down

restart: ## Recreate container (use after editing .env)
	$(DC) up -d --force-recreate --wait

logs: ## Tail container logs
	$(DC) logs -f --tail=100 comfyui

shell: ## Shell inside the container
	$(DC) exec comfyui bash

ps: ## Container status
	$(DC) ps

clean: ## Remove container, image and build cache (keeps output/ user/)
	$(DC) down --rmi local --volumes
	-docker builder prune -f

##@ Verify & run
.PHONY: verify-nodes templates smoke models run
verify-nodes: ## Assert GLM / VLM / video nodes are registered
	uv run --no-project python scripts/verify_nodes.py

templates: ## List workflow templates and their overridable fields
	uv run --no-project python scripts/run_workflow.py --list

smoke: ## Free end-to-end test: OpenRouter LLM -> Placeholder Clip (no cost)
	uv run --no-project python scripts/run_workflow.py --template llm_to_clip --override provider=openrouter --override prompt="a fox in snow" --wait --out output/smoke

run: ## Run a template: make run T=glm_to_t2v P="a fox in snow"
	uv run --no-project python scripts/run_workflow.py --template $(T) --override prompt="$(P)" --out output/cli

models: ## List model ids: make models P=openrouter|nvidia|zai|openrouter-video
	@case "$(P)" in \
	  openrouter) curl -fsS https://openrouter.ai/api/v1/models?input_modalities=image | uv run --no-project python -c "import json,sys;[print(m['id']) for m in json.load(sys.stdin)['data']]";; \
	  openrouter-video) curl -fsS https://openrouter.ai/api/v1/videos/models | uv run --no-project python -c "import json,sys;d=json.load(sys.stdin);[print(m['id'],m.get('supported_resolutions')) for m in d.get('data',d)]";; \
	  nvidia) curl -fsS -H "Authorization: Bearer $$NVIDIA_API_KEY" $${NVIDIA_BASE_URL:-https://integrate.api.nvidia.com/v1}/models | uv run --no-project python -c "import json,sys;[print(m['id']) for m in json.load(sys.stdin)['data']]";; \
	  zai) curl -fsS -H "Authorization: Bearer $$ZAI_API_KEY" $${ZAI_BASE_URL:-https://api.z.ai/api/coding/paas/v4}/models | uv run --no-project python -c "import json,sys;[print(m['id']) for m in json.load(sys.stdin)['data']]";; \
	  *) echo "usage: make models P=openrouter|openrouter-video|nvidia|zai";; esac

##@ MCP (agent control)
.PHONY: mcp-config mcp-doctor mcp-add
mcp-config: ## Print the MCP JSON config for Claude Code / ZCode / Claude Desktop
	@printf '{\n  "mcpServers": {\n    "comfyui": {\n      "command": "npx",\n      "args": ["-y", "comfyui-mcp@$(COMFYUI_MCP_VERSION)"],\n      "env": {\n        "COMFYUI_URL": "$(COMFYUI_URL)",\n        "COMFYUI_MCP_FORCE_REMOTE": "1"\n      }\n    }\n  }\n}\n'

mcp-add: ## Register the MCP server with Claude Code (user scope)
	claude mcp add comfyui -s user -e COMFYUI_URL=$(COMFYUI_URL) -e COMFYUI_MCP_FORCE_REMOTE=1 -- npx -y comfyui-mcp@$(COMFYUI_MCP_VERSION)

mcp-doctor: ## Handshake with the MCP server and list tools (needs Node >= 22)
	node scripts/mcp_doctor.mjs

##@ Kubernetes (optional, colima k3s)
.PHONY: k8s-up k8s-down k8s-forward k8s-status
k8s-up: build ## Deploy to k3s (image is shared via colima docker runtime)
	kubectl apply -f k8s/namespace.yaml
	kubectl -n comfyui create secret generic comfyui-env --from-env-file=.env --dry-run=client -o yaml | kubectl apply -f -
	kubectl apply -f k8s/comfyui.yaml
	kubectl -n comfyui rollout status deploy/comfyui --timeout=300s

k8s-forward: ## Port-forward the k8s service to localhost:8188
	kubectl -n comfyui port-forward svc/comfyui 8188:8188

k8s-status: ## Show k8s resources
	kubectl -n comfyui get all,pvc

k8s-down: ## Delete the k8s namespace (PVCs included)
	kubectl delete ns comfyui --ignore-not-found
