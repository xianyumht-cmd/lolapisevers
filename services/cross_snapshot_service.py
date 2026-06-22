import asyncio
from datetime import datetime
from typing import Any, Dict, Optional

from db import Database


async def upsert_cross_snapshot(
    db: Optional[Database],
    *,
    query_name: str,
    region: str,
    display_name: str,
    payload_pretty: Dict[str, Any],
    payload_raw: Dict[str, Any],
) -> None:
    if db is None:
        return
    await asyncio.to_thread(
        db.upsert_cross_snapshot,
        query_name=query_name,
        region=region,
        display_name=display_name,
        payload_pretty=payload_pretty,
        payload_raw=payload_raw,
        is_success=True,
        updated_at=datetime.now(),
    )


async def get_cross_snapshot(db: Optional[Database], *, query_name: str, region: str) -> Optional[Dict[str, Any]]:
    if db is None:
        return None
    return await asyncio.to_thread(db.get_cross_snapshot, query_name=query_name, region=region)
