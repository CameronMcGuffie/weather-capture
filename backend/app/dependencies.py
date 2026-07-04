from __future__ import annotations

from fastapi import Request

from app.database import Database
from app.ingestion import RTL433Manager


def get_database(request: Request) -> Database:
    return request.app.state.database  # type: ignore[no-any-return]


def get_ingestion_manager(request: Request) -> RTL433Manager:
    return request.app.state.ingestion  # type: ignore[no-any-return]
