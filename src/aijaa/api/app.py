from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from aijaa.core.db import init_db

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)


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

    return app


app = create_app()
