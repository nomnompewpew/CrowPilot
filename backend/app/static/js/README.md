# Frontend JS Index

All scripts are plain browser scripts (no imports/exports). Order is important.

## Module Responsibilities

- `state.js` — global app state and helpers
- `auth.js` — login/logout/session checks
- `nav.js` — tab and navigation state
- `server.js` — server stats and log stream
- `chat.js` — chat streaming, render, approvals
- `knowledge.js` — notes ingest/search flows
- `mcp.js` — MCP server catalog and management
- `credentials.js` — vault and connector UX
- `projects.js` — workspace/project operations
- `widgets.js` — dashboard widgets
- `tasks.js` — automation and copilot task UX
- `skills.js` — skill CRUD UX
- `integrations.js` — provider integration UX
- `conversations.js` — conversation history/archive UX
- `copilot_history.js` — Copilot session history UX
- `lan.js` — LAN explorer UX
- `monaco_editor.js` — Monaco embedding helpers
- `app.js` — app bootstrap and event wiring

## Change Rule

When adding or renaming files in this folder, update:

1. `backend/app/static/index.html` script tags.
2. This index file.
3. Turn notes in `docs/agent-turn-log.md`.
