# Pantheon Apps Monorepo

This folder defines product editions that share the same core CrowPilot codebase.

## Editions

| Edition | Folder | Primary Target | Runtime Profile | Positioning |
|---|---|---|---|---|
| CrowPilot Developer | `apps/crowpilot-developer` | personal lab / feature playground | `developer` | all features and tooling enabled for fast iteration |
| CrowPi | `apps/crowpi` | Raspberry Pi / Orange Pi | `raspberry-pi` | lowest footprint with CPU-first defaults |
| CrowPilot Lite | `apps/crowpilot-lite` | older laptops / CPU-only desktops | `lite` | balanced experience with constrained hardware |
| CrowPilot | `apps/crowpilot` | discrete GPU or Jetson-class systems | `workstation` | full feature profile with stronger local quality |

## What Lives In Each Edition Folder

Each edition stores:

- `app.json` - manifest and product metadata
- `backend.env` - edition-specific backend environment overlay loaded by `backend/run.sh`

The shared implementation currently stays in `backend/` and `frontend/`. As modules are extracted, shared code will move into `packages/` and edition-specific deltas will remain under `apps/<edition>/`.
