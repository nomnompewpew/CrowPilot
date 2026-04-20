# Pantheon

Pantheon is a local-first AI command centre. Everything runs on your machine — chat history, knowledge retrieval, credential vault, provider routing, and task automation — with no cloud dependency beyond the model providers you choose to wire in.

## What It Does

- **Multi-provider chat routing** — Copilot Proxy, local llama.cpp, or any OpenAI-compatible endpoint, selectable per conversation.
- **Sensitive gate** — local PII scanner (Qwen3 `/no_think` mode) redacts secrets before any prompt reaches a cloud model. Full approval flow with manual tag overrides.
- **Knowledge Lab** — paste notes, fetch URLs via Jina Reader, and get automatic FTS5 + semantic (embedding) indexing. BM25 keyword search and cosine-similarity recall run side by side.
- **Passive embed worker** — background asyncio task embeds every new knowledge chunk into 1 024-dim float32 vectors without blocking requests.
- **Zen planner** — natural-language-to-record for seven domains: tasks, skills, notes, MCP servers, widgets, credentials, and integrations.
- **Encrypted credential vault** — AES-GCM secrets stored locally; reusable via `{{cred:name}}` references across all forms.
- **Provider integrations registry** — register any OpenAI-compatible provider, store its API key via vault reference, and sync its model catalog.
- **MCP Forge** — register, validate, and manage MCP servers (HTTP and stdio transport).
- **Skills & Tasks** — define reusable skill contracts and automation task runbooks with sensitive-mode routing.
- **Projects workspace** — local folder management with filesystem tree inspection and Copilot CLI actions.
- **Setup Wizard** — runs on first login; checks all six system requirements (chat model, embed model, gh CLI, gh auth, password changed, first note) and tracks per-user completion.

## Runtime Topology

| Service | Address | Notes |
|---|---|---|
| Pantheon API + UI | `0.0.0.0:8787` | FastAPI / uvicorn |
| Copilot Proxy | `127.0.0.1:8080/v1` | model `gpt-4.1` |
| Local chat (llama.cpp) | `127.0.0.1:8082/v1` | `Qwen_Qwen3-14B-Q4_K_M.gguf` |
| Local embed (llama.cpp) | `127.0.0.1:8081/v1` | `Qwen3-Embedding-0.6B-Q8_0.gguf` — 1 024 dims |

> **Qwen3 note**: Qwen3-14B runs in thinking mode by default. Pantheon prepends `/no_think\n` to every system prompt sent to the local chat model so the response arrives in `content`, not `reasoning_content`.

llama.cpp flags (1080 Ti tuning):

```
--ctx-size 4096 --n-gpu-layers auto --flash-attn on
```

## Repo Layout

```
apps/                  # Product edition manifests + env overlays
  crowpilot-developer/
  crowpi/
  crowpilot-lite/
  crowpilot/
backend/
  app/
    main.py            # FastAPI app, lifespan, router registration
    config.py          # Settings (env vars)
    db.py              # SQLite init, schema migrations
    schemas.py         # Pydantic request/response models
    state.py           # g singleton (db, providers)
    routers/           # One file per domain endpoint group
    services/          # Business logic (memory, zen, security_gate, …)
    middleware/        # auth_middleware (session cookie)
    wizard/            # Setup wizard router
    static/            # index.html — single-page UI
  data/                # pantheon.db lives here (gitignored)
  projects/            # User project folders (gitignored)
  requirements.txt
  run.sh
docs/
  architecture.md
  integration.md
  monorepo-plan.md
packages/              # Future shared Python packages
```

## Quick Start

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in your values
bash run.sh                   # or: uvicorn app.main:app --host 0.0.0.0 --port 8787 --reload
```

Open `http://127.0.0.1:8787` — the setup wizard will walk you through the remaining checks.

## Key Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `PANTHEON_COPILOT_BASE_URL` | `http://127.0.0.1:8080/v1` | Copilot Proxy endpoint |
| `PANTHEON_COPILOT_MODEL` | `gpt-5.3-codex` | Cloud model name |
| `PANTHEON_EDITION` | `crowpilot-developer` | Product edition (`crowpilot-developer`, `crowpi`, `crowpilot-lite`, `crowpilot`) |
| `PANTHEON_LOCAL_BASE_URL` | _(empty)_ | Local chat model endpoint |
| `PANTHEON_LOCAL_MODEL` | `local-model` | Local chat model name |
| `PANTHEON_EMBEDDING_BASE_URL` | _(empty)_ | Embedding model endpoint |
| `PANTHEON_EMBEDDING_MODEL` | _(empty)_ | Embedding model name |
| `PANTHEON_EMBED_MODE` | `realtime` | Background embedding throttle mode |
| `PANTHEON_AGENT_HOME` | `../.corbin` | Repo-local Corbin workspace |
| `PANTHEON_RUNTIME_PROFILE` | `desktop` | Hardware profile hint for local defaults |
| `PANTHEON_CREDENTIAL_KEY` | _(required)_ | AES encryption key for credential vault |
| `PANTHEON_PROJECTS_ROOT` | `./projects` | Root for local project folders |
| `PANTHEON_DB_PATH` | `./data/pantheon.db` | SQLite database path |

## Corbin Workspace

CrowPilot now seeds a repo-local `.corbin/` workspace on startup for persistent agent scaffolding:

- `memory/` — local JSONL persistence targets for working-set and long-term notes
- `env/` — desktop, Raspberry Pi, and workstation env templates
- `personality/` — repo-local fallback prompt for Corbin
- `mcp/` — saved MCP endpoint definitions, including `http://localhost:8787/mcp`
- `skills/` — seed skill contracts for local automation
- `hardware/` — model recommendations by host capability tier

For entry-level hardware, start from `.corbin/env/raspberry-pi.env.example`. It keeps the dedicated PII redaction model and swaps the embedding path to a lighter CPU-friendly default so indexing can run on weaker hardware without dragging live chat down.

For monorepo edition defaults, start from one of:

- `.corbin/env/crowpilot-developer.env.example`
- `.corbin/env/crowpi.env.example`
- `.corbin/env/crowpilot-lite.env.example`
- `.corbin/env/crowpilot.env.example`

## Remote LAN Access

1. Set `PANTHEON_HOST=0.0.0.0` in `backend/.env` (already the default).
2. Restart Pantheon.
3. Open the Credentials Vault page — the Hub Access panel shows your LAN URLs.
