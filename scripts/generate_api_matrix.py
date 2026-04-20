#!/usr/bin/env python3
"""Generate a compact API endpoint matrix from live OpenAPI JSON."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError, HTTPError
from urllib.request import urlopen

HTTP_METHODS = ["get", "post", "put", "patch", "delete", "options", "head"]

PUBLIC_PREFIXES = (
    "/api/auth/",
    "/api/wizard/",
    "/static/",
    "/docs",
    "/openapi",
    "/redoc",
)
PUBLIC_EXACT = {"/", "/favicon.ico", "/mcp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate docs/api-endpoint-matrix.md from a live OpenAPI endpoint."
    )
    parser.add_argument(
        "--openapi-url",
        default="http://127.0.0.1:8787/openapi.json",
        help="OpenAPI JSON URL",
    )
    parser.add_argument(
        "--output",
        default="docs/api-endpoint-matrix.md",
        help="Output markdown path",
    )
    return parser.parse_args()


def fetch_openapi(openapi_url: str) -> dict[str, Any]:
    try:
        with urlopen(openapi_url, timeout=10) as response:  # nosec B310 - local trusted URL
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        raise SystemExit(f"OpenAPI request failed: HTTP {exc.code} at {openapi_url}") from exc
    except URLError as exc:
        raise SystemExit(f"OpenAPI request failed: {exc.reason}") from exc

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"OpenAPI payload was not valid JSON: {exc}") from exc


def classify_access(path: str) -> str:
    if path in PUBLIC_EXACT:
        return "public"
    if any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
        return "public"
    return "auth-required"


def md_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def build_rows(openapi: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    paths = openapi.get("paths", {})

    for path, operations in paths.items():
        for method in HTTP_METHODS:
            operation = operations.get(method)
            if not operation:
                continue
            tags = operation.get("tags") or ["untagged"]
            rows.append(
                {
                    "tag": str(tags[0]),
                    "method": method.upper(),
                    "path": path,
                    "access": classify_access(path),
                    "operation_id": str(operation.get("operationId", "")),
                    "summary": str(operation.get("summary", "")),
                }
            )

    rows.sort(key=lambda row: (row["tag"], row["path"], row["method"]))
    return rows


def render_matrix(rows: list[dict[str, str]], openapi_url: str, title: str, version: str) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines: list[str] = []
    lines.append("# API Endpoint Matrix")
    lines.append("")
    lines.append(f"Generated from live OpenAPI: `{openapi_url}`")
    lines.append("")
    lines.append(f"- Generated: `{generated_at}`")
    lines.append(f"- API title: `{title}`")
    lines.append(f"- API version: `{version}`")
    lines.append(f"- Endpoint count: `{len(rows)}`")
    lines.append("")
    lines.append("## Compact Matrix")
    lines.append("")
    lines.append("| Tag | Method | Path | Access | Operation ID | Summary |")
    lines.append("|---|---|---|---|---|---|")

    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    md_escape(row["tag"]),
                    md_escape(row["method"]),
                    md_escape(row["path"]),
                    md_escape(row["access"]),
                    md_escape(row["operation_id"]),
                    md_escape(row["summary"]),
                ]
            )
            + " |"
        )

    lines.append("")
    lines.append("## Access Classification")
    lines.append("")
    lines.append("- `public`: allowed by auth middleware prefixes/exact paths")
    lines.append("- `auth-required`: all other endpoints")
    lines.append("")
    lines.append("Access is derived from `backend/app/middleware/auth.py` rules.")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    openapi = fetch_openapi(args.openapi_url)
    rows = build_rows(openapi)

    info = openapi.get("info") or {}
    title = str(info.get("title", "unknown"))
    version = str(info.get("version", "unknown"))

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_matrix(rows, args.openapi_url, title=title, version=version),
        encoding="utf-8",
    )

    print(f"Wrote {output} with {len(rows)} endpoints")


if __name__ == "__main__":
    main()
