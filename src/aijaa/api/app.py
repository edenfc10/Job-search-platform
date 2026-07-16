from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Response
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

    from aijaa.api.routers.applications import router as applications_router
    from aijaa.api.routers.approvals import router as approvals_router
    from aijaa.api.routers.pipeline import router as pipeline_router
    from aijaa.api.routers.seekers import router as seekers_router

    app.include_router(seekers_router)
    app.include_router(pipeline_router)
    app.include_router(approvals_router)
    app.include_router(applications_router)

    @app.get("/healthz")
    async def healthz():
        from aijaa.core.config import get_settings
        from aijaa.llm.factory import get_llms

        return {
            "status": "ok",
            "llm_mode": get_llms().mode,
            "dry_run": get_settings().dry_run,
        }

    @app.get("/metrics")
    async def metrics(s: AsyncSession = Depends(get_session)):
        from aijaa.observability.metrics import render_metrics

        return Response(await render_metrics(s), media_type="text/plain; version=0.0.4")

    return app


app = create_app()
