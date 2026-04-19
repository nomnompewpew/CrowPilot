# CrowPilot — GitHub Copilot Agent Instructions

## Who You Are

You are working on **CrowPilot / Pantheon** — a self-hosted, local-first AI hub built by one developer who moves fast and expects you to move with them. The user is an experienced developer who prototypes aggressively, makes decisions quickly, and does not want to be asked to confirm obvious things.

Your personality, communication style, and identity are defined in `.corbin/personality/corbin-system-prompt.txt`. Read that file and embody it fully on every response. It is the canonical source — not this file.

## The Stack

- **Backend**: FastAPI 0.116.0 / Python 3.13, venv at `backend/.venv/`
- **Server**: `0.0.0.0:8787`, uvicorn with `--reload`, started via `backend/run.sh`
- **Database**: SQLite with WAL + FTS5, at `backend/data/pantheon.db`
- **Repo-local agent workspace**: `.corbin/` for personality fallback, MCP setup stubs, hardware profiles, skill seeds, and local memory/env templates
- **Frontend**: Vanilla JS + CSS, no Node.js, no bundlers, no npm — ever
  - `backend/app/static/index.html` — HTML shell
  - `backend/app/static/css/app.css` — all styles
  - `backend/app/static/js/*.js` — feature modules served by FastAPI `StaticFiles`
- **Local chat model**: `http://127.0.0.1:8082/v1` — Qwen3-14B, prefix `/no_think` for non-reasoning mode
- **Local embed model**: `http://127.0.0.1:8081/v1` — Qwen3-Embedding-0.6B, 1024-dim
- **Copilot proxy**: `http://127.0.0.1:8080/v1` — gpt-4.1 backbone
- **Scan model**: `http://127.0.0.1:8083/v1` — PII redaction

### Local Profiles

- Entry-level / Raspberry Pi defaults live in `.corbin/env/raspberry-pi.env.example`
- Hardware recommendations live in `.corbin/hardware/profiles.json`
- The repo-local MCP relay stub is `.corbin/mcp/servers.json` and points at `http://localhost:8787/mcp`

---

## Rules — Always Follow

### Git Workflow
- All work happens on the **`staging`** branch
- **At the end of every single turn**, you must:
  1. `git add -A`
  2. `git commit -m "<concise present-tense message describing what changed>"`
  3. `git push origin staging`
- Commit messages are present tense, specific: `"Add ZIM indexer progress endpoint"` not `"Updates"`
- Never push to `main` directly. Main is merged from staging only when the user says so

### Server
- The dev server **must be running** at `0.0.0.0:8787` at the end of every turn
- Check: `ss -tlnp | grep 8787`
- If not running, start it: `cd backend && source .venv/bin/activate && nohup bash run.sh > /tmp/crowpilot.log 2>&1 &`
- Wait for it to be ready before the turn ends

### Code Style
- Python: follow existing patterns in `backend/app/`. No docstrings on functions you didn't create. No type annotations added as "improvements"
- JS: vanilla ES2020, no frameworks, no `import`/`export` (not modules — loaded as plain scripts in order)
- CSS: custom properties in `:root`, no utility-first frameworks added unless explicitly asked
- Do not over-engineer. Do not add abstractions for one-off things
- No Node.js. No npm. No build steps. Ever.

### Security
- SQL params always use `?` placeholders — never f-string interpolation into queries
- The `_assert_select_only()` guard exists in `services/db_connector.py` — use it
- Passwords/secrets are stored encrypted via Fernet in `dsn_encrypted` — never plaintext
- Never return secrets in API responses

### Testing
- After any backend change, verify with `python3 -c "import app.main; print('OK')"`
- For new routes, smoke-test with `curl -s http://localhost:8787/<route>`
- Don't write unit test files unless explicitly asked

---

## Architecture Landmarks

```
backend/app/
  main.py           — FastAPI app, router registration, startup events
  db.py             — SQLite schema, all CREATE TABLE IF NOT EXISTS
  config.py         — Settings (env vars via os.getenv)
  providers.py      — Model provider registry, routing logic
  schemas.py        — Pydantic request/response models
  routers/
    auth.py         — Login, session
    chat.py         — Streaming chat, Corbin injection, passive embed enqueue
    mcp.py          — MCP server forge + relay
    tasks.py        — Copilot tasks + automation tasks
    skills.py       — Skill registry
    credentials.py  — Vault CRUD
    integrations.py — Provider integration registry
    projects.py     — Workspace management, script runner, preview
    system.py       — Server stats, LAN info, log stream
    nomad.py        — ZIM file management + embed mode toggle
    db_connections.py — External DB connectors (SELECT-only)
  services/
    corbin.py       — System prompt, Corbin personality, settings table
    memory.py       — Priority embed queue (REALTIME/BACKGROUND), overnight mode
    zim_indexer.py  — ZIM file walker + chunker
    db_connector.py — Postgres/MySQL/SQLite connector, SELECT guard
    native_tools.py — Tool implementations (semantic search, task CRUD, etc.)
backend/app/static/
  index.html        — HTML shell, links to css/ and js/
  css/app.css       — All styles
  js/
    state.js        — `el()` helper + `state` object (load first)
    auth.js         — Login/logout
    nav.js          — Tab switching, copy helper
    server.js       — Server stats + live log stream
    chat.js         — Streaming chat, stat strip, conversation rendering
    knowledge.js    — Notes, URL import, semantic search
    mcp.js          — MCP catalog + server management
    credentials.js  — Vault + connectors
    projects.js     — Workspace management
    widgets.js      — Dashboard widgets
    tasks.js        — Automation tasks
    skills.js       — Skill registry
    integrations.js — Provider integrations
    conversations.js — Conversation history, archive/delete
    app.js          — initApp(), event wiring, checkAuth() bootstrap (load last)
```

---

## Personality & Communication

- **Be brief.** 1-3 sentences for simple answers.
- **Do the work first, explain after** if at all.
- **No filler phrases.** "Here's what I did:" → just say what you did. "Great question!" → never.
- **Call out bad ideas immediately.** One sentence, specific reason, then offer the better path.
- **When in doubt, implement.** Don't ask for confirmation on obvious missing details — infer from context.
- The user has a live browser window open watching changes. Every turn should leave the app in a working, improved state.

---

## Prototyper Flow

This is a live prototyping environment:
1. User prompts
2. You implement, test, commit
3. User sees changes live via the running server
4. Repeat

At the end of every turn:
- ✅ Code works (imports clean, server responds)
- ✅ `git add -A && git commit -m "..." && git push origin staging`
- ✅ Server is running on port 8787
