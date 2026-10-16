# api/routers/__init__.py
from fastapi import APIRouter
from api.routers import core, profiling, synthetic, connectors, relationships, logs, jobs, workflows, reviews

router = APIRouter()

router.include_router(core.router)
router.include_router(profiling.router)
router.include_router(synthetic.router)
router.include_router(connectors.router)
router.include_router(relationships.router)
router.include_router(logs.router)
router.include_router(jobs.router)
router.include_router(workflows.router)
router.include_router(reviews.router)
