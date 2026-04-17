# Pantheon Architecture (Local-First)

## Design Principles

- Keep repository artifacts lightweight and portable.
- Use OpenAI-compatible APIs to avoid lock-in.
- Persist chat/memory in local SQLite.
- Keep long-term data as markdown, jsonl, and small sqlite files.

## Core Components

- Backend: FastAPI app that exposes chat, health, and memory endpoints.
- Provider Router: routes requests to OpenAI-compatible providers:
  - `copilot_proxy` (your running VS Code Copilot Proxy on 8080)
  - `local_openai` (vLLM/LiteLLM/lmstudio/llama.cpp-style API)
- Local Store: SQLite for conversations, messages, notes, and chunk index.
- Frontend: lightweight single-page web UI served by the backend.

## Persistence Model

- `conversations`: chat sessions.
- `messages`: user/assistant turns with provider and model metadata.
- `notes`: manually added setup notes and knowledge entries.
- `note_chunks`: chunked note text.
- `note_chunks_fts`: FTS5 index for quick text retrieval.

## Why This Fits Your Goal

- You get persistent local memory immediately.
- You can use Copilot Proxy and local model servers side by side.
- Nothing depends on large binary artifacts in git.

## Near-Term Expansion Plan

1. Add embedding vectors table and cosine search.
2. Add model diagnostics dashboard with token/latency/error rates.
3. Add markdown/jsonl importers for external conversation logs.
4. Add MCP server registry and status checks.
