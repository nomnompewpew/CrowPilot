from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from ..schemas import (
    AutomationTaskCreateRequest,
    AutomationTaskUpdateRequest,
    CopilotTaskCreateRequest,
    CopilotTaskUpdateRequest,
)
from ..services.memory import enqueue_message, BACKGROUND
from ..services.serializers import serialize_automation_task_row, serialize_copilot_task_row
from ..state import g

router = APIRouter(tags=["tasks"])


# ---------------------------------------------------------------------------
# Copilot tasks
# ---------------------------------------------------------------------------

@router.get("/api/copilot/blueprint")
def copilot_blueprint() -> dict:
    return {
        "title": "Copilot Build Loop",
        "description": "Queue build tasks from the UI, then execute and iterate with Copilot in the same repo context.",
        "flow": [
            "Create task card from UI",
            "Refine in editor with Copilot",
            "Run checks and commit",
            "Attach result markdown to task",
        ],
        "note": "Direct tool invocation stays in VS Code/Copilot session, but this queue tracks and coordinates work.",
    }


@router.get("/api/copilot/tasks")
def list_copilot_tasks(limit: int = 50) -> list[dict]:
    limit = max(1, min(limit, 200))
    rows = g.db.execute(
        "SELECT * FROM copilot_tasks ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [serialize_copilot_task_row(r) for r in rows]


@router.post("/api/copilot/tasks")
def create_copilot_task(payload: CopilotTaskCreateRequest) -> dict:
    cur = g.db.execute(
        """
        INSERT INTO copilot_tasks(title, description, status, context_json)
        VALUES (?, ?, 'queued', ?)
        """,
        (payload.title.strip(), payload.description.strip(), json.dumps(payload.context)),
    )
    g.db.commit()
    task_id = cur.lastrowid
    row = g.db.execute("SELECT * FROM copilot_tasks WHERE id = ?", (task_id,)).fetchone()
    enqueue_message(
        f"{payload.title.strip()}\n{payload.description.strip()}",
        "task", task_id, 0, BACKGROUND,
    )
    return serialize_copilot_task_row(row)


@router.patch("/api/copilot/tasks/{task_id}")
def update_copilot_task(task_id: int, payload: CopilotTaskUpdateRequest) -> dict:
    row = g.db.execute("SELECT * FROM copilot_tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    next_status = payload.status or row["status"]
    next_result = payload.result_markdown if payload.result_markdown is not None else row["result_markdown"]

    g.db.execute(
        """
        UPDATE copilot_tasks
        SET status = ?, result_markdown = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (next_status, next_result, task_id),
    )
    g.db.commit()
    updated = g.db.execute("SELECT * FROM copilot_tasks WHERE id = ?", (task_id,)).fetchone()
    return serialize_copilot_task_row(updated)


# ---------------------------------------------------------------------------
# Automation tasks
# ---------------------------------------------------------------------------

@router.get("/api/tasks")
def list_automation_tasks(limit: int = 100) -> list[dict]:
    limit = max(1, min(limit, 500))
    rows = g.db.execute(
        "SELECT * FROM automation_tasks ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [serialize_automation_task_row(r) for r in rows]


@router.post("/api/tasks")
def create_automation_task(payload: AutomationTaskCreateRequest) -> dict:
    cur = g.db.execute(
        """
        INSERT INTO automation_tasks(
            title, objective, trigger_type, status, sensitive_mode,
            local_context_json, cloud_prompt_template, runbook_markdown
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.title.strip(),
            payload.objective.strip(),
            payload.trigger_type,
            payload.status,
            payload.sensitive_mode,
            json.dumps(payload.local_context),
            payload.cloud_prompt_template,
            payload.runbook_markdown,
        ),
    )
    g.db.commit()
    task_id = cur.lastrowid
    row = g.db.execute("SELECT * FROM automation_tasks WHERE id = ?", (task_id,)).fetchone()
    enqueue_message(
        f"{payload.title.strip()}\n{payload.objective.strip()}",
        "task", task_id, 0, BACKGROUND,
    )
    return serialize_automation_task_row(row)


@router.patch("/api/tasks/{task_id}")
def update_automation_task(task_id: int, payload: AutomationTaskUpdateRequest) -> dict:
    row = g.db.execute("SELECT * FROM automation_tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    next_values = dict(row)
    patch = payload.model_dump(exclude_unset=True)
    if "local_context" in patch:
        next_values["local_context_json"] = json.dumps(patch.pop("local_context"))
    for key, value in patch.items():
        next_values[key] = value

    g.db.execute(
        """
        UPDATE automation_tasks
        SET title = ?, objective = ?, trigger_type = ?, status = ?, sensitive_mode = ?,
            local_context_json = ?, cloud_prompt_template = ?, runbook_markdown = ?,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (
            next_values["title"],
            next_values["objective"],
            next_values["trigger_type"],
            next_values["status"],
            next_values["sensitive_mode"],
            next_values["local_context_json"],
            next_values["cloud_prompt_template"],
            next_values["runbook_markdown"],
            task_id,
        ),
    )
    g.db.commit()
    updated = g.db.execute("SELECT * FROM automation_tasks WHERE id = ?", (task_id,)).fetchone()
    return serialize_automation_task_row(updated)


@router.post("/api/tasks/{task_id}/run")
def run_automation_task(task_id: int) -> dict:
    row = g.db.execute("SELECT * FROM automation_tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    g.db.execute(
        """
        UPDATE automation_tasks
        SET run_count = run_count + 1, last_run_at = datetime('now'), updated_at = datetime('now')
        WHERE id = ?
        """,
        (task_id,),
    )
    g.db.commit()
    updated = g.db.execute("SELECT * FROM automation_tasks WHERE id = ?", (task_id,)).fetchone()
    return {
        "ok": True,
        "task": serialize_automation_task_row(updated),
        "note": "Run recorded. Wire this endpoint to local/cloud execution runtime next.",
    }


@router.delete("/api/tasks/{task_id}")
def delete_automation_task(task_id: int) -> dict:
    cur = g.db.execute("DELETE FROM automation_tasks WHERE id = ?", (task_id,))
    g.db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"deleted": True, "id": task_id}
