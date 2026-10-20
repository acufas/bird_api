import os
import subprocess
import sys

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import NullPool
from sqlmodel import Session

from app.config import settings
from app.database.reset import reset_database
from app.database.seed import load_seed_birds
from tests.conftest import PROJECT_ROOT
from tests.factories import add_bird
from tests.test_migrations import current_revision
from tests.test_seed import bird_rows, stored_birds


@pytest.fixture
def engine(alembic_config):
    engine = create_engine(settings.database_url, poolclass=NullPool)
    yield engine
    engine.dispose()


def seed_bird_rows():
    return bird_rows(load_seed_birds())


def run_reset_command(database_url):
    return subprocess.run(
        [sys.executable, "-m", "app.database.reset"],
        cwd=PROJECT_ROOT,
        env={**os.environ, "BIRD_API_DATABASE_URL": database_url},
        capture_output=True,
        text=True,
    )


def test_reset_creates_migrated_and_seeded_database_when_missing(alembic_config, engine):
    assert reset_database() == 1

    assert current_revision(engine) == ScriptDirectory.from_config(alembic_config).get_current_head()
    assert stored_birds(engine) == seed_bird_rows()


def test_reset_discards_existing_rows_and_tables(alembic_config, engine):
    command.upgrade(alembic_config, "head")
    with Session(engine) as session:
        add_bird(session, binomial_name="Turdus migratorius", genus="Turdus", species="migratorius")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE leftover (id INTEGER)")

    assert reset_database() == 1

    assert sorted(inspect(engine).get_table_names()) == ["alembic_version", "bird_images", "birds"]
    assert stored_birds(engine) == seed_bird_rows()


def test_reset_replaces_file_that_is_not_a_database(alembic_config, engine, tmp_path):
    (tmp_path / "migrated.db").write_bytes(b"not a database")

    assert reset_database() == 1

    assert stored_birds(engine) == seed_bird_rows()


def test_reset_seeds_with_foreign_keys_enabled(alembic_config, monkeypatch):
    pragma_values = []

    def record_foreign_keys(session):
        pragma_values.append(session.connection().exec_driver_sql("PRAGMA foreign_keys").scalar())
        return 0

    monkeypatch.setattr("app.database.reset.seed_birds", record_foreign_keys)

    reset_database()

    assert pragma_values == [1]


@pytest.mark.parametrize("database_url", ["postgresql://user@localhost/birds", "mysql://user@localhost/birds"])
def test_reset_refuses_non_sqlite_database(monkeypatch, database_url):
    monkeypatch.setattr(settings, "database_url", database_url)

    with pytest.raises(ValueError, match="only SQLite file databases can be reset"):
        reset_database()


@pytest.mark.parametrize("database_url", ["sqlite://", "sqlite:///:memory:", "sqlite:///file:birds?mode=memory&uri=true"])
def test_reset_refuses_in_memory_database(monkeypatch, database_url):
    monkeypatch.setattr(settings, "database_url", database_url)

    with pytest.raises(ValueError, match="in-memory SQLite databases cannot be reset"):
        reset_database()


def test_reset_command_rebuilds_configured_database(alembic_config, engine):
    with Session(engine) as session:
        command.upgrade(alembic_config, "head")
        add_bird(session, binomial_name="Turdus migratorius", genus="Turdus", species="migratorius")

    result = run_reset_command(settings.database_url)

    assert result.returncode == 0, result.stderr
    assert "inserted 1 seed bird(s)" in result.stdout
    assert stored_birds(engine) == seed_bird_rows()


def test_reset_command_refuses_non_sqlite_database():
    result = run_reset_command("postgresql://user@localhost/birds")

    assert result.returncode == 1
    assert "only SQLite file databases can be reset" in result.stderr
