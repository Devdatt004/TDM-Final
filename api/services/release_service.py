"""
api/services/release_service.py

Pre-release checks for generated data, combined into one envelope that is
stored on every SyntheticDataset (``validation_report``):

  {"passed": bool,             # False -> plausibility hard failure, nothing is written
   "plausibility": report|None,# Step 12
   "privacy": report|None,     # Step 13
   "release_status": "RELEASED" | "BLOCKED"}

Plausibility repairs rows first; privacy is assessed on the repaired rows.
A privacy failure does not stop the file being written - it marks the
dataset BLOCKED so download is refused until an audited admin override.
"""

from sqlalchemy.orm import Session

from api.services import plausibility_service, privacy_service


def release_checks(db: Session, tables: dict, domain, seed=None, source_id=None, username=None) -> dict:
    plausibility = plausibility_service.apply_to_generated(db, tables, domain, seed=seed) if domain else None
    if plausibility is not None and not plausibility["passed"]:
        return {"passed": False, "plausibility": plausibility, "privacy": None, "release_status": None}
    privacy = privacy_service.assess_generated(db, tables, domain, source_id=source_id, username=username)
    return {"passed": True, "plausibility": plausibility, "privacy": privacy,
            "release_status": privacy_service.release_status(privacy)}
