from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# MCP Onboarding Catalog
# ---------------------------------------------------------------------------
# auth_type: "none" | "api_key" | "bearer" | "oauth"
# auth_env_key: which env var holds the token to send as Authorization: Bearer
# ---------------------------------------------------------------------------
MCP_ONBOARDING_CATALOG: dict[str, dict] = {
    "github": {
        "name": "github",
        "transport": "http",
        "url": "https://api.githubcopilot.com/mcp/",
        "command": None,
        "args": [],
        "env": {"GITHUB_TOKEN": "<required>"},
        "auth_type": "bearer",
        "auth_env_key": "GITHUB_TOKEN",
        "docs": ["https://github.com/github/github-mcp-server"],
        "notes": "GitHub Copilot MCP. Repos, issues, PRs, Actions, code search. GitHub PAT with repo scopes.",
        "capabilities": ["repositories", "issues", "pull requests", "code search", "actions", "copilot"],
    },
    "cloudflare": {
        "name": "cloudflare",
        "transport": "http",
        "url": "https://mcp.cloudflare.com/mcp",
        "command": None,
        "args": [],
        "env": {"CLOUDFLARE_API_TOKEN": "<required>"},
        "auth_type": "bearer",
        "auth_env_key": "CLOUDFLARE_API_TOKEN",
        "docs": ["https://developers.cloudflare.com/agents/model-context-protocol/mcp-servers-for-cloudflare/"],
        "notes": "Workers, Pages, D1, R2, KV, Queues, Durable Objects. Create a scoped API token at dash.cloudflare.com/profile/api-tokens.",
        "capabilities": ["cloudflare workers", "pages", "d1 database", "r2 storage", "kv store", "queues"],
    },
    "stripe": {
        "name": "stripe",
        "transport": "http",
        "url": "https://mcp.stripe.com/mcp",
        "command": None,
        "args": [],
        "env": {"STRIPE_API_KEY": "<required>"},
        "auth_type": "bearer",
        "auth_env_key": "STRIPE_API_KEY",
        "docs": ["https://docs.stripe.com/stripe-apps/create-app"],
        "notes": "Payments, customers, subscriptions, invoices. Use a restricted API key scoped to needed resources.",
        "capabilities": ["payments", "customers", "subscriptions", "products", "invoices", "webhooks"],
    },
    "neon": {
        "name": "neon",
        "transport": "http",
        "url": "https://mcp.neon.tech/mcp",
        "command": None,
        "args": [],
        "env": {"NEON_API_KEY": "<required>"},
        "auth_type": "bearer",
        "auth_env_key": "NEON_API_KEY",
        "docs": ["https://neon.tech/docs/ai/neon-mcp-server", "https://console.neon.tech/app/settings/api-keys"],
        "notes": "Neon Postgres databases, SQL, branches. Get API key at console.neon.tech → Account → API keys.",
        "capabilities": ["postgresql", "database management", "branching", "sql queries", "schema introspection"],
    },
    "sentry": {
        "name": "sentry",
        "transport": "http",
        "url": "https://mcp.sentry.io/mcp",
        "command": None,
        "args": [],
        "env": {"SENTRY_AUTH_TOKEN": "<required>"},
        "auth_type": "bearer",
        "auth_env_key": "SENTRY_AUTH_TOKEN",
        "docs": ["https://docs.sentry.io/product/sentry-mcp/", "https://sentry.io/settings/auth-tokens/"],
        "notes": "Issues, traces, performance data, error monitoring. Create an auth token at sentry.io → Settings → Auth Tokens.",
        "capabilities": ["error monitoring", "issue tracking", "performance traces", "release tracking"],
    },
    "notion": {
        "name": "notion",
        "transport": "http",
        "url": "https://mcp.notion.com/mcp",
        "command": None,
        "args": [],
        "env": {"NOTION_TOKEN": "<required>"},
        "auth_type": "bearer",
        "auth_env_key": "NOTION_TOKEN",
        "docs": ["https://developers.notion.com/docs/getting-started", "https://www.notion.so/my-integrations"],
        "notes": "Pages, databases, blocks. Create an internal integration at notion.so/my-integrations and copy the token.",
        "capabilities": ["pages", "databases", "blocks", "search", "comments"],
    },
    "supabase": {
        "name": "supabase",
        "transport": "http",
        "url": "https://mcp.supabase.com/mcp",
        "command": None,
        "args": [],
        "env": {"SUPABASE_ACCESS_TOKEN": "<required>"},
        "auth_type": "bearer",
        "auth_env_key": "SUPABASE_ACCESS_TOKEN",
        "docs": ["https://supabase.com/docs/guides/getting-started/mcp", "https://supabase.com/dashboard/account/tokens"],
        "notes": "Postgres, auth, storage, edge functions. Get a personal access token at supabase.com → Account → Access Tokens.",
        "capabilities": ["postgresql", "auth", "storage", "edge functions", "realtime", "project management"],
    },
    "firecrawl": {
        "name": "firecrawl",
        "transport": "http",
        "url": "https://mcp.firecrawl.dev/mcp",
        "command": None,
        "args": [],
        "env": {"FIRECRAWL_API_KEY": "<required>"},
        "auth_type": "bearer",
        "auth_env_key": "FIRECRAWL_API_KEY",
        "docs": ["https://docs.firecrawl.dev/mcp"],
        "notes": "Web scraping, crawling, structured extraction. Get API key at firecrawl.dev.",
        "capabilities": ["web scraping", "crawling", "content extraction", "markdown conversion", "structured data"],
    },
    "exa": {
        "name": "exa",
        "transport": "http",
        "url": "https://mcp.exa.ai/mcp",
        "command": None,
        "args": [],
        "env": {"EXA_API_KEY": "<required>"},
        "auth_type": "bearer",
        "auth_env_key": "EXA_API_KEY",
        "docs": ["https://docs.exa.ai"],
        "notes": "Neural web search — semantically relevant pages + full content. Get key at exa.ai.",
        "capabilities": ["web search", "semantic search", "content retrieval", "research"],
    },
    "context7": {
        "name": "context7",
        "transport": "http",
        "url": "https://mcp.context7.com/mcp",
        "command": None,
        "args": [],
        "env": {},
        "auth_type": "none",
        "auth_env_key": None,
        "docs": ["https://context7.com/docs"],
        "notes": "Free. Up-to-date library docs and code examples injected into context. No key needed.",
        "capabilities": ["documentation lookup", "library references", "code examples", "framework docs"],
    },
    "deepwiki": {
        "name": "deepwiki",
        "transport": "http",
        "url": "https://mcp.deepwiki.com/mcp",
        "command": None,
        "args": [],
        "env": {},
        "auth_type": "none",
        "auth_env_key": None,
        "docs": ["https://deepwiki.com"],
        "notes": "Free. Search and read open-source GitHub repos, codebases, and wikis. No key needed.",
        "capabilities": ["open source code search", "repository exploration", "github wikis", "codebase understanding"],
    },
}

