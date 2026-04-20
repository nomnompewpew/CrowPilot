# API Documentation Guide

Pantheon exposes APIs through FastAPI routers in `backend/app/routers/`.

## Live API Docs

- Swagger UI: `/docs`
- ReDoc: `/redoc`
- OpenAPI JSON: `/openapi.json`

Swagger is the fastest way to inspect payload schemas for new endpoint work.

## Route Groups

- `auth` — `/api/auth/*`
- `chat` — `/api/chat/*`
- `conversations` — `/api/conversations/*`
- `copilot-history` — `/api/copilot-history/*`
- `credentials` — `/api/credentials/*`
- `db_connections` — `/api/db-connections/*`
- `integrations` — `/api/integrations/*`
- `knowledge` — `/api/notes/*`
- `lan` — `/api/lan/*`
- `mcp` — `/api/mcp/*` and `/mcp`
- `network_routers` — `/api/routers/*`
- `nomad` — `/api/nomad/*`
- `projects` — `/api/projects/*`
- `sensitive` — `/api/sensitive/*`
- `skills` — `/api/skills/*`
- `system` — `/api/health`, `/api/system/*`, `/api/models`, `/api/hub/access`, `/api/dashboard/summary`
- `tasks` — `/api/tasks/*`, `/api/copilot/tasks*`, `/api/copilot/blueprint`
- `widgets` — `/api/widgets/*`
- `wizard` — `/api/wizard/*`
- `zen` — `/api/zen/*`

## Workflow For New Endpoints

1. Add route in the correct router file under `backend/app/routers/`.
2. Use request/response models from `backend/app/schemas.py` where applicable.
3. Verify route appears in `/docs`.
4. Add curl smoke check in your turn notes.
5. Update [agent-turn-log.md](agent-turn-log.md) with behavior and follow-ups.

## Authentication Notes

Public paths are controlled by `backend/app/middleware/auth.py`.
API docs are intentionally public:

- `/docs`
- `/redoc`
- `/openapi.json`

Keep docs endpoints public so setup and debugging remain easy during local-first development.
