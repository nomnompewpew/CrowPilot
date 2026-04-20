# Scripts Index

Utility scripts for editions and local model orchestration.

## Scripts

- `edition.sh` — run/switch/status helpers for product editions
- `crowpi-models.sh` — bootstraps and runs CrowPi local model stack
- `generate_api_matrix.py` — fetches OpenAPI JSON and writes docs endpoint matrix markdown

## Usage Quick Reference

```bash
scripts/edition.sh status
scripts/edition.sh run crowpilot-developer
scripts/edition.sh switch crowpi
scripts/crowpi-models.sh start
python3 scripts/generate_api_matrix.py --openapi-url http://127.0.0.1:8787/openapi.json --output docs/api-endpoint-matrix.md
```

Keep script usage docs synchronized with behavior changes.
