# Routers Index

One router file per domain, mounted in `backend/app/main.py`.

## Router Map

- `auth.py` — authentication/session endpoints
- `chat.py` — streaming chat and sensitive approval workflow
- `conversations.py` — conversation CRUD and archive access
- `copilot_history.py` — Copilot session harvest/search/history
- `credentials.py` — vault credentials and connector launchers
- `db_connections.py` — external DB connector CRUD + query/introspection
- `integrations.py` — provider integration records and model sync
- `knowledge.py` — notes, URL fetch ingestion, search
- `lan.py` — LAN device discovery and management tools
- `mcp.py` — MCP registry, checks, relay endpoint
- `network_routers.py` — OPNsense/pfSense endpoint wrappers and snapshots
- `nomad.py` — ZIM ingestion and embed mode controls
- `projects.py` — project workspace management and runtime execution
	- includes project-scoped Copilot session discovery for resume-context workflows
- `sensitive.py` — redact/unredact preview API
- `skills.py` — skill contract CRUD
- `system.py` — health, model lists, dashboard and logs
- `tasks.py` — automation tasks and copilot tasks
- `widgets.py` — dashboard widget CRUD
- `zen.py` — natural-language planner endpoint

## Related Docs

- [../../../docs/api.md](../../../docs/api.md) — route group overview and OpenAPI usage
