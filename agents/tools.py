"""
agents/tools.py

Step 14 - the Query Agent's complete tool surface, and the policy that guards it.

Security model
  * Allowlist: these tools are the only things the agent can do. All are
    read-only queries over the METADATA store - no source connections, no
    SQL text, no shell, no writes.
  * Authorization lives here, in server code. ``tools_for(user)`` decides which
    tools the model is even shown, and ``execute()`` re-checks the caller's
    roles on every call - the model can propose a call but never widens its
    own scope (a hallucinated or injected tool name is simply refused).
  * Arguments are validated against the schema again server-side (types,
    enums, lengths) and table names are matched against known metadata; they
    are only ever used as ORM filter values.
  * Outputs are aggregates and classifications - never row values - capped
    in size, and returned as JSON data. Identifiers that originate from users
    (uploaded file / column names) are stripped of control characters and
    length-capped so they cannot smuggle formatting into the prompt.
"""

import json
import re
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from metadata_store.models import (
    AnalysisRun, ClassificationResult, ClassificationReview, ColumnProfile, SyntheticDataset,
)

MAX_OUTPUT_CHARS = 8000
MAX_LIST_ITEMS = 50
MAX_IDENTIFIER_LEN = 128
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f​-‏‪-‮⁦-⁩]")

REVIEWER_PLUS = frozenset({"admin", "steward", "reviewer"})
STEWARD_PLUS = frozenset({"admin", "steward"})


class ToolDenied(Exception):
    """Caller may not use this tool."""


