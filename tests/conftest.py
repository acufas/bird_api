import os
import tempfile
from pathlib import Path

test_database_directory = tempfile.TemporaryDirectory()
os.environ["BIRD_API_DATABASE_URL"] = f"sqlite:///{Path(test_database_directory.name) / 'birds.db'}"

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings
from app.database import db
from app.database.db import get_session
from app.database.sqlite import enable_foreign_keys
from app.main import app

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def pytest_unconfigure():
    db.engine.dispose()
    test_database_directory.cleanup()


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    enable_foreign_keys(engine)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def alembic_config(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 'migrated.db'}")
    return Config(PROJECT_ROOT / "alembic.ini")


@pytest.fixture
def migrated_engine(alembic_config):
    command.upgrade(alembic_config, "head")
    engine = create_engine(settings.database_url)
    yield engine
    engine.dispose()
