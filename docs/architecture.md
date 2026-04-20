# Pantheon Architecture

## Design Principles

- Local-first: all state lives on disk. No external services required beyond your model providers.
- OpenAI-compatible APIs throughout — no vendor lock-in.
- Single SQLite database with WAL mode and FTS5 for text search.
- Thin service layer; routers stay as thin wrappers over services.

---

## Process Layout

```
uvicorn (port 8787)
  └── FastAPI app  (backend/app/main.py)
        ├── auth_middleware            cookie session gate
        ├── asyncio lifespan
        │     ├── init providers       (copilot_proxy, local_openai, local_embed)
        │     ├── init DB + migrations
        │     └── embed_worker task    passive background embed loop
        └── routers/
              auth, chat, conversations, knowledge, mcp, widgets,
              tasks, skills, zen, integrations, credentials,
              projects, sensitive, system, wizard
```

---

## Module Map

### `app/main.py`
App factory. Lifespan starts the embed worker (`services/memory.py`) and stops it cleanly on shutdown. All 15 routers registered here.

### `app/config.py` — `Settings`
Frozen dataclass populated from env vars / `.env`. Key fields:

| Field | Env var |
|---|---|
| `copilot_base_url` | `PANTHEON_COPILOT_BASE_URL` |
| `local_base_url` | `PANTHEON_LOCAL_BASE_URL` |
| `embedding_base_url` | `PANTHEON_EMBEDDING_BASE_URL` |
| `embedding_model` | `PANTHEON_EMBEDDING_MODEL` |
| `credential_key` | `PANTHEON_CREDENTIAL_KEY` |
| `chunk_size` / `chunk_overlap` | `PANTHEON_CHUNK_SIZE` / `PANTHEON_CHUNK_OVERLAP` |

### `app/state.py` — `g` singleton
Holds `g.db` (SQLite connection) and `g.providers` (dict of named `Provider` objects). Accessed directly by routers and services.

### `app/db.py`
`init_db()` creates all tables on first run and uses `_ensure_column()` for additive schema migrations (no destructive changes). WAL + foreign keys enabled globally.

---

## Database Schema

| Table | Purpose |
|---|---|
| `conversations` | Chat sessions; soft-archived with `sidebar_state` |
| `messages` | User/assistant turns; stores provider + model used |
| `conversation_archive_chunks` | Compressed archive chunks for long conversations |
| `notes` | Knowledge entries (manual or URL-fetched) |
| `note_chunks` | Chunked note text (configurable size/overlap) |
| `note_chunks_fts` | FTS5 virtual table over `note_chunks` |
| `mcp_servers` | MCP server registry (HTTP + stdio) |
| `dashboard_widgets` | Dashboard widget configs |
| `copilot_tasks` | VS Code Copilot build-loop task queue |
| `automation_tasks` | Automation task runbooks with sensitive routing |
| `skills` | Reusable skill contracts |
| `integrations` | AI provider integration records |
| `credentials` | AES-GCM encrypted secrets |
| `projects` | Local project folder registry |
| `sensitive_profiles` | Sensitive gate routing profiles |
| `users` | Auth accounts; `setup_complete` flag for wizard |
| `sessions` | Session tokens with expiry |

`note_chunks` carries an `embedding BLOB` column (float32 packed via `struct`) updated by the embed worker. `users` carries `setup_complete INTEGER` tracked by the wizard.

---

## Service Layer (`app/services/`)

