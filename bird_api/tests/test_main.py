import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

from app.database.db import get_session
from app.main import app

client = TestClient(app)


def override_session(database_url, **engine_options):
    engine = create_engine(database_url, connect_args={"check_same_thread": False}, **engine_options)

    def session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    yield
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def working_database():
    yield from override_session("sqlite://", poolclass=StaticPool)


@pytest.fixture
def failing_database(tmp_path):
    yield from override_session(f"sqlite:///{tmp_path / 'missing' / 'birds.db'}")


def test_live_returns_ok():
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_ok_when_database_answers(working_database):
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_503_when_database_query_fails(failing_database):
    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_old_health_route_is_removed():
    response = client.get("/health")

    assert response.status_code == 404


def test_health_routes_are_unversioned():
    assert client.get("/api/v1/health/live").status_code == 404
    assert client.get("/api/v1/health/ready").status_code == 404
