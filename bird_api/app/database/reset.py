from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import make_url
from sqlmodel import Session, create_engine

from app.config import settings
from app.database.seed import seed_birds
from app.database.sqlite import enable_foreign_keys

ALEMBIC_CONFIG_PATH = Path(__file__).resolve().parents[2] / "alembic.ini"


def sqlite_database_path(database_url: str) -> Path:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise ValueError(f"only SQLite file databases can be reset, not {url.get_backend_name()}")
    if not url.database or url.database == ":memory:" or url.query.get("mode") == "memory":
        raise ValueError("in-memory SQLite databases cannot be reset")
    return Path(url.database)


def reset_database() -> int:
    database_url = settings.database_url
    sqlite_database_path(database_url).unlink(missing_ok=True)
    command.upgrade(Config(ALEMBIC_CONFIG_PATH), "head")
    engine = create_engine(database_url)
    enable_foreign_keys(engine)
    try:
        with Session(engine) as session:
            return seed_birds(session)
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        inserted = reset_database()
    except ValueError as error:
        raise SystemExit(f"Refusing to reset the database: {error}") from error
    print(f"Reset {settings.database_url} and inserted {inserted} seed bird(s)")
