from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncGenerator

import httpx


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    default_model: str
    api_key: str = ""


class OpenAICompatProvider:
    def __init__(self, cfg: ProviderConfig):
        self.cfg = cfg

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        return headers

    async def list_models(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self.cfg.base_url}/models", headers=self._headers())
            resp.raise_for_status()
            payload = resp.json()
            return payload.get("data", [])

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        no_think: bool = False,
    ) -> AsyncGenerator[tuple[str, str], None]:
        """Yields (kind, token) tuples where kind is 'content' or 'thinking'."""
        msgs = list(messages)
        if no_think and (not msgs or msgs[0].get("role") != "system" or "/no_think" not in msgs[0].get("content", "")):
            msgs = [{"role": "system", "content": "/no_think"}] + msgs

        payload: dict[str, Any] = {
            "model": model or self.cfg.default_model,
            "messages": msgs,
            "stream": True,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{self.cfg.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        parsed = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    choices = parsed.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    token = delta.get("content")
                    if token:
                        yield ("content", token)
                    thinking = delta.get("reasoning_content")
                    if thinking:
                        yield ("thinking", thinking)

    async def complete_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict:
        """Non-streaming call with tool definitions. Returns the full message dict including tool_calls."""
        payload: dict[str, Any] = {
            "model": model or self.cfg.default_model,
            "messages": messages,
            "tools": tools,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self.cfg.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            parsed = resp.json()

        choices = parsed.get("choices", [])
        if not choices:
            return {"role": "assistant", "content": "", "tool_calls": None}
        message = choices[0].get("message", {})
        return {
            "role": "assistant",
            "content": message.get("content") or "",
            "tool_calls": message.get("tool_calls"),
        }

    async def complete_chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model or self.cfg.default_model,
            "messages": messages,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.cfg.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            parsed = resp.json()
            choices = parsed.get("choices", [])
            if not choices:
                return ""

            message = choices[0].get("message", {})
            content = message.get("content", "")

            if isinstance(content, str):
                return content
            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                return "".join(text_parts)
            return str(content)
