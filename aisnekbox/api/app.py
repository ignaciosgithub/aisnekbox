"""FastAPI application exposing the code-evaluation endpoint.

The endpoint is intentionally thin: it validates input with Pydantic, enforces
bounded concurrency, delegates to :class:`aisnekbox.sandbox.Sandbox`, and maps
sandbox errors to ``400``. The blocking subprocess work runs in FastAPI's
threadpool because the handler is a regular ``def`` function.

Observability is request-scoped and privacy-preserving: every request is tagged
with a generated identifier and logged with its method, path, status, duration
and (for evaluations) the returncode and output size. The submitted source code
and uploaded file contents are **never** logged.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from .. import __version__
from ..concurrency import CapacityError, Limiter
from ..config import Settings, get_settings
from ..models import EvalRequest, EvalResult
from ..sandbox import Sandbox, SandboxError

logger = logging.getLogger("aisnekbox")

REQUEST_ID_HEADER = "X-Request-ID"


def _get_settings_override(settings: Settings) -> Callable[[], Settings]:
    def _override() -> Settings:
        return settings

    return _override


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
    app.state.settings = settings
    app.state.limiter = Limiter(settings.max_concurrent_evals)
    app.dependency_overrides[get_settings] = _get_settings_override(settings)

    def _get_sandbox(settings: Settings = Depends(get_settings)) -> Sandbox:
        return Sandbox(settings)

    @app.middleware("http")
    async def observability(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        start = time.perf_counter()

        max_body = settings.max_request_body_size
        content_length = request.headers.get("content-length")
        too_large = (
            content_length is not None
            and content_length.isdigit()
            and int(content_length) > max_body
        )
        if too_large:
            logger.warning(
                "request rejected: body too large id=%s path=%s bytes=%s",
                request_id,
                request.url.path,
                content_length,
            )
            return JSONResponse(
                status_code=413,
                content={"detail": "request body too large"},
                headers={REQUEST_ID_HEADER: request_id},
            )

        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000.0
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "request id=%s method=%s path=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok", "version": __version__}

    @app.post("/eval", response_model=EvalResult, tags=["eval"])
    def evaluate(
        request: EvalRequest,
        http_request: Request,
        sandbox: Sandbox = Depends(_get_sandbox),
    ) -> EvalResult:
        """Execute Python code in an isolated sandbox and return its output."""
        limiter: Limiter = http_request.app.state.limiter
        request_id: str = http_request.state.request_id
        with limiter.slot():
            result = sandbox.execute(request)
        logger.info(
            "eval id=%s returncode=%s stdout_bytes=%d files=%d",
            request_id,
            result.returncode,
            len(result.stdout),
            len(result.files),
        )
        return result

    @app.exception_handler(SandboxError)
    def _handle_sandbox_error(request: Request, exc: SandboxError) -> JSONResponse:
        request_id: str = request.state.request_id
        logger.warning("sandbox error id=%s detail=%s", request_id, exc)
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(CapacityError)
    def _handle_capacity_error(request: Request, exc: CapacityError) -> JSONResponse:
        request_id: str = request.state.request_id
        logger.warning("capacity exceeded id=%s", request_id)
        return JSONResponse(
            status_code=429,
            content={"detail": "server at capacity, retry shortly"},
            headers={"Retry-After": "1"},
        )

    return app


app = create_app()
