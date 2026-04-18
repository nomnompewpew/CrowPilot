"""
services/security_gate.py — Two-stage mandatory PII/secret redaction pipeline.

Stage 1 — Regex (always runs, synchronous, zero cost):
  High-confidence pattern matching for known secret formats: OpenAI keys,
  GitHub tokens, AWS keys, generic key=value patterns, etc.

Stage 2 — Local model scan (async):
  Recommended: OpenPipe/PII-Redact-General (Llama 3.2 1B fine-tune).
  Purpose-built for credential/secret detection — SSNs 100%, IPs 99.8%,
  API keys/passwords F1≈1.00. Runs on CPU-only hardware (Pi/Orange Pi)
  at ~128k context. Falls back to the local chat model if not configured.

  GGUF download: https://huggingface.co/OpenPipe/PII-Redact-General
  Serve:  llama-server -m PII-Redact-General-Q8_0.gguf --port 8083 -c 8192
  Set:    PANTHEON_SCAN_BASE_URL=http://127.0.0.1:8083/v1
          PANTHEON_SCAN_MODEL=PII-Redact-General-Q8_0.gguf

  Output format: PII-Redact outputs [TYPE_LABEL] bracket notation
  (e.g. [EMAIL_ADDRESS], [PASSWORD], [API_KEY]). The normalizer at the
  edge converts these to our internal {{TYPE_N}} placeholder format so
  the rest of the system (DB, UI, approval flow) stays consistent.

  Fine-tuned models do NOT use a system prompt — sending one can hurt
  accuracy. A system prompt is only used when falling back to the general
  local chat model (no dedicated scan model configured).

Design principles:
  - Never skip Stage 1. It costs nothing and catches obvious tokens.
  - scan_skipped=True means Stage 2 was unreachable. The chat stream
    emits a warning and does NOT silently proceed.
  - The user always sees the redacted text before approving. The review
    step is mandatory — it builds awareness that secrets don't belong
    in prompts, not just for security but to avoid leaking company
    context into AI training pipelines.
"""
from __future__ import annotations

import re
from typing import NamedTuple

from ..catalogs import SENSITIVE_PATTERNS
from ..config import settings
from ..providers import OpenAICompatProvider

# ── Prompt ────────────────────────────────────────────────────────────────────

_SCAN_SYSTEM_PROMPT = (
    "You are a security scanner with one job: find secrets in text and replace them.\n"
    "Secrets include: API keys, passwords, tokens, bearer credentials, private keys, "
    "connection strings, SSNs, account numbers, internal server hostnames, IP addresses "
    "that look like internal infrastructure, and any value a user explicitly calls a "
    "password, secret, key, or token.\n"
    "Rules:\n"
    "- Replace each unique sensitive value with {{SECRET_1}}, {{SECRET_2}}, etc.\n"
    "- Use semantic type prefixes where obvious: {{PASSWORD_1}}, {{API_KEY_1}}, "
    "{{EMAIL_1}}, {{IP_1}}, {{SSN_1}}.\n"
    "- Do NOT redact public URLs, generic words, or values that are clearly not secrets.\n"
    "- Return ONLY the sanitized text. No explanation. No commentary.\n"
    "- If nothing is sensitive, return the original text exactly as-is."
)

# Prepend to disable Qwen3 chain-of-thought (no-op on other models, safe to always include)
_NO_THINK = "/no_think\n"

_PLACEHOLDER_RE = re.compile(r"\{\{[A-Z_]+_\d+\}\}")

