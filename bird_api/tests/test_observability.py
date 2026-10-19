import logging
import re
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, settings
from app.main import app
from app.observability import configure_logging

REQUEST_LINE = re.compile(
    r"^request_id=(?P<request_id>\S+) method=(?P<method>\S+) path=(?P<path>\S+) "
    r"status=(?P<status>\d{3}) duration_ms=(?P<duration_ms>\d+\.\d+)$"
)

client = TestClient(app)


@pytest.fixture
def failing_route():
    def boom():
        raise RuntimeError("boom")

    app.add_api_route("/test-only/boom", boom)
    route = app.router.routes[-1]
    yield TestClient(app, raise_server_exceptions=False)
    app.router.routes.remove(route)


def request_lines(caplog):
    return [record for record in caplog.records if record.name == "bird_api.request"]


def request_fields(record):
    match = REQUEST_LINE.match(record.getMessage())
    assert match is not None
    return match.groupdict()


def test_request_id_is_echoed_when_sent():
    response = client.get("/health/live", headers={"X-Request-ID": "abc123"})

    assert response.headers["X-Request-ID"] == "abc123"


def test_request_id_is_generated_when_absent():
    response = client.get("/health/live")

    assert UUID(response.headers["X-Request-ID"]).version == 4


def test_request_ids_differ_between_requests():
    first = client.get("/health/live").headers["X-Request-ID"]
    second = client.get("/health/live").headers["X-Request-ID"]

    assert first != second


def test_request_id_is_returned_on_not_found_response():
    response = client.get("/does-not-exist", headers={"X-Request-ID": "abc123"})

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "abc123"


def test_request_id_is_generated_on_validation_error_response():
    response = client.get("/api/v1/birds/not-a-uuid")

    assert response.status_code == 422
    assert UUID(response.headers["X-Request-ID"]).version == 4


def test_one_info_log_line_per_request(caplog):
    caplog.set_level(logging.INFO, logger="bird_api.request")

    client.get("/health/live", headers={"X-Request-ID": "abc123"})

    [record] = request_lines(caplog)
    assert record.levelno == logging.INFO
    fields = request_fields(record)
    assert fields["request_id"] == "abc123"
    assert fields["method"] == "GET"
    assert fields["path"] == "/health/live"
    assert fields["status"] == "200"
    assert float(fields["duration_ms"]) >= 0


def test_request_log_line_uses_generated_request_id_and_error_status(caplog):
    caplog.set_level(logging.INFO, logger="bird_api.request")

    response = client.get("/does-not-exist")

    [record] = request_lines(caplog)
    fields = request_fields(record)
    assert fields["request_id"] == response.headers["X-Request-ID"]
    assert fields["path"] == "/does-not-exist"
    assert fields["status"] == "404"


def test_unhandled_exception_returns_json_500_with_request_id(failing_route):
    response = failing_route.get("/test-only/boom", headers={"X-Request-ID": "abc123"})

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error", "request_id": "abc123"}
    assert response.headers["X-Request-ID"] == "abc123"


def test_unhandled_exception_generates_request_id_when_absent(failing_route):
    response = failing_route.get("/test-only/boom")

    request_id = response.headers["X-Request-ID"]
    assert UUID(request_id).version == 4
    assert response.json()["request_id"] == request_id


def test_unhandled_exception_is_logged_at_error_with_traceback(failing_route, caplog):
    caplog.set_level(logging.INFO, logger="bird_api")

    failing_route.get("/test-only/boom", headers={"X-Request-ID": "abc123"})

    [error] = [record for record in caplog.records if record.levelno == logging.ERROR and record.name.startswith("bird_api")]
    assert "request_id=abc123" in error.getMessage()
    assert error.exc_info[0] is RuntimeError
    [request_line] = request_lines(caplog)
    assert request_fields(request_line)["status"] == "500"


def test_log_level_defaults_to_info(monkeypatch):
    monkeypatch.delenv("BIRD_API_LOG_LEVEL", raising=False)

    assert Settings().log_level == "INFO"


def test_log_level_can_be_set_by_environment_variable(monkeypatch):
    monkeypatch.setenv("BIRD_API_LOG_LEVEL", "DEBUG")

    assert Settings().log_level == "DEBUG"


def test_app_loggers_use_configured_log_level():
    assert logging.getLogger("bird_api").level == logging.getLevelNamesMapping()[settings.log_level]


def test_configure_logging_sets_app_logger_level():
    logger = logging.getLogger("bird_api")
    original = logger.level
    try:
        configure_logging("WARNING")
        assert logger.level == logging.WARNING
    finally:
        logger.setLevel(original)


def test_configure_logging_does_not_add_duplicate_handlers():
    configure_logging(settings.log_level)
    configure_logging(settings.log_level)

    assert len(logging.getLogger("bird_api").handlers) == 1


def test_configure_logging_leaves_root_and_uvicorn_loggers_alone():
    root_level = logging.getLogger().level
    uvicorn_level = logging.getLogger("uvicorn").level
    root_handlers = list(logging.getLogger().handlers)
    try:
        configure_logging("DEBUG")
        assert logging.getLogger().level == root_level
        assert logging.getLogger().handlers == root_handlers
        assert logging.getLogger("uvicorn").level == uvicorn_level
    finally:
        configure_logging(settings.log_level)
