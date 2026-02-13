"""Application package for the refactored FastAPI server."""


def create_app():
    """Lazy import wrapper to avoid eager heavy dependency imports."""
    from app.factory import create_app as _create_app

    return _create_app()
