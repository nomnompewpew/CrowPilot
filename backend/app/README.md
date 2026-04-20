# App Package Index

`backend/app/` is the FastAPI application package.

## Core Files

- `main.py` — FastAPI app setup, lifespan tasks, router registration
- `config.py` — environment-backed settings
- `db.py` — SQLite schema initialization and migrations
- `schemas.py` — request and response models
- `state.py` — global runtime state singleton

## Subpackages

- [routers/README.md](routers/README.md) — API endpoints by domain
- [services/README.md](services/README.md) — domain logic modules
- `middleware/` — request middleware (auth/session gate)
- [static/README.md](static/README.md) — browser UI assets
- `wizard/` — setup-wizard API

## Lifespan Tasks

- Seed and normalize MCP records
- Reload provider integrations
- Seed default user
- Start embed worker
- Start Copilot session watcher
