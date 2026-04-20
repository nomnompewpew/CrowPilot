# Agent Turn Log

Append one section per turn. Keep this file chronological.

## 2026-04-20 00:00 (bootstrap)

### Completed
- Initialized mandatory per-turn documentation log.
- Added root-level and folder-level context index scaffolding.

### Verified
- Documentation graph links from root to core backend and docs hubs.

### Next
- Continue appending this file each turn with implementation details and forward plan.
- Keep API docs references in sync with router changes.

## 2026-04-20 Documentation Mesh + Turn Rules

### Completed
- Rewrote root [README](../README.md) to reflect current architecture and added explicit API docs workflow.
- Added root crawl map [INDEX.md](../INDEX.md) and documentation hub [README](README.md).
- Added supporting indexes: [backend/README.md](../backend/README.md), [backend/app/README.md](../backend/app/README.md), [routers index](../backend/app/routers/README.md), [services index](../backend/app/services/README.md), [static index](../backend/app/static/README.md), [frontend JS index](../backend/app/static/js/README.md), and [scripts index](../scripts/README.md).
- Added [api.md](api.md) with route-group coverage and OpenAPI/Swagger usage.
- Updated [.github/copilot-instructions.md](../.github/copilot-instructions.md) to make per-turn docs updates mandatory and linked to turn-log/playbook requirements.
- Updated FastAPI app config in [backend/app/main.py](../backend/app/main.py) to explicitly expose `/docs`, `/redoc`, and `/openapi.json`.
- Updated outdated UI architecture wording in [architecture.md](architecture.md).

### Verified
- Backend import check succeeded: `python3 -c "import app.main; print('OK')"`.
- Server is running on `0.0.0.0:8787`.
- OpenAPI endpoint confirmed: `GET /openapi.json` returns schema.

### Next
- Keep [INDEX.md](../INDEX.md) and folder index READMEs updated whenever structure changes.
- Append this turn log every turn with completed/verified/next sections.
- Add endpoint examples in [api.md](api.md) as new routes are introduced.

## 2026-04-20 API Matrix Automation

### Completed
- Added [scripts/generate_api_matrix.py](../scripts/generate_api_matrix.py) to generate a compact markdown endpoint matrix from live OpenAPI.
- Generated [api-endpoint-matrix.md](api-endpoint-matrix.md) with current endpoints from `http://127.0.0.1:8787/openapi.json`.
- Updated docs navigation and guidance in [api.md](api.md), [README](README.md), [../INDEX.md](../INDEX.md), and [../scripts/README.md](../scripts/README.md).
- Updated turn-close enforcement in [agent-turn-playbook.md](agent-turn-playbook.md) and [../.github/copilot-instructions.md](../.github/copilot-instructions.md) to require matrix regeneration when routes change.

### Verified
- Matrix generator command runs successfully and writes `docs/api-endpoint-matrix.md`.
- Current generated matrix includes 148 endpoints from live OpenAPI.
- Workspace diagnostics report no errors.

### Next
- Run matrix regeneration in any turn that adds, removes, renames, or retags routes.
- Keep auth classification rules in the generator aligned with middleware public path policy.

## 2026-04-20 VS Code Run And Debug Profiles

### Completed
- Added VS Code launch profiles for each edition in [../.vscode/launch.json](../.vscode/launch.json).
- Added profiles for CrowPilot Developer (8787), CrowPilot (8788), CrowPilot Lite (8789), and CrowPi (8790).
- Added a compound profile to run all editions together.
- Updated [../.gitignore](../.gitignore) to allow committing shared VS Code config files including [../.vscode/launch.json](../.vscode/launch.json).
- Updated [../README.md](../README.md), [../backend/README.md](../backend/README.md), and [../INDEX.md](../INDEX.md) with profile discovery and usage notes.

### Verified
- Launch configuration file exists and contains all edition-specific debug entries.
- Port assignments avoid collisions so editions can be debugged individually or together.

### Next
- If edition env overlays change, mirror those changes in [../.vscode/launch.json](../.vscode/launch.json).
- Consider adding a task profile set if you want no-debug run commands alongside debug launchers.