| Module | Purpose |
|---|---|
| `memory.py` | Async embed worker + cosine-similarity semantic retrieval |
| `security_gate.py` | PII scanner — calls local model with `/no_think` prefix, redacts before cloud routing |
| `zen.py` | Zen planner — builds structured prompts, extracts JSON, provides fallbacks for 7 domains |
| `credential_vault.py` | AES-GCM encrypt/decrypt for credential secrets |
| `mcp.py` | MCP server insertion with unique-name logic |
| `mcp_relay.py` | Protocol health checks for MCP servers |
| `project_runtime.py` | Filesystem tree inspection and safe command execution |
| `native_tools.py` | Tool-call dispatch for chat function-calling |
| `providers.py` | `Provider` abstraction over OpenAI-compatible HTTP |
| `serializers.py` | Consistent row-to-dict serialisation for API responses |
| `knowledge.py` | Knowledge retrieval helpers |
| `auth.py` | Session creation / validation |
| `server_stats.py` | CPU/RAM/disk stats for sidebar display |
| `log_handler.py` | Structured log capture |

---

## Memory & Embedding Pipeline

```
POST /api/notes  or  POST /api/notes/fetch-url
  │
  ├── split_into_chunks(text, size=700, overlap=120)
  ├── INSERT INTO note_chunks (FTS5 trigger fires automatically)
  └── enqueue_for_embed(chunk, note_id, chunk_index)
           │
           ▼ asyncio.Queue
      embed_worker (background task)
           │
           ├── POST /v1/embeddings  →  1024-dim float32 vector
           └── UPDATE note_chunks SET embedding = ?
```

Retrieval:
- **Keyword**: `note_chunks_fts MATCH ?` (BM25, built into SQLite FTS5)
- **Semantic**: `GET /api/memory/retrieve` — cosine similarity in pure Python against all stored embeddings

Embed queue size is exposed at `GET /api/memory/queue-size` and shown as a live badge in the sidebar.

---

## Security Gate (Sensitive Mode)

When a conversation has `sensitive_mode != 'off'`:

1. User message stored to DB immediately.
2. `security_gate.scan()` sends the message to the **local** model with `/no_think\n` prefix and a PII detection system prompt.
3. Local model returns redacted text (secrets replaced with `{{SECRET_N}}`).
4. Redacted text replaces the original in the DB and is what gets forwarded to the cloud model.
5. If the local model is unavailable, the original message is used as fallback (fail-open — review your threat model if needed).

> **Qwen3 quirk**: Qwen3-14B defaults to chain-of-thought mode and outputs to `reasoning_content` instead of `content`. Prepending `/no_think\n` to the system prompt disables this. Pantheon does this for all local-model calls.

---

## Zen Planner

`POST /api/zen/act` accepts a free-text `prompt` and a `domain` literal:

`task_create | skill_create | note_create | mcp_create | widget_create | credential_create | integration_create`

Flow:
1. `build_zen_messages()` — assembles a structured system prompt with the domain's shape contract.
2. Provider called with `temperature=0.2`, `max_tokens=900`, 8 s timeout.
3. `extract_json_object()` — strips markdown fences, parses JSON.
4. On failure: `fallback_zen_plan()` returns a safe draft record.
5. Router inserts the record into the appropriate table and returns it.

---

## Setup Wizard

`GET /api/wizard/status` runs six checks concurrently:

1. Local chat model reachable (port 8082)
2. Local embed model reachable (port 8081)
3. `gh` CLI installed
4. `gh` CLI authenticated ("Active account: true" in output)
5. Password changed from default
6. At least one knowledge note exists

`POST /api/wizard/complete` sets `users.setup_complete = 1` for the current user.

The wizard overlay appears automatically on login if any check fails and `setup_complete` is not set.

---

## Auth

Cookie-based session auth (`crowpilot_session`). `auth_middleware` blocks all paths except `/api/auth/`, `/api/wizard/`, `/static/`, and API docs. Sessions stored in `sessions` table with expiry.

---

## UI Architecture

`index.html` is the static shell served by FastAPI, with feature logic split across plain scripts in `backend/app/static/js/` (no framework, no bundler). Tabs and domain behavior are implemented by module files such as `chat.js`, `knowledge.js`, `mcp.js`, `projects.js`, and `tasks.js`, with `app.js` handling bootstrap wiring.
