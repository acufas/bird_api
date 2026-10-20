from typing import Any

from sqlalchemy import Engine, event


def enable_foreign_keys(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def set_foreign_keys_on(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
