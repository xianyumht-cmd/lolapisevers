from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI, Query

from services.contact_risk_report_delivery import (
    list_report_retry_queue,
    remove_report_retry_item,
    retry_report_queue,
)


def install_parser_center_retry_routes(app: FastAPI) -> None:
    @app.get("/admin/parser-center/report-queue")
    async def admin_parser_center_report_queue(
        state: str = "",
        limit: int = Query(100, ge=1, le=1000),
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            list_report_retry_queue,
            state=str(state or "").strip(),
            limit=limit,
        )

    @app.post("/admin/parser-center/report-queue/retry")
    async def admin_parser_center_report_queue_retry(
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = payload or {}
        return await retry_report_queue(
            queue_id=max(0, int(body.get("queue_id") or 0)),
            limit=max(1, min(int(body.get("limit") or 20), 100)),
        )

    @app.post("/admin/parser-center/report-queue/remove")
    async def admin_parser_center_report_queue_remove(
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        queue_id = int(payload.get("queue_id") or 0)
        if queue_id <= 0:
            return {"ok": False, "error": "queue_id is required"}
        return await asyncio.to_thread(remove_report_retry_item, queue_id)
