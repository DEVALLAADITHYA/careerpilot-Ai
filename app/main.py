from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.core import router
from app.config import get_settings
from app.database.connection import configure
from app.utils.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(get_settings().log_level)
    configure()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="CareerPilot AI", version="1.0.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
                       allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)
    return app


app = create_app()
