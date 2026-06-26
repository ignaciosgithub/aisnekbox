"""Console entrypoint: run the API server with uvicorn."""

from __future__ import annotations

import uvicorn

from .config import get_settings


def main() -> None:
    """Start the aisnekbox API server."""
    settings = get_settings()
    uvicorn.run(
        "aisnekbox.api.app:app",
        host=settings.host,
        port=settings.port,
        log_level="debug" if settings.debug else "info",
    )


if __name__ == "__main__":
    main()
