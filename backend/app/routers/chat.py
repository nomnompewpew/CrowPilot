from __future__ import annotations

import json
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..config import settings
from ..schemas import ChatRequest
from ..services.knowledge import fetch_memory_context
from ..state import g

router = APIRouter(prefix="/api/chat", tags=["chat"])

_PII_SYSTEM_PROMPT = (
    "You are a security scanner. "
    "Identify any sensitive data in the user message: API keys, passwords, tokens, "
    "credentials, SSNs, email addresses, phone numbers, IP addresses, server hostnames, "
    "account numbers, or any private identifiers. "
    "Replace each unique sensitive value with a numbered placeholder like "
    "{{SECRET_1}}, {{EMAIL_1}}, {{IP_1}}, etc. "
    "Return ONLY the sanitized message text with placeholders. "
    "If nothing sensitive is found, return the original text unchanged."
)


@router.post("/stream")
async def chat_stream(payload: ChatRequest):
    # ── Resolve providers ──────────────────────────────────────────────────
    if payload.secure_mode:
        local_provider = g.providers.get("local_openai")
        if not local_provider:
            raise HTTPException(
                status_code=400,
                detail="Secure mode requires a local model. Set PANTHEON_LOCAL_BASE_URL in .env.",
            )
        cloud_name = payload.cloud_provider or settings.default_provider
        cloud_provider = g.providers.get(cloud_name)
        if not cloud_provider:
            raise HTTPException(status_code=400, detail=f"Unknown cloud provider: {cloud_name}")
    else:
        provider_name = payload.provider or settings.default_provider
        provider = g.providers.get(provider_name)
        if not provider:
            raise HTTPException(status_code=400, detail=f"Unknown provider: {provider_name}")

    # ── Conversation bookkeeping ───────────────────────────────────────────
    conversation_id = payload.conversation_id
    if conversation_id is None:
        cur = g.db.execute(
            "INSERT INTO conversations(title) VALUES (?)", (payload.message[:80],)
        )
        g.db.commit()
        conversation_id = cur.lastrowid

    user_msg_cur = g.db.execute(
        "INSERT INTO messages(conversation_id, role, content) VALUES (?, ?, ?)",
        (conversation_id, "user", payload.message),
    )
    user_msg_id = user_msg_cur.lastrowid
    g.db.commit()

    history_rows = g.db.execute(
        "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC",
        (conversation_id,),
    ).fetchall()
    history = [{"role": r["role"], "content": r["content"]} for r in history_rows]

    memory_hits = 0
    if payload.use_memory:
        memories = fetch_memory_context(payload.message, limit=3)
        if memories:
            memory_hits = len(memories)
            context_text = "\n\n".join(
                f"[Memory: {m['title']}]\n{m['chunk_text']}" for m in memories
            )
            history = [
                {"role": "system", "content": f"Relevant context from your knowledge base:\n\n{context_text}"}
            ] + history

    # ── Secure mode: local PII scan before cloud ───────────────────────────
    async def secure_event_stream() -> AsyncGenerator[str, None]:
        yield "data: " + json.dumps(
            {"type": "meta", "conversation_id": conversation_id, "memory_hits": memory_hits, "secure": True}
        ) + "\n\n"
        yield "data: " + json.dumps({"type": "status", "text": "🔍 Scanning locally for sensitive data…"}) + "\n\n"

        try:
            # /no_think suppresses Qwen3 reasoning mode so output goes to content, not reasoning_content
            scanned = await local_provider.complete_chat(
                messages=[
                    {"role": "system", "content": "/no_think\n" + _PII_SYSTEM_PROMPT},
                    {"role": "user", "content": payload.message},
                ],
                max_tokens=2048,
                temperature=0.0,
            )
        except Exception as exc:
            yield "data: " + json.dumps({"type": "error", "error": f"Local scan failed: {exc}"}) + "\n\n"
            return

        # Fall back to original if local model returned nothing (e.g. thinking-only response)
        if not scanned or not scanned.strip():
            scanned = payload.message

        # Count redacted placeholders
        import re
        redacted_count = len(re.findall(r"\{\{[A-Z_]+_\d+\}\}", scanned))
        yield "data: " + json.dumps(
            {"type": "pii_scan", "redacted_count": redacted_count, "scanned_text": scanned}
        ) + "\n\n"

        # Persist redacted version so future conversation turns don't leak original
        if redacted_count:
            g.db.execute(
                "UPDATE messages SET content = ? WHERE id = ?",
                (scanned, user_msg_id),
            )
            g.db.commit()
            yield "data: " + json.dumps(
                {"type": "status", "text": f"🔒 {redacted_count} value(s) redacted. Sending to cloud…"}
            ) + "\n\n"
        else:
            yield "data: " + json.dumps(
                {"type": "status", "text": "✅ No sensitive data found. Sending to cloud…"}
            ) + "\n\n"

        # Replace last user message in history with the scanned version
        cloud_history = history[:-1] + [{"role": "user", "content": scanned}]

        assistant_parts: list[str] = []
        try:
            async for kind, token in cloud_provider.stream_chat(
                messages=cloud_history,
                model=None if payload.model == "auto" else payload.model,
                max_tokens=payload.max_tokens,
                temperature=payload.temperature,
                no_think=True,
            ):
                if kind == "content":
                    assistant_parts.append(token)
                    yield "data: " + json.dumps({"type": "token", "token": token}) + "\n\n"
                elif kind == "thinking":
                    yield "data: " + json.dumps({"type": "thinking", "token": token}) + "\n\n"

            assistant_text = "".join(assistant_parts).strip()
            g.db.execute(
                "INSERT INTO messages(conversation_id, role, content, provider, model) VALUES (?, ?, ?, ?, ?)",
                (conversation_id, "assistant", assistant_text, cloud_name, payload.model or cloud_provider.cfg.default_model),
            )
            g.db.commit()
            yield "data: " + json.dumps({"type": "done"}) + "\n\n"
        except Exception as exc:
            yield "data: " + json.dumps({"type": "error", "error": str(exc)}) + "\n\n"

    # ── Normal mode ────────────────────────────────────────────────────────
    async def event_stream() -> AsyncGenerator[str, None]:
        assistant_parts: list[str] = []

        yield "data: " + json.dumps(
            {"type": "meta", "conversation_id": conversation_id, "memory_hits": memory_hits}
        ) + "\n\n"

        # Use /no_think for local models to avoid streaming pause from reasoning tokens
        is_local = provider_name == "local_openai"

        try:
            async for kind, token in provider.stream_chat(
                messages=history,
                model=None if payload.model == "auto" else payload.model,
                max_tokens=payload.max_tokens,
                temperature=payload.temperature,
                no_think=is_local,
            ):
                if kind == "content":
                    assistant_parts.append(token)
                    yield "data: " + json.dumps({"type": "token", "token": token}) + "\n\n"
                elif kind == "thinking":
                    yield "data: " + json.dumps({"type": "thinking", "token": token}) + "\n\n"

            assistant_text = "".join(assistant_parts).strip()
            g.db.execute(
                """
                INSERT INTO messages(conversation_id, role, content, provider, model)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    "assistant",
                    assistant_text,
                    provider_name,
                    payload.model or provider.cfg.default_model,
                ),
            )
            g.db.commit()
            yield "data: " + json.dumps({"type": "done"}) + "\n\n"
        except Exception as exc:
            yield "data: " + json.dumps({"type": "error", "error": str(exc)}) + "\n\n"

    if payload.secure_mode:
        return StreamingResponse(secure_event_stream(), media_type="text/event-stream")
    return StreamingResponse(event_stream(), media_type="text/event-stream")
