"""
api/main.py

FastAPI backend - Setup and router registration.
Business logic is delegated to the Service Layer and Routers.
"""

import asyncio
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routers.sources import router as sources_router
from api.routers.rules import router as rules_router

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(BASE_DIR, "Connectors"))
sys.path.append(os.path.join(BASE_DIR, "Profiling"))
sys.path.append(os.path.join(BASE_DIR, "pattern_analysis"))
sys.path.append(os.path.join(BASE_DIR, "agents"))
sys.path.append(os.path.join(BASE_DIR, "synthetic_generation"))
sys.path.append(BASE_DIR)

from metadata_store.db import Base, engine, get_db, SessionLocal
from metadata_store import activity as act
from metadata_store import audit
from metadata_store.seed import seed_data_dictionary

from api.services import audit_service
from api.routers import router as api_router

# Schema initialization and migrations are now handled via Alembic.

try:                                     # built-in sample sources are rebuilt if missing
    from sample_domains import registry as _domains
    _domains.ensure_domain_databases()
    _domains.check_table_names_disjoint()
except Exception as e:
    print(f"Sample domain setup failed: {e}")

_seed_db = SessionLocal()
try:
    seed_data_dictionary(_seed_db)
    act.backfill_from_runs(_seed_db)
finally:
    _seed_db.close()

def _purge_once():
    session = SessionLocal()
    try:
        audit_service.purge_old_logs(session)
    except Exception as e:
        print(f"Log cleanup failed: {e}")
    finally:
        session.close()

async def _purge_loop():
    while True:
        await asyncio.sleep(act.LOG_PURGE_INTERVAL_SECONDS)
        await asyncio.to_thread(_purge_once)

@asynccontextmanager
async def lifespan(_app):
    _purge_once()
    task = asyncio.create_task(_purge_loop())
    yield
    task.cancel()

app = FastAPI(title="TDM Platform API", lifespan=lifespan)

_DEFAULT_ORIGINS = "http://localhost:5500,http://127.0.0.1:5500,http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173"
ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in os.getenv("TDM_ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
    "Authorization",
    "Content-Type",
    "X-Dev-User",
    "X-Dev-Roles",
],
)

# Register all routers
app.include_router(api_router)
app.include_router(sources_router)
app.include_router(rules_router)
