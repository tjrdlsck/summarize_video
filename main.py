"""Application entrypoint.

This module intentionally stays thin: app assembly now lives in `app/`.
"""

from app.factory import create_app

app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
