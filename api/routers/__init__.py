# api/routers/__init__.py
from fastapi import APIRouter
from api.routers import (
    core, profiling, synthetic, connectors, relationships, logs,
    jobs, workflows, reviews, plausibility, datasets, sources, rules,
)

# Routers written without a version prefix. Mounted at /api/v1 (canonical,
# documented) and, temporarily, at their old unversioned paths (deprecated
# aliases, hidden from OpenAPI). Both mounts share the same handlers.
unversioned_router = APIRouter()
unversioned_router.include_router(core.router)
unversioned_router.include_router(profiling.router)
unversioned_router.include_router(synthetic.router)
unversioned_router.include_router(connectors.router)
unversioned_router.include_router(relationships.router)
unversioned_router.include_router(logs.router)

# Routers that already carry their /api/v1/... prefix.
v1_router = APIRouter()
for module in (jobs, workflows, reviews, plausibility, datasets, sources, rules):
    v1_router.include_router(module.router)
