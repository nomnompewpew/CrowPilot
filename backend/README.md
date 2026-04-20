# Backend Index

Backend runtime entrypoint and source map.

## Runtime

- Start script: `run.sh`
- Requirements: `requirements.txt`
- App package: `app/`
- Runtime data path: `data/`
- Project workspaces: `projects/`

## Navigation

- [app/README.md](app/README.md) — architecture and composition
- [app/routers/README.md](app/routers/README.md) — route catalog
- [app/services/README.md](app/services/README.md) — service contracts
- [app/static/README.md](app/static/README.md) — frontend static assets served by FastAPI

## Server Contract

- Host/port expected in local dev: `0.0.0.0:8787`
- App object: `app.main:app`
- OpenAPI docs: `/docs`, `/redoc`, `/openapi.json`

## VS Code Debugging

Use the Run and Debug profiles in [../.vscode/launch.json](../.vscode/launch.json):

- CrowPilot Developer on `8787`
- CrowPilot on `8788`
- CrowPilot Lite on `8789`
- CrowPi on `8790`
- Compound profile to run all editions together
