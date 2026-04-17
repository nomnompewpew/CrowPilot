# Integration Guide

## Confirm Copilot Proxy

- Expected endpoint: `http://127.0.0.1:8080/v1`
- Probe: `GET /v1/models`
- In this environment, port 8080 is healthy and returns model catalog.

## Configure Pantheon

Copy `backend/.env.example` to `backend/.env` and set:

- `PANTHEON_DEFAULT_PROVIDER=copilot_proxy`
- `PANTHEON_COPILOT_BASE_URL=http://127.0.0.1:8080/v1`
- `PANTHEON_COPILOT_MODEL=gpt-4.1`

Optional local model backend:

- `PANTHEON_LOCAL_BASE_URL=http://127.0.0.1:8082/v1`
- `PANTHEON_LOCAL_MODEL=Qwen_Qwen3-14B-Q4_K_M.gguf`
- `PANTHEON_LOCAL_API_KEY=` (blank)

Observed in this environment:

- Port `8000` is serving `chroma-frontend` OpenAPI and returns `404` for `/v1/models`.
- This means `8000` is not your model inference endpoint.
- Port `8082` serves local llama.cpp OpenAI-compatible inference for Pantheon and AnythingLLM.
- Port `8081` remains dedicated to embeddings.

llama.cpp service notes (fixed state):

- Broken unit was `llama-server.service` (not Ollama).
- Fixed flag syntax for flash attention, corrected port conflict, and reduced GPU pressure.
- Current tuning: `--ctx-size 4096`, `--n-gpu-layers auto`, `--flash-attn on`.

## Common Local Model Failure Modes

1. Wrong base path
- Some servers expose `/v1/models`, others only `/models`.

2. Auth mismatch
- LiteLLM/vLLM may require bearer token or custom header.

3. Model name mismatch
- Requesting alias not loaded by server.

4. Tokenizer/model startup failure
- Server is listening but worker did not finish loading model.

5. CUDA/ROCm runtime mismatch
- Backend process starts but inference fails on first request.

## Quick Check Sequence

1. `curl -s http://127.0.0.1:<port>/v1/models`
2. If empty/fail, try `curl -s http://127.0.0.1:<port>/models`
3. Send minimal non-stream completion request.
4. Check backend logs for model-loading exceptions.

## Git-Friendly Data Strategy

Track:
- markdown notes
- small sqlite snapshots
- jsonl conversation exports

Do not track:
- model binaries
- large embeddings blobs
- volatile WAL/SHM temp files