# ── Output normalizer ─────────────────────────────────────────────────────────
# OpenPipe PII-Redact models output [TYPE_LABEL] bracket notation rather than
# our {{TYPE_N}} format. This map covers all entity types in the AI4Privacy
# dataset that PII-Redact-General was trained on.
_BRACKET_LABEL_MAP: dict[str, str] = {
    "email": "EMAIL",
    "email_address": "EMAIL",
    "emailaddress": "EMAIL",
    "password": "PASSWORD",
    "pass": "PASSWORD",
    "api_key": "API_KEY",
    "apikey": "API_KEY",
    "private_key": "PRIVATE_KEY",
    "secret_key": "SECRET",
    "secret": "SECRET",
    "token": "TOKEN",
    "bearer_token": "TOKEN",
    "access_token": "TOKEN",
    "refresh_token": "TOKEN",
    "two_factor": "TOKEN",
    "2fa": "TOKEN",
    "ssn": "SSN",
    "social_security": "SSN",
    "social_security_number": "SSN",
    "ip": "IP",
    "ip_address": "IP",
    "ipaddress": "IP",
    "ipv4": "IP",
    "ipv6": "IP",
    "address": "ADDRESS",
    "street_address": "ADDRESS",
    "username": "USERNAME",
    "phone": "PHONE",
    "phone_number": "PHONE",
    "phonenumber": "PHONE",
    "credit_card": "CREDIT_CARD",
    "creditcard": "CREDIT_CARD",
    "card_number": "CREDIT_CARD",
    "passport": "PASSPORT",
    "passport_number": "PASSPORT",
    "license": "LICENSE",
    "driver_license": "LICENSE",
    "date_of_birth": "DOB",
    "dob": "DOB",
    "birthdate": "DOB",
    "redacted": "SECRET",
    "pii": "PII",
}

_BRACKET_RE = re.compile(r"\[([A-Z][A-Z0-9_]*)\]")


def _normalize_bracket_placeholders(text: str) -> tuple[str, int]:
    """
    Convert PII-Redact bracket notation → our {{TYPE_N}} format.

    e.g. "Send to [EMAIL_ADDRESS] using key [API_KEY]"
      →  "Send to {{EMAIL_1}} using key {{API_KEY_1}}"

    Skips brackets that don't look like entity labels (e.g. markdown [link]).
    Returns (normalized_text, additional_count).
    """
    counter: dict[str, int] = {}
    total = 0

    def _replacer(m: re.Match) -> str:
        nonlocal total
        raw = m.group(1).lower()
        kind = _BRACKET_LABEL_MAP.get(raw)
        if kind is None:
            # Unknown label — only replace if it looks like a PII entity type
            # (all-caps, underscore-separated). Ignore things like [INFO], [NOTE].
            if "_" in raw or len(raw) <= 4:
                return m.group(0)  # not a PII label, leave it
            kind = raw.upper()
        counter[kind] = counter.get(kind, 0) + 1
        total += 1
        return f"{{{{{kind}_{counter[kind]}}}}}"

    result = _BRACKET_RE.sub(_replacer, text)
    return result, total


# ── Result type ───────────────────────────────────────────────────────────────

class RedactionResult(NamedTuple):
    text: str           # Final text — redacted where secrets were found
    count: int          # Total number of redactions applied
    stage: str          # "none" | "regex" | "model" | "both"
    scan_skipped: bool  # True if Stage 2 could not run (model unavailable)
    original: str       # Original unredacted text — for UI diff display


# ── Stage 1: regex ────────────────────────────────────────────────────────────

def _regex_scan(text: str) -> tuple[str, int]:
    """Apply SENSITIVE_PATTERNS via re.sub. Returns (redacted_text, count)."""
    total = 0
    counter: dict[str, int] = {}

    for kind, pattern in SENSITIVE_PATTERNS.items():
        if kind == "GENERIC_SECRET":
            # Pattern captures keyword in group(1) and the secret value in group(2).
            # Replace only the value part so the keyword label stays readable.
            def _gen_replacer(m: re.Match, _kind: str = kind) -> str:
                nonlocal total
                value = m.group(2) if m.lastindex and m.lastindex >= 2 else ""
                if not value or len(value) < 4:
                    return m.group(0)
                # Skip if the value is already a placeholder from an earlier pass
                if _PLACEHOLDER_RE.fullmatch(value):
                    return m.group(0)
                counter[_kind] = counter.get(_kind, 0) + 1
                total += 1
                placeholder = f"{{{{{_kind}_{counter[_kind]}}}}}"
                # Keep everything up to (and including) the separator; replace only value
                prefix_len = m.start(2) - m.start(0)
                return m.group(0)[:prefix_len] + placeholder

            text = pattern.sub(_gen_replacer, text)
        else:
            def _replacer(m: re.Match, _kind: str = kind) -> str:
                nonlocal total
                val = m.group(0)
                if not val or len(val) < 4:
                    return val
                counter[_kind] = counter.get(_kind, 0) + 1
                total += 1
                return f"{{{{{_kind}_{counter[_kind]}}}}}"

            text = pattern.sub(_replacer, text)

    return text, total


