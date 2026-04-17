# Pantheon

Pantheon is a local-first AI workspace manager for:

- chat history you can version control
- local memory + retrieval with SQLite
- model/provider routing (Copilot Proxy + OpenAI-compatible local backends)
- encrypted local credential vault with reusable credential references
- local projects workspace with filesystem controls and Copilot CLI-driven actions
- a small UI to operate your setup

## Goals

- Keep repo data small and portable.
- Prefer markdown/jsonl/small sqlite files.
- Build from open standards and easy local tooling.
- Make recovery/reinstall straightforward.

## Repo Layout

- `backend/`: FastAPI service for chat routing, persistence, memory indexing.
- `frontend/`: minimal browser UI.
- `docs/`: architecture and integration guides.

## Quick Start

1. `cd backend`
2. `python3 -m venv .venv && source .venv/bin/activate`
3. `pip install -r requirements.txt`
4. `cp .env.example .env`
5. `uvicorn app.main:app --reload --port 8787`
6. Open `http://127.0.0.1:8787`

## Current Integrations

- Copilot Proxy (OpenAI-compatible assumed): default `http://127.0.0.1:8080/v1`
- Optional local OpenAI-compatible runtime (LiteLLM/vLLM/LM Studio/llama.cpp server): configure `PANTHEON_LOCAL_BASE_URL` when available

## Current Runtime Topology (Verified)

- Pantheon API: `http://127.0.0.1:8787`
- Copilot Proxy provider: `http://127.0.0.1:8080/v1`
- Local inference provider (llama.cpp server): `http://127.0.0.1:8082/v1`
- Local model name: `Qwen_Qwen3-14B-Q4_K_M.gguf`
- Embedding service: `127.0.0.1:8081`
- Chroma: `127.0.0.1:8000`

llama.cpp inference settings (for the current 1080 Ti tuning):

- `--ctx-size 4096`
- `--n-gpu-layers auto`
- `--flash-attn on`

## What This Baseline Already Does

- Creates local SQLite DB on first run.
- Stores conversations and messages.
- Streams assistant output to browser.
- Indexes and searches notes via FTS5 chunk store.
- Stores secrets in an encrypted local credential vault and supports .env import.
- Provides a multi-tab Control Deck UI:
	- `Command Deck`: chat with provider routing and live health.
	- `MCP Forge`: register/list/check/delete MCP servers.
	- `Credentials Vault`: encrypted credential management, connector login launch, and LAN access hints.
	- `Projects`: create/load local project folders, inspect tree, run approved commands, and call Copilot CLI.
	- `Knowledge Lab`: capture notes and place configurable dashboard widgets.
	- `Copilot Build Loop`: queue build tasks to drive iterative work in VS Code.

## Remote LAN Access

To expose CrowPilot to other devices on your local network:

1. Set `PANTHEON_HOST=0.0.0.0` in `backend/.env`.
2. Restart CrowPilot.
3. Open the Credentials Vault page and use the Hub Access panel URLs from your other machine.

## Next Milestones

- Add embedding model and semantic search re-rank.
- Add model health dashboard.
- Add import/export for markdown and jsonl history.
- Optionally ingest existing AnythingLLM conversation/config exports.
