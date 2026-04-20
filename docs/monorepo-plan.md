# Pantheon Monorepo Plan

## Goal

Turn Pantheon into a multi-app Python monorepo where CrowPilot Developer is the upstream playground and product editions inherit from it.

## Edition Strategy

| Edition | Hardware Target | Runtime Profile | Defaults |
|---|---|---|---|
| CrowPilot Developer | personal lab / high-flex dev machine | `developer` | all capabilities on, realtime embedding |
| CrowPi | Raspberry Pi / Orange Pi | `raspberry-pi` | lightweight embedding model, overnight embedding |
| CrowPilot Lite | CPU-only laptops/desktops | `lite` | lightweight embedding model, realtime embedding |
| CrowPilot | 8GB+ VRAM desktops and Jetson | `workstation` | higher-quality embedding model, realtime embedding |

## Monorepo Layout (Phase 1)

- `apps/` edition manifests and per-edition backend env overlays
- `packages/` future shared Python package extraction target
- `backend/` current shared runtime implementation (single codebase today)

## What Was Implemented

1. Added `apps/` edition folders with `app.json` manifests.
2. Added `apps/<edition>/backend.env` overlays.
3. Updated `backend/run.sh` to auto-load edition overlay using `PANTHEON_EDITION`.
4. Added `PANTHEON_EDITION` in backend settings.
5. Added edition/runtime metadata to dashboard summary API.
6. Extended agent workspace profile seeding to include `developer` and `lite` plus edition env templates.

## Next Extraction Phases

1. Move shared backend modules into `packages/crowpilot_core` and keep thin app entrypoints.
2. Add edition capability flags table in DB (`edition_features`).
3. Gate routers/features by edition config.
4. Add per-edition static branding and onboarding copy.
5. Add release scripts that package each edition independently.
