from __future__ import annotations

from fastapi import APIRouter

from ..catalogs import SENSITIVE_PATTERNS
from ..schemas import SensitiveRedactApplyRequest, SensitiveRedactPreviewRequest

router = APIRouter(prefix="/api/sensitive", tags=["sensitive"])


@router.post("/redact-preview")
def sensitive_redact_preview(payload: SensitiveRedactPreviewRequest) -> dict:
    text = payload.text
    matches: list[tuple[int, int, str, str]] = []

    for kind, pattern in SENSITIVE_PATTERNS.items():
        for match in pattern.finditer(text):
            token_text = match.group(0)
            if kind == "GENERIC_SECRET" and match.lastindex and match.lastindex >= 2:
                token_text = match.group(2)
                start = match.start(2)
                end = match.end(2)
            else:
                start = match.start(0)
                end = match.end(0)
            matches.append((start, end, kind, token_text))

    for manual in payload.manual_tags:
        if manual:
            idx = text.find(manual)
            if idx != -1:
                matches.append((idx, idx + len(manual), "MANUAL_TAG", manual))

    approved: dict[str, str] = {}
    redacted = text
    dedup: list[tuple[int, int, str, str]] = []
    for start, end, kind, value in sorted(matches, key=lambda x: x[0], reverse=True):
        if any(start >= s and end <= e for s, e, _, _ in dedup):
            continue
        if value in payload.manual_untags:
            continue
        token = f"{{{kind}_{len(approved) + 1}}}"
        approved[token] = value
        redacted = redacted[:start] + token + redacted[end:]
        dedup.append((start, end, kind, value))

    return {
        "original": text,
        "redacted": redacted,
        "approved_tokens": approved,
        "detected_count": len(approved),
    }


@router.post("/unredact")
def sensitive_unredact(payload: SensitiveRedactApplyRequest) -> dict:
    text = payload.text
    for token, value in payload.approved_tokens.items():
        text = text.replace(token, value)
    return {"text": text}