# ── Stage 2: model ────────────────────────────────────────────────────────────

def _get_scan_provider() -> tuple[OpenAICompatProvider, bool] | tuple[None, None]:
    """
    Return (provider, is_dedicated) or (None, None) if no model is configured.

    is_dedicated=True  → a specific PANTHEON_SCAN_* model is configured.
                         PII-Redact fine-tunes fall into this category.
                         These do NOT use a system prompt.
    is_dedicated=False → falling back to the local chat model.
                         General instruction models need the system prompt.
    """
    if settings.scan_base_url and settings.scan_model:
        from ..providers import ProviderConfig
        cfg = ProviderConfig(
            name="scan",
            base_url=settings.scan_base_url,
            api_key=settings.scan_api_key,
            default_model=settings.scan_model,
        )
        return OpenAICompatProvider(cfg), True

    if settings.local_base_url and settings.local_model:
        from ..providers import ProviderConfig
        cfg = ProviderConfig(
            name="scan_fallback",
            base_url=settings.local_base_url,
            api_key=settings.local_api_key,
            default_model=settings.local_model,
        )
        return OpenAICompatProvider(cfg), False

    return None, None


async def _model_scan(
    provider: OpenAICompatProvider,
    text: str,
    is_dedicated: bool,
) -> tuple[str, int]:
    """
    Run one LLM scan pass.

    is_dedicated=True  → fine-tuned model (PII-Redact): send raw text, no
                         system prompt. The model knows its job.
    is_dedicated=False → general instruction model: needs the system prompt
                         to understand what to do and /no_think for Qwen3.
    """
    if is_dedicated:
        messages = [{"role": "user", "content": text}]
    else:
        messages = [
            {"role": "system", "content": _NO_THINK + _SCAN_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ]

    try:
        result = await provider.complete_chat(
            messages=messages,
            max_tokens=max(len(text) * 2 + 256, 512),
            temperature=0.0,
        )
    except Exception:
        raise  # caller handles

    if not result or not result.strip():
        return text, 0

    cleaned = result.strip()

    # Normalize PII-Redact bracket output → our {{TYPE_N}} format.
    # No-op if the model already outputs {{TYPE_N}} (general instruction models).
    cleaned, bracket_count = _normalize_bracket_placeholders(cleaned)

    placeholder_count = len(_PLACEHOLDER_RE.findall(cleaned))
    count = max(bracket_count, placeholder_count)
    return cleaned, count


# ── Public API ────────────────────────────────────────────────────────────────

async def scan_and_redact(text: str) -> RedactionResult:
    """
    Run the two-stage pipeline on `text`.

    Stage 1 (regex) always runs. Stage 2 (model) runs if any scan provider
    is reachable. scan_skipped=True means Stage 2 could not run — the chat
    stream will warn the user rather than silently proceeding.
    """
    original = text

    # Stage 1 — regex, always
    after_regex, regex_count = _regex_scan(text)

    # Stage 2 — model
    provider, is_dedicated = _get_scan_provider()
    if provider is None:
        stage = "regex" if regex_count > 0 else "none"
        return RedactionResult(
            text=after_regex,
            count=regex_count,
            stage=stage,
            scan_skipped=True,
            original=original,
        )

    try:
        after_model, model_count = await _model_scan(provider, after_regex, is_dedicated)
    except Exception:
        stage = "regex" if regex_count > 0 else "none"
        return RedactionResult(
            text=after_regex,
            count=regex_count,
            stage=stage,
            scan_skipped=True,
            original=original,
        )

    total = regex_count + model_count
    if regex_count > 0 and model_count > 0:
        stage = "both"
    elif model_count > 0:
        stage = "model"
    elif regex_count > 0:
        stage = "regex"
    else:
        stage = "none"

    return RedactionResult(
        text=after_model,
        count=total,
        stage=stage,
        scan_skipped=False,
        original=original,
    )


# Keep the old function signature for any callers that used it directly
async def scan_message(provider: OpenAICompatProvider, text: str) -> tuple[str, int]:
    """Legacy shim — use scan_and_redact() for new code."""
    result = await scan_and_redact(text)
    return result.text, result.count

