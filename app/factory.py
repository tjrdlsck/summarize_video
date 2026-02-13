"""FastAPI application factory."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routers import include_routers
from app.core.container import AppContainer
from app.core.paths import CLIPS_DIR, RESULTS_DIR, STATIC_DIR, TEMP_DIR, VIDEOS_DIR
from app.lifecycle import create_lifespan


def create_app() -> FastAPI:
    """Creates and configures the FastAPI app."""
    container = AppContainer()

    app = FastAPI(
        title="AI Video Analyst API",
        version="2.0",
        lifespan=create_lifespan(container),
    )

    app.state.container = container

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )

    os.makedirs(VIDEOS_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(CLIPS_DIR, exist_ok=True)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    include_routers(app)

    return app
