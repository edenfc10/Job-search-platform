from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from aijaa.core.db import get_session, init_db
from aijaa.observability.logging import configure_logging

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="AIJAA — AI Job Applications Agent", version="0.1.0", lifespan=lifespan)
    static_dir = Path(__file__).with_name("static")
    from aijaa.api.routers.applications import router as applications_router
    from aijaa.api.routers.approvals import router as approvals_router
    from aijaa.api.routers.cv import router as cv_router
    from aijaa.api.routers.pipeline import router as pipeline_router
    from aijaa.api.routers.seekers import router as seekers_router
    from aijaa.core.config import get_settings

    app.include_router(cv_router)
    app.include_router(seekers_router)
    app.include_router(pipeline_router)
    app.include_router(approvals_router)
    app.include_router(applications_router)

    @app.middleware("http")
    async def disable_console_cache(request, call_next):
        """The local console changes frequently while the API is running with
        reload. Do not let a stale app.js keep calling an obsolete workflow."""
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    if not get_settings().production_mode:
        from aijaa.testkit.mockboard import create_mock_ats

        app.mount("/mockboard", create_mock_ats(), name="mockboard")

    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    async def console():
        return FileResponse(static_dir / "index.html")

    @app.get("/healthz")
    async def healthz():
        from aijaa.core.production import csv_items, production_status
        from aijaa.llm.factory import get_llms

        settings = get_settings()
        prod = production_status(settings)
        llm_mode = "unconfigured"
        if not (settings.production_mode and not prod.production_ready):
            llm_mode = get_llms().mode
        return {
            "status": "ok",
            "llm_mode": llm_mode,
            "dry_run": settings.dry_run,
            "configured_greenhouse_orgs": csv_items(settings.greenhouse_orgs),
            "configured_lever_orgs": csv_items(settings.lever_orgs),
            **prod.model_dump(),
        }

    @app.get("/metrics")
    async def metrics(s: AsyncSession = Depends(get_session)):
        from aijaa.observability.metrics import render_metrics

        return Response(await render_metrics(s), media_type="text/plain; version=0.0.4")

    return app


app = create_app()
