from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BIRD_API_")

    database_url: str = f"sqlite:///{Path(__file__).resolve().parent / 'database' / 'birds.db'}"
    log_level: str = "INFO"


settings = Settings()