class ToolInputError(ValueError):
    """Arguments failed server-side validation."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    allowed_roles: frozenset
    handler: Callable

    def definition(self) -> dict:
        # Length limits are enforced server-side in _validate(); they are left out of
        # the strict schema sent to the API, which constrains structure, not size.
        public = {k: {kk: vv for kk, vv in v.items() if kk != "maxLength"}
                  for k, v in self.input_schema["properties"].items()}
        return {"name": self.name, "description": self.description,
                "input_schema": dict(self.input_schema, properties=public), "strict": True}


def clean(value) -> str:
    """User-originated identifier -> safe, bounded plain text."""
    return _CONTROL_RE.sub("", str(value))[:MAX_IDENTIFIER_LEN]


def _schema(properties: dict, required=()) -> dict:
    return {"type": "object", "properties": properties, "required": list(required),
            "additionalProperties": False}


_TABLE = {"type": "string", "description": "A table name from list_profiled_tables.", "maxLength": MAX_IDENTIFIER_LEN}


def _validate(spec: ToolSpec, args) -> dict:
    """Re-check the input against the declared schema (never trust the wire)."""
    if not isinstance(args, dict):
        raise ToolInputError("Arguments must be an object.")
    props = spec.input_schema["properties"]
    unknown = set(args) - set(props)
    if unknown:
        raise ToolInputError(f"Unknown argument(s): {', '.join(sorted(clean(u) for u in unknown))}.")
    for name in spec.input_schema["required"]:
        if name not in args:
            raise ToolInputError(f"Missing argument '{name}'.")
    for name, value in args.items():
        rule = props[name]
        if rule["type"] == "string":
            if not isinstance(value, str) or len(value) > rule.get("maxLength", 200):
                raise ToolInputError(f"'{name}' must be a short string.")
            if "enum" in rule and value not in rule["enum"]:
                raise ToolInputError(f"'{name}' must be one of {rule['enum']}.")
        elif rule["type"] == "integer":
            if not isinstance(value, int) or isinstance(value, bool) or value < rule.get("minimum", 0):
                raise ToolInputError(f"'{name}' must be a non-negative integer.")
    return args


def _known_table(db: Session, table_name: str) -> str:
    exists = db.query(AnalysisRun.id).filter(AnalysisRun.source_table == table_name).first()
    if not exists:
        raise ToolInputError("Unknown table - call list_profiled_tables to see what has been profiled.")
    return table_name


def _latest_run(db: Session, table_name: str):
    return (db.query(AnalysisRun).filter(AnalysisRun.source_table == table_name)
            .order_by(AnalysisRun.run_timestamp.desc(), AnalysisRun.id.desc()).first())


# ── handlers (read-only, aggregate-only) ─────────────────────────────────────

def _list_profiled_tables(db, user, args):
    runs = db.query(AnalysisRun).order_by(AnalysisRun.run_timestamp.desc()).limit(500).all()
    seen, out = set(), []
    for r in runs:
        key = (r.source_table, r.source_id)
        if key in seen:
            continue
        seen.add(key)
        out.append({"table_name": clean(r.source_table), "source_id": r.source_id, "latest_run_id": r.id,
                    "run_at": r.run_timestamp.isoformat() if r.run_timestamp else None,
                    "fields": r.total_fields})
    return {"tables": out}


def _get_run_summary(db, user, args):
    run = _latest_run(db, _known_table(db, args["table_name"]))
    classes = {c.column_name: c for c in db.query(ClassificationResult).filter(ClassificationResult.run_id == run.id)}
    columns = []
    for col in run.columns:
        c = classes.get(col.column_name)
        columns.append({
            "column": clean(col.column_name), "pattern_type": col.pattern_type, "verdict": col.verdict,
            "null_percent": col.null_percent, "distinct_count": col.distinct_count,
            "sensitivity": c.sensitivity if c else None,
            "classification_status": c.classification_status if c else None,
            "detected_types": list(c.detected_types or []) if c else [],
        })
    return {"table_name": clean(run.source_table), "run_id": run.id,
            "run_at": run.run_timestamp.isoformat() if run.run_timestamp else None,
            "sampling_method": run.sampling_method, "sample_rows": run.sample_size,
            "population_rows": run.population_rows, "columns": columns}


def _get_column_metrics(db, user, args):
    run = _latest_run(db, _known_table(db, args["table_name"]))
    profiles = db.query(ColumnProfile).filter(ColumnProfile.run_id == run.id).all()
    out = []
    for p in profiles:
        m = dict(p.metrics or {})
        # Defence in depth: even non-sensitive category values stay out of the prompt.
        m.pop("top_values", None)
        out.append({"column": clean(p.column_name), **m})
    return {"table_name": clean(run.source_table), "run_id": run.id, "columns": out}


def _list_review_queue(db, user, args):
    status = args.get("status", "PENDING")
    q = db.query(ClassificationReview, ClassificationResult).join(
        ClassificationResult, ClassificationReview.classification_result_id == ClassificationResult.id)
    if status != "ALL":
        q = q.filter(ClassificationReview.status == status)
    if args.get("table_name"):
        q = q.filter(ClassificationResult.table_name == _known_table(db, args["table_name"]))
    rows = q.order_by(ClassificationReview.created_at.desc()).limit(200).all()
    return {"status": status, "items": [
        {"review_id": r.id, "status": r.status, "table_name": clean(c.table_name), "column": clean(c.column_name),
         "proposed_sensitivity": r.proposed_sensitivity, "confidence": c.sensitivity_confidence,
         "evidence": list(c.evidence or [])} for r, c in rows]}


def _get_release_status(db, user, args):
    q = db.query(SyntheticDataset)
    if args.get("table_name"):
        q = q.filter(SyntheticDataset.source_table == _known_table(db, args["table_name"]))
    out = []
    for d in q.order_by(SyntheticDataset.created_at.desc()).limit(100).all():
        report = d.validation_report or {}
        privacy = report.get("privacy") or {}
        failed = [c["check"] for t in (privacy.get("tables") or {}).values()
                  for c in t.get("checks", []) if c.get("status") == "fail"]
        out.append({"dataset_id": d.public_id, "table_name": clean(d.source_table), "rows": d.row_count,
                    "release_status": d.release_status, "failed_privacy_checks": failed,
                    "created_at": d.created_at.isoformat() if d.created_at else None})
    return {"datasets": out}


TOOLS = {t.name: t for t in (
    ToolSpec("list_profiled_tables",
             "List tables that have been profiled, with their latest run id. Call this first.",
             _schema({}), REVIEWER_PLUS, _list_profiled_tables),
    ToolSpec("get_run_summary",
             "Latest profiling run for a table: per-column pattern, verdict, null %, distinct count, "
             "sensitivity and classification status. No data values.",
             _schema({"table_name": _TABLE}, ["table_name"]), REVIEWER_PLUS, _get_run_summary),
    ToolSpec("get_column_metrics",
             "Aggregate column metrics (cardinality, length, format shapes, quantiles) for a table's latest run.",
             _schema({"table_name": _TABLE}, ["table_name"]), REVIEWER_PLUS, _get_column_metrics),
    ToolSpec("list_review_queue",
             "Human-review items for classifications, optionally for one table.",
             _schema({"status": {"type": "string", "enum": ["PENDING", "APPROVED", "REJECTED", "ALL"]},
                      "table_name": _TABLE}), REVIEWER_PLUS, _list_review_queue),
    ToolSpec("get_release_status",
             "Release-gate status of generated/masked datasets and which privacy checks failed.",
             _schema({"table_name": _TABLE}), STEWARD_PLUS, _get_release_status),
)}


def tools_for(user) -> list:
    """Tool definitions this caller may use - the model never sees the rest."""
    roles = set(user.roles or [])
    return [t.definition() for t in TOOLS.values() if roles & t.allowed_roles]


def _cap(payload: dict) -> str:
    """Serialize, shrinking lists until the result fits MAX_OUTPUT_CHARS."""
    text = json.dumps(payload, default=str, ensure_ascii=True)
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    for key, value in list(payload.items()):
        if isinstance(value, list) and len(value) > 1:
            limit = min(len(value), MAX_LIST_ITEMS)
            while limit > 1:
                limit //= 2
                trial = dict(payload, **{key: value[:limit], "truncated": True, f"{key}_total": len(value)})
                text = json.dumps(trial, default=str, ensure_ascii=True)
                if len(text) <= MAX_OUTPUT_CHARS:
                    return text
    return json.dumps({"error": "Result too large; ask about a single table."})


def execute(db: Session, user, name: str, args) -> str:
    """Authorize, validate and run one tool call. Raises ToolDenied / ToolInputError."""
    spec = TOOLS.get(name)
    if spec is None or not (set(user.roles or []) & spec.allowed_roles):
        raise ToolDenied(f"Tool '{clean(name)}' is not available to you.")
    return _cap(spec.handler(db, user, _validate(spec, args)))