# ---------------------------------------------------------------------------
# Builtin MCP servers seeded on every startup
# ---------------------------------------------------------------------------
BUILTIN_MCP_SERVERS: list[dict] = [
    {
        "name": "context7",
        "transport": "http",
        "url": "https://mcp.context7.com/mcp",
        "command": None,
        "args": [],
        "env": {},
    },
    {
        "name": "deepwiki",
        "transport": "http",
        "url": "https://mcp.deepwiki.com/mcp",
        "command": None,
        "args": [],
        "env": {},
    },
]

# ---------------------------------------------------------------------------
# Credential connector catalog (OAuth / API key portals)
# ---------------------------------------------------------------------------
CREDENTIAL_CONNECTOR_CATALOG: dict[str, dict] = {
    "cloudflare": {
        "title": "Cloudflare API token setup",
        "auth_url": "https://dash.cloudflare.com/profile/api-tokens",
        "credential_type": "api_key",
        "suggested_env": "CLOUDFLARE_API_TOKEN",
    },
    "stripe": {
        "title": "Stripe API key setup",
        "auth_url": "https://dashboard.stripe.com/apikeys",
        "credential_type": "api_key",
        "suggested_env": "STRIPE_API_KEY",
    },
    "github": {
        "title": "GitHub token setup",
        "auth_url": "https://github.com/settings/tokens",
        "credential_type": "api_key",
        "suggested_env": "GITHUB_TOKEN",
    },
    "openrouter": {
        "title": "OpenRouter API key setup",
        "auth_url": "https://openrouter.ai/keys",
        "credential_type": "api_key",
        "suggested_env": "OPENROUTER_API_KEY",
    },
}

# ---------------------------------------------------------------------------
# Sensitive-data detection patterns
# ---------------------------------------------------------------------------
CRED_REF_PATTERN = re.compile(r"^\{\{cred:([^}]+)\}\}$")

SENSITIVE_PATTERNS: dict[str, re.Pattern] = {
    "OPENAI_KEY": re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    "GOOGLE_API_KEY": re.compile(r"\bAIza[0-9A-Za-z\-_]{20,}\b"),
    "AWS_ACCESS_KEY": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GITHUB_TOKEN": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    "GENERIC_SECRET": re.compile(
        r"\b(secret|token|api[_-]?key|password)\s*[:=]\s*['\"]?([^\s'\",;]+)",
        re.IGNORECASE,
    ),
}
