from pathlib import Path

from app.config import Settings, settings
from app.database import db

DEFAULT_DATABASE_PATH = Path(__file__).resolve().parent.parent / "app" / "database" / "birds.db"


def test_tests_do_not_use_real_database():
    assert settings.database_url != f"sqlite:///{DEFAULT_DATABASE_PATH}"
    assert db.engine.url.database is not None
    assert Path(db.engine.url.database).resolve() != DEFAULT_DATABASE_PATH


def test_database_url_defaults_to_absolute_birds_db_path(monkeypatch):
    monkeypatch.delenv("BIRD_API_DATABASE_URL", raising=False)

    assert Settings().database_url == f"sqlite:///{DEFAULT_DATABASE_PATH}"


def test_database_url_default_does_not_depend_on_working_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("BIRD_API_DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)

    assert Settings().database_url == f"sqlite:///{DEFAULT_DATABASE_PATH}"


def test_database_url_can_be_set_by_environment_variable(monkeypatch):
    monkeypatch.setenv("BIRD_API_DATABASE_URL", "sqlite:////tmp/other.db")

    assert Settings().database_url == "sqlite:////tmp/other.db"


def test_module_settings_is_a_settings_instance():
    assert isinstance(settings, Settings)
