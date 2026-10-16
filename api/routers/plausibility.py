"""
api/routers/plausibility.py

Step 12 - domain plausibility rules.

Rules themselves are managed through the rule registry (/api/v1/rules, rule_type
PLAUSIBILITY): edit, version, activate, deactivate. These endpoints cover the
starter catalogue and a dry-run against the real source.

RBAC mapping
------------
GET  /api/v1/plausibility/catalogue/{domain}         – reviewer+ (read proposed starter rules)
POST /api/v1/plausibility/catalogue/{domain}/import  – steward+  (create missing rules as DRAFT)
GET  /api/v1/plausibility/source-check/{domain}      – steward+  (aggregate violation rates on the source)
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth.dependencies import require_reviewer_or_above, require_steward_or_admin
from api.auth.models import CurrentUser
from api.services import audit_service, plausibility_service
from metadata_store.db import get_db

router = APIRouter(prefix="/api/v1/plausibility", tags=["Plausibility"])


@router.get("/catalogue/{domain}")
def get_catalogue(domain: str, user: CurrentUser = Depends(require_reviewer_or_above())):
    return plausibility_service.load_catalogue(domain)


@router.post("/catalogue/{domain}/import")
def import_catalogue(
    domain: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    result = plausibility_service.import_catalogue(db, domain, user.username)
    audit_service.record_audit(
        db, "Plausibility Catalogue Imported", user, "complete",
        f"{len(result['created_as_draft'])} rule(s) created as DRAFT for {domain}.",
        source=f"plausibility:{domain}", source_type="Rule Registry")
    return result


@router.get("/source-check/{domain}")
def source_check(
    domain: str,
    include_drafts: bool = True,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_steward_or_admin()),
):
    return plausibility_service.check_source(db, domain, include_drafts=include_drafts)
