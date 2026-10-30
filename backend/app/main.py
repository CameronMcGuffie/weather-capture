from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import Database
from app.ingestion import RTL433Manager
from app.migrations import run_startup_migrations
from app.routers import insights, openclaw, status, weather

_log_level = getattr(logging, get_settings().log_level.upper(), logging.INFO)
logging.basicConfig(level=_log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# At DEBUG, aiosqlite logs every statement in full, burying the rtl_433 lines.
logging.getLogger("aiosqlite").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    database = Database(settings.database_path)
    await database.connect()
    # Before ingestion starts, so nothing is writing while history is repaired.
    await run_startup_migrations(database, settings.database_path)

    ingestion = RTL433Manager(settings, database)
    await ingestion.start()

    app.state.database = database
    app.state.ingestion = ingestion

    yield

    await ingestion.stop()
    await database.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Weather Capture", version="1.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(weather.router)
    app.include_router(status.router)
    app.include_router(openclaw.router)
    app.include_router(insights.router)

    static_dir = Path(settings.static_dir)
    if static_dir.is_dir():
        assets_dir = static_dir / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str) -> FileResponse:
            # An unknown API path must be a JSON 404, not the SPA's HTML page.
            if full_path == "api" or full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not Found")
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
