import logging
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse

REQUEST_ID_HEADER = "X-Request-ID"

logger = logging.getLogger("bird_api")
request_logger = logging.getLogger("bird_api.request")


def configure_logging(level: str) -> None:
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)


async def track_request(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid4())
    request.state.request_id = request_id
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    started = time.perf_counter()
    try:
        response = await call_next(request)
        status_code = response.status_code
    finally:
        request_logger.info(
            "request_id=%s method=%s path=%s status=%d duration_ms=%.2f",
            request_id,
            request.method,
            request.url.path,
            status_code,
            (time.perf_counter() - started) * 1000,
        )
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


async def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
    request_id = request.state.request_id
    logger.error("unhandled exception request_id=%s", request_id, exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error", "request_id": request_id},
        headers={REQUEST_ID_HEADER: request_id},
    )


def setup_observability(app: FastAPI, log_level: str) -> None:
    configure_logging(log_level)
    app.middleware("http")(track_request)
    app.add_exception_handler(Exception, handle_unexpected_exception)
