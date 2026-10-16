"""
api/services/plausibility_service.py

Step 12 - glue between the plausibility engine, the rule registry and the
generation flows.

* Rules live in the Step 7 registry as rule_type PLAUSIBILITY. Only ACTIVE
  rules, at their current version, are enforced.
* The starter catalogue (plausibility/catalogue/<domain>.json) is imported as
  DRAFT so a domain owner must review and activate each rule.
* A table's domain comes from the built-in sample-domain registry. Uploaded
  files and registered sources have no domain, so no domain rules ever run
  on them unless explicitly configured (healthcare rules never touch banking).
"""

import json
import os

from fastapi import HTTPException
from sqlalchemy.orm import Session

from api.services import rule_service
from Connectors.db_connector import DBConnector
from metadata_store.models import Rule, RuleVersion
from plausibility import engine
from plausibility.rules import RuleDefinitionError, parse
from sample_domains import registry as domains

CATALOGUE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                             "plausibility", "catalogue")
SOURCE_CHECK_ROWS = 1000


def domain_for(table_name: str, source_id: str = None):
    if source_id:
        return None
    return domains.domain_of_table(table_name)


def _rules(db: Session, domain: str, statuses) -> list:
    rows = (db.query(Rule, RuleVersion)
            .join(RuleVersion, (RuleVersion.rule_id == Rule.id) & (RuleVersion.version_number == Rule.current_version))
            .filter(Rule.rule_type == "PLAUSIBILITY", Rule.status.in_(statuses))
            .order_by(Rule.rule_key).all())
    out = []
    for rule, version in rows:
        try:
            parsed = parse(version.definition, key=rule.rule_key, version=version.version_number)
        except RuleDefinitionError:
            continue                    # registry validates on write; skip anything legacy/corrupt
        if parsed.domain == domain:
            out.append(parsed)
    return out


def active_rules(db: Session, domain: str) -> list:
    return _rules(db, domain, (rule_service.ACTIVE,)) if domain else []


def load_catalogue(domain: str) -> dict:
    if domain not in domains.DOMAINS:
        raise HTTPException(status_code=404, detail=f"Unknown domain '{domain}'.")
    path = os.path.join(CATALOGUE_DIR, f"{domain}.json")
    if not os.path.exists(path):
        return {"domain": domain, "rules": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def import_catalogue(db: Session, domain: str, username: str) -> dict:
    """Create missing catalogue rules as DRAFT. Existing keys are left untouched."""
    catalogue = load_catalogue(domain)
    created, skipped = [], []
    for entry in catalogue["rules"]:
        if db.query(Rule).filter(Rule.rule_key == entry["rule_key"]).first():
            skipped.append(entry["rule_key"])
            continue
        rule_service.create_rule(
            db, rule_key=entry["rule_key"], name=entry["name"], rule_type="PLAUSIBILITY",
            definition=entry["definition"], description=catalogue.get("status_note"), created_by=username)
        created.append(entry["rule_key"])
    return {"domain": domain, "created_as_draft": created, "already_present": skipped}


def check_source(db: Session, domain: str, include_drafts: bool = True) -> dict:
    """Dry-run rules against the real source so a domain owner can calibrate
    them before activation. Aggregates only - no source values are returned."""
    if not domains.is_available(domain):
        raise HTTPException(status_code=404, detail=f"Unknown domain '{domain}'.")
    statuses = (rule_service.ACTIVE, rule_service.DRAFT) if include_drafts else (rule_service.ACTIVE,)
    rules = _rules(db, domain, statuses)
    needed = {r.table for r in rules} | {r.params["join"]["parent_table"] for r in rules if "join" in r.params}
    connector = DBConnector(domains.connection_string(domain))
    connector.connect()
    try:
        tables = {t: connector.sample(t, limit=SOURCE_CHECK_ROWS) for t in needed
                  if t in connector.list_table_names()}
    finally:
        connector.close()
    report = engine.evaluate(tables, rules, domain)
    report["source_rows_per_table_cap"] = SOURCE_CHECK_ROWS
    for r in report["rules"]:
        r.pop("violating_row_indexes", None)
    return report


def apply_to_generated(db: Session, tables: dict, domain, seed=None) -> dict:
    """Repair + validate generated tables. Returns the report (``passed`` False
    means a hard rule still fails and the dataset must not be published)."""
    rules = active_rules(db, domain)
    if not rules:
        return {"domain": domain, "rules_evaluated": 0, "passed": True, "rules": [],
                "note": "No ACTIVE plausibility rules for this domain."}
    return engine.repair_and_evaluate(tables, rules, domain, seed=seed)
