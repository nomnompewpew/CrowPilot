# Pantheon

Pantheon is a local-first AI command center for chat workflows, MCP automation, knowledge indexing, provider routing, and encrypted credential handling.

## Current Product Surface

- Multi-provider chat routing (Copilot proxy, local OpenAI-compatible chat, external integrations)
- Sensitive gate with local redaction/approval flow
- Knowledge ingestion via notes and URL fetch, with FTS + embedding retrieval
- Background embedding worker and queue observability
- MCP Forge registry and relay endpoints
- Skills, automation tasks, dashboard widgets, and projects workspace tooling
- Encrypted credential vault and connector launch support
- Setup wizard checks for local model/runtime readiness
- LAN tools for local network device workflows

## Runtime Topology

| Service | Address | Notes |
|---|---|---|
| Pantheon API + UI | `0.0.0.0:8787` | FastAPI / uvicorn |
| OpenAPI Schema | `http://127.0.0.1:8787/openapi.json` | machine-readable endpoint schema |
| Swagger UI | `http://127.0.0.1:8787/docs` | interactive API testing |
| ReDoc | `http://127.0.0.1:8787/redoc` | API reference rendering |
| Copilot Proxy | `127.0.0.1:8080/v1` | default cloud backbone |
| Local chat (llama.cpp) | `127.0.0.1:8082/v1` | default local chat endpoint |
| Local embed (llama.cpp) | `127.0.0.1:8081/v1` | default local embedding endpoint |

## Documentation Graph

Start with these indexes:

- [INDEX.md](INDEX.md) — root crawl map for agents and humans
- [docs/README.md](docs/README.md) — docs hub
- [docs/api.md](docs/api.md) — API group map and OpenAPI workflow
- [backend/README.md](backend/README.md) — backend runtime index
- [backend/app/README.md](backend/app/README.md) — app package index

Turn continuity docs:

- [docs/agent-turn-playbook.md](docs/agent-turn-playbook.md)
- [docs/agent-turn-log.md](docs/agent-turn-log.md)

## Repo Layout

```
apps/                  # edition manifests and backend env overlays
backend/               # FastAPI app, static UI, services, routers
docs/                  # architecture, integration, API, planning, turn logs
packages/              # future shared package extraction target
scripts/               # edition/model helper scripts
```

## Quick Start

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
bash run.sh
```

Open `http://127.0.0.1:8787`.

CrowPi bootstrap:

```bash
scripts/crowpi-models.sh start
PANTHEON_EDITION=crowpi bash backend/run.sh
```

## Key Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `PANTHEON_EDITION` | `crowpilot-developer` | active product edition |
| `PANTHEON_HOST` | `0.0.0.0` | bind host |
| `PANTHEON_PORT` | `8787` | bind port |
| `PANTHEON_DB_PATH` | `./data/pantheon.db` | SQLite path |
| `PANTHEON_COPILOT_BASE_URL` | `http://127.0.0.1:8080/v1` | cloud provider endpoint |
| `PANTHEON_LOCAL_BASE_URL` | _(empty)_ | local chat endpoint |
| `PANTHEON_EMBEDDING_BASE_URL` | _(empty)_ | embedding endpoint |
| `PANTHEON_CREDENTIAL_KEY` | _(required)_ | credential vault key |
| `PANTHEON_PROJECTS_ROOT` | `./projects` | project workspace root |

## API Documentation Workflow

1. Build or modify endpoint in `backend/app/routers/`.
2. Open Swagger at `/docs`.
3. Validate request/response shape with live calls.
4. Keep [docs/api.md](docs/api.md) and [docs/agent-turn-log.md](docs/agent-turn-log.md) current.

## VS Code Run And Debug Profiles

Run and Debug profiles are available in [.vscode/launch.json](.vscode/launch.json):

- Pantheon: CrowPilot Developer (8787)
- Pantheon: CrowPilot (8788)
- Pantheon: CrowPilot Lite (8789)
- Pantheon: CrowPi (8790)
- Pantheon: Run All Editions (8787-8790)

Use the Run and Debug panel, choose a profile, and press F5.

Each profile runs Uvicorn from the backend folder with the edition-specific environment values.

Run-only (no debugger attached) profiles are available as VS Code tasks in [.vscode/tasks.json](.vscode/tasks.json):

- Pantheon: Run CrowPilot Developer (8787)
- Pantheon: Run CrowPilot (8788)
- Pantheon: Run CrowPilot Lite (8789)
- Pantheon: Run CrowPi (8790)
- Pantheon: Run All Editions (No Debug)

Use `Tasks: Run Task` from the command palette to launch them.

## Projects Prototyper (In-App)

The Projects tab now supports a full project-scoped prototyper loop:

- Workspace-specific chat with project context injection
- Script runtime launcher + live runtime logs
- Direct command execution in the selected project folder
- Copilot CLI runner scoped to selected folder
- Resume-context support from archived Copilot sessions linked to the project

For command and Copilot execution, enable the Projects toggle:

- `Allow command/script/Copilot CLI execution for selected workspace`
