from __future__ import annotations

import json

import sqlite3
from fastapi import APIRouter, HTTPException

from ..schemas import SkillCreateRequest, SkillUpdateRequest
from ..services.serializers import serialize_skill_row
from ..state import g

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("")
def list_skills(limit: int = 200) -> list[dict]:
    limit = max(1, min(limit, 500))
    rows = g.db.execute(
        "SELECT * FROM skills ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [serialize_skill_row(r) for r in rows]


@router.post("")
def create_skill(payload: SkillCreateRequest) -> dict:
    cur = g.db.execute(
        """
        INSERT INTO skills(
            name, category, description, status, local_only,
            input_schema_json, output_schema_json, tool_contract_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.name.strip(),
            payload.category.strip(),
            payload.description.strip(),
            payload.status,
            1 if payload.local_only else 0,
            json.dumps(payload.input_schema),
            json.dumps(payload.output_schema),
            json.dumps(payload.tool_contract),
        ),
    )
    g.db.commit()
    row = g.db.execute("SELECT * FROM skills WHERE id = ?", (cur.lastrowid,)).fetchone()
    return serialize_skill_row(row)


@router.patch("/{skill_id}")
def update_skill(skill_id: int, payload: SkillUpdateRequest) -> dict:
    row = g.db.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Skill not found")

    next_values = dict(row)
    patch = payload.model_dump(exclude_unset=True)
    if "local_only" in patch:
        next_values["local_only"] = 1 if patch.pop("local_only") else 0
    if "input_schema" in patch:
        next_values["input_schema_json"] = json.dumps(patch.pop("input_schema"))
    if "output_schema" in patch:
        next_values["output_schema_json"] = json.dumps(patch.pop("output_schema"))
    if "tool_contract" in patch:
        next_values["tool_contract_json"] = json.dumps(patch.pop("tool_contract"))
    for key, value in patch.items():
        next_values[key] = value

    g.db.execute(
        """
        UPDATE skills
        SET name = ?, category = ?, description = ?, status = ?, local_only = ?,
            input_schema_json = ?, output_schema_json = ?, tool_contract_json = ?,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (
            next_values["name"],
            next_values["category"],
            next_values["description"],
            next_values["status"],
            next_values["local_only"],
            next_values["input_schema_json"],
            next_values["output_schema_json"],
            next_values["tool_contract_json"],
            skill_id,
        ),
    )
    g.db.commit()
    updated = g.db.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
    return serialize_skill_row(updated)


@router.delete("/{skill_id}")
def delete_skill(skill_id: int) -> dict:
    cur = g.db.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
    g.db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"deleted": True, "id": skill_id}
