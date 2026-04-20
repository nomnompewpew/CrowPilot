# Documentation Hub

This folder is the canonical docs hub. Use [../INDEX.md](../INDEX.md) for root traversal.

## Core Docs

- [architecture.md](architecture.md) — system architecture and data flow
- [integration.md](integration.md) — runtime integration and environment setup
- [api.md](api.md) — API route catalog and OpenAPI docs usage
- [master-plan.md](master-plan.md) — stabilization and refactor strategy
- [monorepo-plan.md](monorepo-plan.md) — edition rollout strategy

## Agent Execution Docs

- [agent-turn-playbook.md](agent-turn-playbook.md) — mandatory end-of-turn process
- [agent-turn-log.md](agent-turn-log.md) — append per-turn changes + future plans

## How To Keep Docs Current

1. Update implementation docs in the folder you changed.
2. Update [agent-turn-log.md](agent-turn-log.md) with what changed and what happens next.
3. If new docs were created or moved, update [../INDEX.md](../INDEX.md) and this file.
