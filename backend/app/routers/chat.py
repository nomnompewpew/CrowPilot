from __future__ import annotations

import asyncio
import json
import secrets
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..config import settings
from ..schemas import ChatRequest
from ..services.corbin import get_system_prompt
from ..services.knowledge import fetch_memory_context
from ..services.memory import enqueue_message, REALTIME, BACKGROUND
from ..services.security_gate import scan_and_redact
from ..state import g

router = APIRouter(prefix="/api/chat", tags=["chat"])

# ── Pending approval registry ─────────────────────────────────────────────────
# Maps short-lived token → asyncio.Event. Set by POST /approve/{token}.
# Entries are removed when the stream completes or times out.
_pending_approvals: dict[str, asyncio.Event] = {}

# How long (seconds) the stream waits for the user to approve redactions.
# After this the message is cancelled, NOT sent.
_APPROVAL_TIMEOUT = 60.0


@router.post("/stream/approve/{token}")
async def approve_redaction(token: str) -> dict:
    """UI calls this after the user reviews and accepts the redaction preview."""
    event = _pending_approvals.get(token)
    if not event:
        raise HTTPException(status_code=404, detail="No pending redaction for this token")
    event.set()
    return {"ok": True}


@router.post("/stream/reject/{token}")
async def reject_redaction(token: str) -> dict:
    """UI calls this when the user cancels after reviewing the redaction preview."""
    event = _pending_approvals.pop(token, None)
    if event:
        event.set()  # unblocks the stream so it can exit cleanly
    return {"ok": True}


# ── Helper: run scan and emit preview event ───────────────────────────────────

async def _scan_and_emit(
    text: str,
    user_msg_id: int,
    stream_gen: list,  # accumulator; yields are appended here
) -> tuple[str, str | None]:
    """
    Run the two-stage pipeline, persist the redacted text, and return
    (safe_text, approval_token_or_None).

    approval_token is non-None only when redactions were found — the caller
    must then pause the stream, emit the review event, and wait for approval.
    """
    result = await scan_and_redact(text)

    # Always persist the safest version immediately
    if result.count > 0:
        g.db.execute(
            "UPDATE messages SET content = ? WHERE id = ?",
            (result.text, user_msg_id),
        )
        g.db.commit()

    # Build the event payload the UI will render
    scan_event = {
        "type": "redaction_review",
        "count": result.count,
        "stage": result.stage,
        "scan_skipped": result.scan_skipped,
        "redacted_text": result.text,
        # Only send an excerpt of original — enough for the diff UI, not a full echo
        "original_excerpt": result.original[:500] if result.count > 0 else None,
    }

    approval_token = None
    if result.count > 0:
        approval_token = secrets.token_urlsafe(16)
        scan_event["approval_token"] = approval_token

    return result.text, approval_token, scan_event


