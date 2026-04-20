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

## Running An Edition

For direct foreground runs:

```bash
scripts/edition.sh run crowpi
```

To switch the already-running dev server on port `8787`:

```bash
scripts/edition.sh switch crowpi
```

CrowPi's lightweight local model stack can be bootstrapped with:

```bash
scripts/crowpi-models.sh start
```

That script ensures the entry-level GGUFs are present locally and serves:

- `8081` — `nomic-embed-text-v1.5.Q8_0.gguf`
- `8082` — `Llama-3.2-1B-Instruct-Q4_K_M.gguf` for local chat
- `8083` — `Llama-3.2-1B-Instruct-Q4_K_M.gguf` for the dedicated scan model

To inspect what is currently running:

```bash
scripts/edition.sh status
```

## Current Reality

Phase 1 is mostly edition scaffolding, with runtime capability gating now active in the UI.

- All editions still share the same backend and frontend implementation.
- The main differences today are env overlays and runtime-profile defaults.
- Sidebar tabs and selected heavyweight deck tools are now hidden based on edition capability flags.
- Backend route pruning is still pending; non-visible routes currently remain mounted.
- CrowPi and Lite are not fully productized yet; they are testable profiles on the shared codebase.
