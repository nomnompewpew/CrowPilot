from __future__ import annotations

import re

from ..providers import OpenAICompatProvider

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

_PLACEHOLDER_RE = re.compile(r"\{\{[A-Z_]+_\d+\}\}")


async def scan_message(provider: OpenAICompatProvider, text: str) -> tuple[str, int]:
    """
    Run PII scan on `text` using the given local provider.

    Returns:
        (scanned_text, redacted_count)

    Falls back to the original text (0 redactions) if the local model is
    unreachable or returns an empty response.
    """
    try:
        scanned = await provider.complete_chat(
            messages=[
                # /no_think suppresses Qwen3 chain-of-thought so output lands in `content`
                {"role": "system", "content": "/no_think\n" + _PII_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            max_tokens=len(text) * 2 + 256,
            temperature=0.0,
        )
    except Exception:
        return text, 0

    if not scanned or not scanned.strip():
        return text, 0

    count = len(_PLACEHOLDER_RE.findall(scanned))
    return scanned, count
