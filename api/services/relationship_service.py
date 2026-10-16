from sqlalchemy.orm import Session
from api.services.audit_service import log_activity_start, log_activity_finish
from api.services.profiling_service import run_profiling
from api.services import release_service
from Connectors.db_connector import DBConnector
from referential_integrity import service as ri_service, FEATURE_NAME
from synthetic_generation import generator as synthetic_generator
from sample_domains import registry as domains

# Activity-log / dashboard name for the generate-and-validate flow (see referential_integrity/__init__.py).
VALIDATION_ACTIVITY = FEATURE_NAME


def _source_connector(domain: str = domains.DEFAULT_DOMAIN):
    if not domains.is_available(domain):
        raise ValueError(f"Source domain '{domain}' is not available.")
    connector = DBConnector(domains.connection_string(domain))
    connector.connect()
    return connector


def _domain_for_tables(tables) -> str:
    """The domain that owns these tables. A related dataset never spans two domains."""
    found = {domains.domain_of_table(t) for t in tables}
    if None in found:
        unknown = sorted(t for t in tables if domains.domain_of_table(t) is None)
        raise ValueError(f"Unknown table(s): {', '.join(unknown)}")
    if len(found) > 1:
        raise ValueError("Select tables from one domain at a time: " + ", ".join(sorted(found)))
    return found.pop()


def _source_label(domain: str) -> str:
    return domains.DOMAINS[domain]["db_file"]


def list_domains():
    return {"default": domains.DEFAULT_DOMAIN, "domains": domains.available_domains()}


def get_relationships(db: Session, refresh: bool = False, domain: str = domains.DEFAULT_DOMAIN):
    return ri_service.relationship_overview(db, _source_connector(domain), refresh=refresh)


def get_relationship_health(db: Session, domain: str = domains.DEFAULT_DOMAIN):
    connector = _source_connector(domain)
    try:
        return ri_service.relationship_health(db, connector)
    finally:
        connector.close()


def refresh_relationships(db: Session, username: str, domain: str = domains.DEFAULT_DOMAIN):
    entry = log_activity_start(db, "Relationship Discovery", source=_source_label(domain), source_type="DB Schema", user=username)
    try:
        result = ri_service.relationship_overview(db, _source_connector(domain), refresh=True)
    except Exception as e:
        log_activity_finish(db, entry, "failed", str(e))
        raise e
    log_activity_finish(db, entry, "complete", f"{len(result['relationships'])} relationships across {len(result['tables'])} tables")
    return result


def get_relationship_suggestions(db: Session, username: str, domain: str = domains.DEFAULT_DOMAIN):
    entry = log_activity_start(db, "Relationship Discovery", source=_source_label(domain), source_type="DB Schema", user=username)
    try:
        found = ri_service.suggest_relationships(db, _source_connector(domain))
    except Exception as e:
        log_activity_finish(db, entry, "failed", str(e))
        raise e
    log_activity_finish(db, entry, "complete", f"{len(found)} possible undeclared relationships found")
    return {"suggestions": found, "min_match_percent": ri_service.MIN_INFERRED_MATCH}


def add_relationship(db: Session, child_table: str, child_column: str, parent_table: str, parent_column: str):
    domain = _domain_for_tables([child_table, parent_table])
    return ri_service.add_manual_relationship(db, _source_connector(domain), child_table, child_column, parent_table, parent_column)


def delete_relationship(db: Session, relationship_id: int):
    ri_service.delete_manual_relationship(db, relationship_id)


def generate_related_tables_flow(db: Session, tables: list[str], row_counts: dict, ensure_parent_coverage: bool, seed: int, username: str):
    domain = _domain_for_tables(tables)
    label = ", ".join(tables)[:200]
    entry = log_activity_start(db, VALIDATION_ACTIVITY, source=label, source_type="DB Tables", user=username)

    def profile_missing(table):
        p_entry = log_activity_start(db, "Profiling", source=table, source_type="DB Table", user=username)
        try:
            r = run_profiling(db, table, 50, username)
        except Exception as e:
            log_activity_finish(db, p_entry, "failed", str(e))
            raise ValueError(f"Could not profile '{table}': {e}")
        log_activity_finish(db, p_entry, "complete", f"{r['rows_sampled']} rows sampled, {r['total_fields']} fields classified", fields=r["total_fields"])

    try:
        result = ri_service.generate_related_dataset(
            db, _source_connector(domain), synthetic_generator, tables,
            row_counts=row_counts, ensure_parent_coverage=ensure_parent_coverage,
            seed=seed, profile_fn=profile_missing,
            postprocess=lambda tables: release_service.release_checks(db, tables, domain, seed=seed, username=username))
    except Exception as e:
        log_activity_finish(db, entry, "failed", str(e))
        raise e

    total_rows = sum(t["rows"] for t in result["tables"])
    log_activity_finish(
        db, entry, "complete" if result["published"] else "failed",
        f"{len(result['tables'])} tables, {total_rows} rows, integrity score {result['score']}%"
        + ("" if result["published"] else " - validation failed, nothing published"),
        fields=len(result["tables"]))
    return result

def get_integrity_runs(db: Session):
    return ri_service.list_integrity_runs(db)

def get_integrity_run(db: Session, run_id: int):
    return ri_service.get_integrity_run(db, run_id)
