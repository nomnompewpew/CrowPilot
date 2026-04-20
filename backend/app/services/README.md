# Services Index

Service modules hold domain logic reused by routers.

## Service Map

- `agent_workspace.py` — repo-local agent workspace scaffolding
- `auth.py` — user/session auth helpers
- `copilot_session_watcher.py` — periodic Copilot session scans
- `corbin.py` — Corbin personality/system prompt assembly
- `credential_vault.py` — encrypted secret storage + retrieval
- `db_connector.py` — external DB connectors with SELECT-only guard
- `edition_profiles.py` — edition capability profile loading
- `knowledge.py` — knowledge retrieval and helpers
- `log_handler.py` — in-memory/server log stream capture
- `mcp.py` — MCP server bootstrap and persistence helpers
- `mcp_relay.py` — MCP protocol interactions and checks
- `memory.py` — embedding queue worker and retrieval
- `native_tools.py` — native tool execution for chat workflows
- `project_runtime.py` — subprocess runtime management for projects
- `projects.py` — project metadata and filesystem workflows
- `providers.py` — provider registry/loading from integrations
- `security_gate.py` — prompt redaction and sensitive-mode controls
- `serializers.py` — row serialization helpers
- `server_stats.py` — host stats collection
- `zen.py` — planner behavior and extraction
- `zim_indexer.py` — ZIM file indexing pipeline

## Notes

- Keep SQL parameterized with `?` placeholders.
- Keep secrets encrypted through vault utilities.
- Keep service functions router-agnostic when possible.
