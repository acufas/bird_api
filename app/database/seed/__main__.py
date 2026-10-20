from sqlmodel import Session

from app.database.db import engine
from app.database.seed import seed_birds

with Session(engine) as session:
    print(f"Inserted {seed_birds(session)} seed bird(s)")
engine.dispose()
