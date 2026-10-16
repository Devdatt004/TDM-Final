"""
metadata_store/db.py

Sets up a SEPARATE database from hospital.db - this one stores OUR
analysis results (runs + per-column classifications), not the source
data itself. Keeping them separate mirrors the real architecture:
source systems vs. the canonical metadata store are always distinct.

We use SQLite here too for simplicity, but as a DIFFERENT file:
metadata_store.db. When you move to Postgres later, only this file
changes (the connection string) - nothing in api/main.py changes.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Where metadata_store.db lives. Defaults to the project root (unchanged
# local-dev behavior). In hosting environments with an ephemeral
# filesystem, set TDM_DATA_DIR to a persistent-disk mount path so this
# database survives restarts/redeploys - see DEPLOYMENT.md.
DATA_DIR = os.getenv(
    "TDM_DATA_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
os.makedirs(DATA_DIR, exist_ok=True)
DATABASE_URL = f"sqlite:///{os.path.join(DATA_DIR, 'metadata_store.db')}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base is what our ORM models (in models.py) will inherit from
Base = declarative_base()


def get_db():
    """
    A dependency for FastAPI - opens a database session for one request,
    and guarantees it's closed afterward (even if an error happens).
    FastAPI will call this automatically wherever a route asks for it.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()



