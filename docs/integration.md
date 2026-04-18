# Integration Guide

## Verified Runtime Ports

| Port | Service | Model |
|---|---|---|
| 8080 | Copilot Proxy (VS Code) | `gpt-4.1` |
| 8081 | llama.cpp embed server | `Qwen3-Embedding-0.6B-Q8_0.gguf` — 1 024 dims |
| 8082 | llama.cpp chat server | `Qwen_Qwen3-14B-Q4_K_M.gguf` |
| 8787 | Pantheon API + UI | — |

Port `8000` (Chroma) is not used by Pantheon and is not an inference endpoint.

---

## `.env` Configuration

Copy `backend/.env.example` to `backend/.env` and set:

```env
# ── Core ─────────────────────────────────────────────────────
PANTHEON_HOST=0.0.0.0
PANTHEON_PORT=8787
PANTHEON_DB_PATH=./data/pantheon.db

# ── Copilot Proxy (cloud backbone) ───────────────────────────
PANTHEON_DEFAULT_PROVIDER=copilot_proxy
PANTHEON_COPILOT_BASE_URL=http://127.0.0.1:8080/v1
PANTHEON_COPILOT_MODEL=gpt-4.1
PANTHEON_COPILOT_API_KEY=

# ── Local chat model (llama.cpp on port 8082) ─────────────────
PANTHEON_LOCAL_BASE_URL=http://127.0.0.1:8082/v1
PANTHEON_LOCAL_MODEL=Qwen_Qwen3-14B-Q4_K_M.gguf
PANTHEON_LOCAL_API_KEY=

# ── Local embedding model (llama.cpp on port 8081) ────────────
PANTHEON_EMBEDDING_BASE_URL=http://127.0.0.1:8081/v1
PANTHEON_EMBEDDING_MODEL=Qwen3-Embedding-0.6B-Q8_0.gguf

# ── Knowledge chunking ────────────────────────────────────────
PANTHEON_CHUNK_SIZE=700
PANTHEON_CHUNK_OVERLAP=120

# ── Security ──────────────────────────────────────────────────
# Generate: python3 -c "import secrets; print(secrets.token_hex(32))"
PANTHEON_CREDENTIAL_KEY=<32-byte hex key>

# ── Projects ──────────────────────────────────────────────────
PANTHEON_PROJECTS_ROOT=./projects
PANTHEON_COPILOT_CLI_COMMAND=gh
```

---

## Qwen3 Local Model Notes

Qwen3-14B runs in **thinking mode** by default: chain-of-thought output goes to `reasoning_content`, leaving `content` empty. Pantheon prepends `/no_think\n` to every system prompt sent to the local chat model to disable this. If you swap to a different local model, remove that prefix from `services/security_gate.py` and `services/zen.py`.

llama.cpp flags confirmed working on a 1080 Ti:

```bash
./llama-server \
  --model /path/to/Qwen_Qwen3-14B-Q4_K_M.gguf \
  --port 8082 \
  --host 0.0.0.0 \
  --ctx-size 4096 \
  --n-gpu-layers auto \
  --flash-attn on
```

Embed server (no GPU required for 0.6B):

```bash
./llama-server \
  --model /path/to/Qwen3-Embedding-0.6B-Q8_0.gguf \
  --port 8081 \
  --host 0.0.0.0 \
  --embedding
```

---

## Quick Health Checks

```bash
# Copilot Proxy
curl -s http://127.0.0.1:8080/v1/models | python3 -m json.tool

# Local chat model
curl -s http://127.0.0.1:8082/v1/models

# Local embed model (1024-dim expected)
curl -s http://127.0.0.1:8081/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen3-Embedding-0.6B-Q8_0.gguf","input":"test"}' \
  | python3 -c "import sys,json; e=json.load(sys.stdin)['data'][0]['embedding']; print('dims:', len(e))"

# Pantheon health
curl -s http://127.0.0.1:8787/api/health | python3 -m json.tool
```

---

## Setup Wizard

On first login the wizard overlay appears and runs six checks:

1. **Local chat model** — HTTP probe to port 8082
2. **Local embed model** — HTTP probe to port 8081
3. **gh CLI installed** — `gh --version`
4. **gh CLI authenticated** — `gh auth status` — pass condition: "Active account: true" (keyring warning is harmless)
5. **Password changed** — compared against the default; change it in Settings
6. **First knowledge note** — at least one note in the DB

"Mark Complete & Close" calls `POST /api/wizard/complete` to suppress the overlay on future logins.

---

## Common Local Model Failure Modes

| Symptom | Likely cause |
|---|---|
| `/v1/models` returns 404 | Server exposes `/models` not `/v1/models` — check your llama.cpp version |
| `content` field empty | Qwen3 thinking mode — ensure `/no_think` prefix in system prompt |
| Auth error on local endpoint | LiteLLM/vLLM may require a bearer token; set `PANTHEON_LOCAL_API_KEY` |
| Model name mismatch | Request alias differs from loaded model file name |
| Server up but inference hangs | CUDA/ROCm runtime mismatch; check `nvidia-smi` and llama.cpp GPU layers log |
| Embed dimensions wrong | Embedding model changed; update `PANTHEON_EMBEDDING_MODEL` and clear old blobs |

---

## Git-Friendly Data Strategy

**Track in git:**
- markdown notes and runbooks
- `backend/requirements.txt`, `backend/run.sh`
- `docs/`

**Do not track:**
- `backend/data/` — SQLite DB and WAL/SHM files
- `backend/projects/` — local project folders
- `backend/.env` — secrets
- model binaries
- `__pycache__/`

A `.gitignore` entry for `*.db`, `*.db-wal`, `*.db-shm`, `.env`, and `projects/` covers all of the above.

---

## Jina Reader Integration

`POST /api/notes/fetch-url` proxies through the public Jina Reader API to convert any URL to clean Markdown and index it automatically.

```json
{ "url": "https://example.com/docs", "title": "optional override" }
```

For a web search instead of a direct fetch:

```json
{ "url": "my search query", "search": true }
```

Optionally pass `"api_key"` for your Jina API key to avoid rate limits. The title is auto-extracted from the first H1 heading if not provided.
