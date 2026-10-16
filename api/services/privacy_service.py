"""
api/services/privacy_service.py

Step 13 - privacy release gate for generated and masked datasets.

* Column roles come from the latest profiling run's classifications (Step 8/9)
  plus the relationship graph (keys).
* The release policy is the builtin default, overridable per domain by an
  ACTIVE rule in the registry with rule_type PRIVACY and key
  ``privacy.release_policy.<domain>`` (or ``privacy.release_policy.default``).
  The rule key@version is recorded with every report.
* A failed gate does not delete the dataset; it marks it BLOCKED so download
  is refused until an admin records an audited override.
"""

import copy

from fastapi import HTTPException
from sqlalchemy.orm import Session

from api.services.column_roles import IDENTIFIER_TYPES, graph_key_columns, is_key
from metadata_store.models import AnalysisRun, ClassificationResult, Rule, RuleVersion
from privacy.validation import BUILTIN_POLICY, BUILTIN_POLICY_VERSION, Roles, assess
from Profiling.sampling import SamplingSpec
from referential_integrity.service import load_graph

SOURCE_SAMPLE_CAP = 10_000
RELEASED, BLOCKED, OVERRIDDEN = "RELEASED", "BLOCKED", "OVERRIDDEN"

QUASI_IDENTIFIER_NAMES = {
    "date_of_birth", "dob", "birth_date", "birthdate", "gender", "sex", "postal_code", "zip",
    "zip_code", "zipcode", "pincode", "pin_code", "city", "state", "age", "marital_status",
    "ethnicity", "race", "occupation", "nationality",
}
DIRECT_IDENTIFIER_TYPES = set(IDENTIFIER_TYPES) | {"ADDRESS"}
_RATE_KEYS = {"max_identifier_leakage_rate", "max_substitute_coincidence_rate", "max_exact_row_match_rate",
              "max_near_row_match_rate", "max_unique_qi_match_rate"}


class PolicyError(ValueError):
    pass


def parse_policy(definition: dict) -> dict:
    """Merge a registry policy definition over the builtin one. Fails closed."""
    if not isinstance(definition, dict) or not set(definition) & set(BUILTIN_POLICY):
        raise PolicyError("A release policy defines 'synthetic' and/or 'masked' thresholds.")
    merged = copy.deepcopy(BUILTIN_POLICY)
    for kind, overrides in definition.items():
        if kind not in BUILTIN_POLICY:
            continue
        if not isinstance(overrides, dict):
            raise PolicyError(f"'{kind}' must be an object.")
        for key, value in overrides.items():
            if key == "k":
                if not isinstance(value, int) or isinstance(value, bool) or value < 2:
                    raise PolicyError("k must be an integer >= 2.")
            elif key in _RATE_KEYS:
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                          or not 0 <= value <= 1):
                    raise PolicyError(f"{key} must be a rate between 0 and 1 (or null to disable).")
            else:
                raise PolicyError(f"Unknown policy setting '{key}'.")
            merged[kind][key] = value
    return merged


def release_policy(db: Session, domain) -> tuple:
    """(policy dict, policy ref) for a domain."""
    keys = ([f"privacy.release_policy.{domain}"] if domain else []) + ["privacy.release_policy.default"]
    for key in keys:
        row = (db.query(Rule, RuleVersion)
               .join(RuleVersion, (RuleVersion.rule_id == Rule.id) & (RuleVersion.version_number == Rule.current_version))
               .filter(Rule.rule_key == key, Rule.rule_type == "PRIVACY", Rule.status == "ACTIVE").first())
        if row:
            rule, version = row
            try:
                return parse_policy(version.definition), f"{rule.rule_key}@v{version.version_number}"
            except PolicyError as exc:
                raise HTTPException(status_code=500, detail=f"Active privacy policy '{key}' is invalid: {exc}")
    return copy.deepcopy(BUILTIN_POLICY), BUILTIN_POLICY_VERSION


def _latest_classifications(db: Session, table: str, source_id):
    q = db.query(AnalysisRun).filter(AnalysisRun.source_table == table)
    q = q.filter(AnalysisRun.source_id.is_(None)) if source_id is None else q.filter(AnalysisRun.source_id == source_id)
    run = q.order_by(AnalysisRun.run_timestamp.desc(), AnalysisRun.id.desc()).first()
    if not run:
        return {}
    return {c.column_name: c for c in db.query(ClassificationResult).filter(ClassificationResult.run_id == run.id)}


def column_roles(db: Session, table: str, columns: list, source_id=None, substituted=()) -> Roles:
    classes = _latest_classifications(db, table, source_id)
    graph, _ = load_graph(db)
    keys = graph_key_columns(graph, table)
    roles = Roles(substituted=[c for c in columns if c in substituted])
    for col in columns:
        key = is_key(keys, col)
        c = classes.get(col)
        types = set([c.pattern_type] + list(c.detected_types or [])) if c else set()
        sensitive = c is not None and c.sensitivity == "sensitive"
        if not key:
            roles.compare.append(col)
        if sensitive and types & DIRECT_IDENTIFIER_TYPES and not key:
            roles.identifiers.append(col)
        elif col.lower() in QUASI_IDENTIFIER_NAMES or "DATE_OF_BIRTH" in types:
            roles.quasi_identifiers.append(col)
    return roles


def source_sample(db: Session, table: str, source_id=None, username=None) -> list:
    spec = SamplingSpec(method="head", size=SOURCE_SAMPLE_CAP, pool_cap=SOURCE_SAMPLE_CAP)
    if source_id:
        from api.services.source_connector_service import load_registered_source_data
        return load_registered_source_data(db, source_id, table, spec)[1]
    from api.services.source_service import load_source_data
    return load_source_data(db, table, spec, username)[0]


def assess_generated(db: Session, tables: dict, domain=None, source_id=None, username=None) -> dict:
    """Privacy report for synthetic tables {table: rows}."""
    policy, ref = release_policy(db, domain)
    reports = {}
    for table, rows in tables.items():
        if not rows:
            continue
        roles = column_roles(db, table, list(rows[0].keys()), source_id)
        source = source_sample(db, table, source_id, username)
        reports[table] = assess(rows, source, roles, "synthetic", policy["synthetic"], policy_ref=ref)
    return {"passed": all(r["passed"] for r in reports.values()), "policy": ref, "tables": reports}


def assess_masked(db: Session, table: str, masked: list, source_rows: list, plan: dict,
                  domain=None, source_id=None) -> dict:
    policy, ref = release_policy(db, domain)
    columns = list(plan)
    roles = column_roles(db, table, columns, source_id,
                         substituted={c for c, p in plan.items() if p["action"] == "substitute"})
    # Every tokenized column (keys included) must differ from the original.
    roles.identifiers = [c for c, p in plan.items() if p["action"] == "tokenize"]
    report = assess(masked, source_rows, roles, "masked", policy["masked"], policy_ref=ref)
    return {"passed": report["passed"], "policy": ref, "tables": {table: report}}


def release_status(privacy: dict) -> str:
    return RELEASED if privacy is None or privacy["passed"] else BLOCKED
