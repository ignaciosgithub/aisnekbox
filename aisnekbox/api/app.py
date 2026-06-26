"""FastAPI application exposing the code-evaluation endpoint.

The endpoint is intentionally thin: it validates input with Pydantic, delegates
to :class:`aisnekbox.sandbox.Sandbox`, and maps sandbox errors to ``400``. The
blocking subprocess work runs in FastAPI's threadpool because the handler is a
regular ``def`` function.
"""

from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from .. import __version__
from ..config import Settings, get_settings
from ..models import EvalRequest, EvalResult
from ..sandbox import Sandbox, SandboxError

logger = logging.getLogger("aisnekbox")


def _get_sandbox(settings: Settings = Depends(get_settings)) -> Sandbox:
    return Sandbox(settings)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the ASGI application."""
    settings = settings or get_settings()
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    app = FastAPI(
        title="aisnekbox",
        version=__version__,
        description="Secure REST sandbox for executing untrusted Python code via NsJail.",
    )

    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok", "version": __version__}

    @app.post("/eval", response_model=EvalResult, tags=["eval"])
    def evaluate(request: EvalRequest, sandbox: Sandbox = Depends(_get_sandbox)) -> EvalResult:
        """Execute Python code in an isolated sandbox and return its output."""
        return sandbox.execute(request)

    @app.exception_handler(SandboxError)
    def _handle_sandbox_error(_request: Request, exc: SandboxError) -> JSONResponse:
        logger.warning("sandbox error: %s", exc)
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return app


app = create_app()
