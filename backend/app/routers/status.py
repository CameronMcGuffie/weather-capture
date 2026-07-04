from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies import get_ingestion_manager
from app.ingestion import RTL433Manager
from app.schemas import IngestionStatusResponse

router = APIRouter(prefix="/api", tags=["status"])


@router.get("/status", response_model=IngestionStatusResponse)
async def get_status(manager: RTL433Manager = Depends(get_ingestion_manager)) -> IngestionStatusResponse:
    state = manager.state
    return IngestionStatusResponse(
        status=state.status.value,
        pid=state.pid,
        started_at=state.started_at,
        last_reading_at=state.last_reading_at,
        restart_count=state.restart_count,
        last_error=state.last_error,
        is_stale=manager.is_stale(),
    )
