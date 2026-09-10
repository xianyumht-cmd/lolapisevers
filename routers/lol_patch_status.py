from fastapi import APIRouter, HTTPException

from services.lol_patch_schedule_service import get_patch_status


router = APIRouter()


@router.get("/lol/patch-status")
async def lol_patch_status(date: str | None = None):
    try:
        return get_patch_status(date)
    except ValueError as exc:
        if str(exc) == "invalid_date":
            raise HTTPException(status_code=400, detail="invalid_date") from exc
        raise
