from __future__ import annotations

from ..config import settings
from ..providers import OpenAICompatProvider, ProviderConfig
from ..services.credential_vault import resolve_credential_by_ref
from ..state import g


def build_base_providers() -> dict[str, OpenAICompatProvider]:
    providers: dict[str, OpenAICompatProvider] = {
        "copilot_proxy": OpenAICompatProvider(
            ProviderConfig(
                name="copilot_proxy",
                base_url=settings.copilot_base_url.rstrip("/"),
                default_model=settings.copilot_model,
                api_key=settings.copilot_api_key,
            )
        )
    }

    if settings.local_base_url.strip():
        providers["local_openai"] = OpenAICompatProvider(
            ProviderConfig(
                name="local_openai",
                base_url=settings.local_base_url.rstrip("/"),
                default_model=settings.local_model,
                api_key=settings.local_api_key,
            )
        )

    return providers


def reload_providers_from_integrations() -> None:
    """Rebuild g.providers from base config + connected integrations."""
    g.providers = build_base_providers()

    rows = g.db.execute(
        """
        SELECT id, name, base_url, api_key, default_model, status
        FROM integrations
        WHERE status = 'connected' AND base_url IS NOT NULL AND trim(base_url) != ''
        """
    ).fetchall()

    for row in rows:
        api_key, err = resolve_credential_by_ref(row["api_key"] or "")
        if err:
            continue
        provider_name = f"integration_{row['id']}"
        g.providers[provider_name] = OpenAICompatProvider(
            ProviderConfig(
                name=provider_name,
                base_url=row["base_url"].rstrip("/"),
                default_model=(row["default_model"] or "auto"),
                api_key=api_key or "",
            )
        )
