# Static UI Index

FastAPI serves this folder as static frontend assets.

## Contents

- `index.html` — HTML shell
- `css/app.css` — all application styling
- `js/` — feature scripts loaded as plain scripts
- `agents/` — bundled helper binaries by platform

## Frontend Model

- Vanilla JS only
- No bundler
- No npm
- Script order matters

See [js/README.md](js/README.md) for module responsibilities and load order expectations.
