from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CreateConversationRequest(BaseModel):
    title: str | None = None


class ConversationUpdateRequest(BaseModel):
    action: Literal["restore", "hide", "archive_good", "archive_bad"]
    note: str | None = None


class ConversationOut(BaseModel):
    id: int
    title: str
    created_at: str


class MessageOut(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    provider: str | None
    model: str | None
    created_at: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: int | None = None
    provider: str | None = None
    model: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None


class AddNoteRequest(BaseModel):
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)


class SearchNotesRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


class McpServerCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    transport: Literal["stdio", "http", "sse"] = "http"
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class McpServerUpdateRequest(BaseModel):
    name: str | None = None
    transport: Literal["stdio", "http", "sse"] | None = None
    url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None


class McpOnboardRequest(BaseModel):
    prompt: str = Field(min_length=1)
    include_catalog: bool = False


class WidgetCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    widget_type: str = Field(min_length=1)
    layout_col: int = Field(default=1, ge=1)
    layout_row: int = Field(default=1, ge=1)
    layout_w: int = Field(default=3, ge=1)
    layout_h: int = Field(default=2, ge=1)
    config: dict = Field(default_factory=dict)


class WidgetUpdateRequest(BaseModel):
    name: str | None = None
    widget_type: str | None = None
    layout_col: int | None = Field(default=None, ge=1)
    layout_row: int | None = Field(default=None, ge=1)
    layout_w: int | None = Field(default=None, ge=1)
    layout_h: int | None = Field(default=None, ge=1)
    config: dict | None = None


class CopilotTaskCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    context: dict = Field(default_factory=dict)


class CopilotTaskUpdateRequest(BaseModel):
    status: Literal["queued", "active", "completed", "blocked"] | None = None
    result_markdown: str | None = None


class AutomationTaskCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    trigger_type: Literal["manual", "scheduled", "event"] = "manual"
    status: Literal["draft", "ready", "active", "archived"] = "draft"
    sensitive_mode: Literal["off", "local_only", "hybrid_redacted"] = "off"
    local_context: dict = Field(default_factory=dict)
    cloud_prompt_template: str | None = None
    runbook_markdown: str | None = None


class AutomationTaskUpdateRequest(BaseModel):
    title: str | None = None
    objective: str | None = None
    trigger_type: Literal["manual", "scheduled", "event"] | None = None
    status: Literal["draft", "ready", "active", "archived"] | None = None
    sensitive_mode: Literal["off", "local_only", "hybrid_redacted"] | None = None
    local_context: dict | None = None
    cloud_prompt_template: str | None = None
    runbook_markdown: str | None = None


class SkillCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    description: str = Field(min_length=1)
    status: Literal["active", "draft", "disabled"] = "draft"
    local_only: bool = False
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    tool_contract: dict = Field(default_factory=dict)


class SkillUpdateRequest(BaseModel):
    name: str | None = None
    category: str | None = None
    description: str | None = None
    status: Literal["active", "draft", "disabled"] | None = None
    local_only: bool | None = None
    input_schema: dict | None = None
    output_schema: dict | None = None
    tool_contract: dict | None = None


class ZenActionRequest(BaseModel):
    domain: Literal["task_create", "skill_create", "note_create", "mcp_create", "widget_create"]
    prompt: str = Field(min_length=1)
    source_text: str | None = None
    provider: str | None = None
    model: str | None = None


class IntegrationCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    provider_kind: str = Field(min_length=1)
    base_url: str | None = None
    auth_type: Literal["api_key", "oauth", "adc", "none"] = "api_key"
    api_key: str | None = None
    default_model: str | None = None
    status: Literal["draft", "connected", "error", "disabled"] = "draft"
    meta: dict = Field(default_factory=dict)


class IntegrationUpdateRequest(BaseModel):
    name: str | None = None
    provider_kind: str | None = None
    base_url: str | None = None
    auth_type: Literal["api_key", "oauth", "adc", "none"] | None = None
    api_key: str | None = None
    default_model: str | None = None
    status: Literal["draft", "connected", "error", "disabled"] | None = None
    meta: dict | None = None


class SensitiveRedactPreviewRequest(BaseModel):
    text: str = Field(min_length=1)
    manual_tags: list[str] = Field(default_factory=list)
    manual_untags: list[str] = Field(default_factory=list)


class SensitiveRedactApplyRequest(BaseModel):
    text: str = Field(min_length=1)
    approved_tokens: dict[str, str] = Field(default_factory=dict)


class CredentialCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    credential_type: Literal["api_key", "password", "oauth_token", "session_token", "other"] = "api_key"
    provider: str | None = None
    username: str | None = None
    secret: str = Field(min_length=1)
    meta: dict = Field(default_factory=dict)


class CredentialUpdateRequest(BaseModel):
    name: str | None = None
    credential_type: Literal["api_key", "password", "oauth_token", "session_token", "other"] | None = None
    provider: str | None = None
    username: str | None = None
    secret: str | None = None
    meta: dict | None = None
    rotate: bool = False


class CredentialEnvImportRequest(BaseModel):
    env_text: str = Field(min_length=1)
    provider: str | None = None
    credential_type: Literal["api_key", "password", "oauth_token", "session_token", "other"] = "api_key"
    overwrite: bool = False


class ConnectorLaunchRequest(BaseModel):
    provider: str = Field(min_length=1)
    open_browser: bool = True


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    kind: Literal["app", "website", "service", "library", "workspace"] = "app"
    stack: dict = Field(default_factory=dict)


class ProjectImportRequest(BaseModel):
    path: str = Field(min_length=1)
    name: str | None = None
    kind: Literal["app", "website", "service", "library", "workspace"] = "workspace"


class ProjectMkdirRequest(BaseModel):
    relative_path: str = Field(min_length=1)


class ProjectCommandRequest(BaseModel):
    command: str = Field(min_length=1)
    allow_system_access: bool = False
    timeout_sec: int = Field(default=120, ge=5, le=900)


class ProjectCopilotCliRequest(BaseModel):
    prompt: str = Field(min_length=1)
    target: Literal["shell", "general"] = "general"
    allow_system_access: bool = False
    timeout_sec: int = Field(default=120, ge=5, le=900)


class ProjectPreviewUpdateRequest(BaseModel):
    dev_url: str | None = None


class ProjectScriptRunRequest(BaseModel):
    script_key: str = Field(min_length=1)
    allow_system_access: bool = False