@router.post("/stream")
async def chat_stream(payload: ChatRequest):
    # ── Resolve providers ──────────────────────────────────────────────────
    # Any route that ends up calling a cloud model goes through the scan gate.
    # "local_openai" routes are exempt — nothing leaves the machine.

    cloud_name = payload.cloud_provider or payload.provider or settings.default_provider
    provider_name = cloud_name

    provider = g.providers.get(provider_name)
    if not provider:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider_name}")

    is_local_only = provider_name == "local_openai"
    needs_scan = not is_local_only  # scan everything going to cloud

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

    # Passively embed the user message at realtime priority so it's retrievable
    # as soon as the next conversation turn.
    enqueue_message(payload.message, "message", user_msg_id, 0, REALTIME)

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

    # Prepend Corbin's system prompt — always first, regardless of provider.
    # Memory context (above) sits between Corbin and the conversation history
    # so the model sees: [Corbin identity] → [memory context] → [history].
    corbin_prompt = {"role": "system", "content": get_system_prompt()}
    history = [corbin_prompt] + history

    # ── Stream generator ───────────────────────────────────────────────────
    async def event_stream() -> AsyncGenerator[str, None]:
        approval_token = None

        yield "data: " + json.dumps({
            "type": "meta",
            "conversation_id": conversation_id,
            "memory_hits": memory_hits,
            "secure": needs_scan,
        }) + "\n\n"

        # ── Gate: scan all cloud-bound messages ────────────────────────────
        safe_text = payload.message
        if needs_scan:
            yield "data: " + json.dumps({"type": "status", "text": "🔍 Scanning for secrets…"}) + "\n\n"
            safe_text, approval_token, scan_event = await _scan_and_emit(
                payload.message, user_msg_id, []
            )
            yield "data: " + json.dumps(scan_event) + "\n\n"

            if scan_event["scan_skipped"] and scan_event["count"] == 0:
                # Regex clean, model unavailable — emit warning and proceed
                yield "data: " + json.dumps({
                    "type": "status",
                    "text": "⚠️ Scan model unavailable — regex scan only. Proceeding.",
                }) + "\n\n"

            elif scan_event["count"] > 0:
                # Redactions found — pause and wait for user approval
                event = asyncio.Event()
                _pending_approvals[approval_token] = event
                yield "data: " + json.dumps({
                    "type": "status",
                    "text": f"🔒 {scan_event['count']} value(s) redacted — review and approve to send.",
                }) + "\n\n"
                try:
                    await asyncio.wait_for(event.wait(), timeout=_APPROVAL_TIMEOUT)
                    # reject_redaction() pops the token before setting the event.
                    # approve_redaction() sets the event and leaves the token in place.
                    # So: token missing → user rejected; token present → user approved.
                    was_approved = approval_token in _pending_approvals
                    _pending_approvals.pop(approval_token, None)
                    if not was_approved:
                        yield "data: " + json.dumps({
                            "type": "cancelled",
                            "reason": "user_rejected",
                        }) + "\n\n"
                        return
                    yield "data: " + json.dumps({"type": "status", "text": "✅ Approved — sending redacted message…"}) + "\n\n"
                except asyncio.TimeoutError:
                    _pending_approvals.pop(approval_token, None)
                    yield "data: " + json.dumps({
                        "type": "cancelled",
                        "reason": "approval_timeout",
                        "message": "Redaction review timed out. Message was not sent.",
                    }) + "\n\n"
                    return

            else:
                yield "data: " + json.dumps({"type": "status", "text": "✅ No secrets detected — sending."}) + "\n\n"

        # ── Send to provider ───────────────────────────────────────────────
        # Replace last history entry with the safe (possibly redacted) version
        send_history = history[:-1] + [{"role": "user", "content": safe_text}]

        assistant_parts: list[str] = []
        try:
            async for kind, token in provider.stream_chat(
                messages=send_history,
                model=None if payload.model == "auto" else payload.model,
                max_tokens=payload.max_tokens,
                temperature=payload.temperature,
                no_think=is_local_only,
            ):
                if kind == "content":
                    assistant_parts.append(token)
                    yield "data: " + json.dumps({"type": "token", "token": token}) + "\n\n"
                elif kind == "thinking":
                    yield "data: " + json.dumps({"type": "thinking", "token": token}) + "\n\n"

            assistant_text = "".join(assistant_parts).strip()
            asst_cur = g.db.execute(
                "INSERT INTO messages(conversation_id, role, content, provider, model) VALUES (?, ?, ?, ?, ?)",
                (conversation_id, "assistant", assistant_text, provider_name,
                 payload.model or provider.cfg.default_model),
            )
            asst_msg_id = asst_cur.lastrowid
            g.db.commit()

            # Passively embed the assistant response at background priority —
            # it's less urgent than the user's own words.
            if assistant_text:
                enqueue_message(assistant_text, "message", asst_msg_id, 0, BACKGROUND)

            yield "data: " + json.dumps({"type": "done"}) + "\n\n"
        except Exception as exc:
            yield "data: " + json.dumps({"type": "error", "error": str(exc)}) + "\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

