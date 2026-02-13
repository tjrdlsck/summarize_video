"""FastAPI dependency helpers."""

from fastapi import Request

from app.core.container import AppContainer


def get_container(request: Request) -> AppContainer:
    """Returns the application-wide dependency container."""
    return request.app.state.container
