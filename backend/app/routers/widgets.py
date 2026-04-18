from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from ..schemas import WidgetCreateRequest, WidgetUpdateRequest
from ..services.serializers import serialize_widget_row
from ..state import g

router = APIRouter(prefix="/api/widgets", tags=["widgets"])


@router.get("")
def list_widgets() -> list[dict]:
    rows = g.db.execute("SELECT * FROM dashboard_widgets ORDER BY id DESC").fetchall()
    return [serialize_widget_row(r) for r in rows]


@router.post("")
def create_widget(payload: WidgetCreateRequest) -> dict:
    cur = g.db.execute(
        """
        INSERT INTO dashboard_widgets(name, widget_type, layout_col, layout_row, layout_w, layout_h, config_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.name.strip(),
            payload.widget_type.strip(),
            payload.layout_col,
            payload.layout_row,
            payload.layout_w,
            payload.layout_h,
            json.dumps(payload.config),
        ),
    )
    g.db.commit()
    row = g.db.execute("SELECT * FROM dashboard_widgets WHERE id = ?", (cur.lastrowid,)).fetchone()
    return serialize_widget_row(row)


@router.patch("/{widget_id}")
def update_widget(widget_id: int, payload: WidgetUpdateRequest) -> dict:
    row = g.db.execute("SELECT * FROM dashboard_widgets WHERE id = ?", (widget_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Widget not found")

    next_values = dict(row)
    patch = payload.model_dump(exclude_unset=True)
    if "config" in patch:
        next_values["config_json"] = json.dumps(patch.pop("config"))
    for k, v in patch.items():
        next_values[k] = v

    g.db.execute(
        """
        UPDATE dashboard_widgets
        SET name = ?, widget_type = ?, layout_col = ?, layout_row = ?, layout_w = ?, layout_h = ?,
            config_json = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (
            next_values["name"],
            next_values["widget_type"],
            next_values["layout_col"],
            next_values["layout_row"],
            next_values["layout_w"],
            next_values["layout_h"],
            next_values["config_json"],
            widget_id,
        ),
    )
    g.db.commit()
    updated = g.db.execute("SELECT * FROM dashboard_widgets WHERE id = ?", (widget_id,)).fetchone()
    return serialize_widget_row(updated)


@router.delete("/{widget_id}")
def delete_widget(widget_id: int) -> dict:
    cur = g.db.execute("DELETE FROM dashboard_widgets WHERE id = ?", (widget_id,))
    g.db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Widget not found")
    return {"deleted": True, "id": widget_id}
