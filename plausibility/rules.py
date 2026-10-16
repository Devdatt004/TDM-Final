"""
plausibility/rules.py

Step 12 - declarative plausibility rule schema.

A rule is a JSON definition stored as a PLAUSIBILITY rule in the Step 7 rule
registry (so it is versioned, owned and DRAFT/ACTIVE managed there). Only the
check kinds below exist - definitions cannot contain code or arbitrary SQL.

Common fields
  domain       e.g. "healthcare"; a rule never runs on another domain's data
  severity     "hard" (must never fail; blocks release) | "soft" (statistical
               preference; reported with a tolerance, never blocks)
  table        table the rule is about
  explanation  what the rule asserts, in plain words
  rationale    why (clinical/business source); required
  owner        accountable domain owner
  tolerance    soft rules only: max acceptable violation rate (0..1)
  repair       optional bool; hard rules may repair violating generated rows

Check kinds (``check`` field)
  allowed_values  field, values
  range           field, min and/or max (numbers)
  pattern         field, regex (full match)
  age_range       field (birth date), min_years, max_years   (as of today)
  date_order      earlier, later  - same-row field names, or
                  earlier/later + join {fk, parent_table, parent_key} where
                  ``earlier`` is a parent field and ``later`` a child field;
                  optional max_gap_days
  conditional     when {field, prefixes|values}, then {field, values}
"""

import re
from dataclasses import dataclass, field

CHECKS = {"allowed_values", "range", "pattern", "age_range", "date_order", "conditional"}
SEVERITIES = {"hard", "soft"}
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,99}$")
MAX_REGEX_LEN = 200


class RuleDefinitionError(ValueError):
    pass


@dataclass(frozen=True)
class PlausibilityRule:
    key: str
    version: int
    domain: str
    severity: str
    check: str
    table: str
    params: dict = field(default_factory=dict)
    explanation: str = ""
    rationale: str = ""
    owner: str = ""
    tolerance: float = 0.0
    repair: bool = False

    @property
    def ref(self) -> str:
        return f"{self.key}@v{self.version}"


def _name(value, what):
    if not isinstance(value, str) or not _NAME_RE.match(value):
        raise RuleDefinitionError(f"{what} must be a plain table/column name.")
    return value


def _require(defn, key):
    if key not in defn:
        raise RuleDefinitionError(f"'{key}' is required for check '{defn.get('check')}'.")
    return defn[key]


def parse(definition: dict, key: str = "inline", version: int = 1) -> PlausibilityRule:
    """Validate a definition and return a rule. Raises RuleDefinitionError."""
    if not isinstance(definition, dict):
        raise RuleDefinitionError("Definition must be an object.")
    d = definition
    check = d.get("check")
    if check not in CHECKS:
        raise RuleDefinitionError(f"check must be one of: {', '.join(sorted(CHECKS))}.")
    severity = d.get("severity")
    if severity not in SEVERITIES:
        raise RuleDefinitionError("severity must be 'hard' or 'soft'.")
    domain = d.get("domain")
    if not isinstance(domain, str) or not domain.strip():
        raise RuleDefinitionError("domain is required.")
    for text_field in ("explanation", "rationale"):
        if not isinstance(d.get(text_field), str) or not d[text_field].strip():
            raise RuleDefinitionError(f"{text_field} is required.")
    table = _name(d.get("table"), "table")
    tolerance = d.get("tolerance", 0.0)
    if not isinstance(tolerance, (int, float)) or not 0 <= tolerance <= 1:
        raise RuleDefinitionError("tolerance must be between 0 and 1.")
    if severity == "hard" and tolerance:
        raise RuleDefinitionError("Hard rules cannot have a tolerance.")
    repair = d.get("repair", False)
    if not isinstance(repair, bool):
        raise RuleDefinitionError("repair must be true or false.")
    if repair and severity != "hard":
        raise RuleDefinitionError("Only hard rules may repair generated rows.")
    if repair and check == "pattern":
        raise RuleDefinitionError("Pattern rules cannot be repaired automatically.")

    params = {}
    if check == "allowed_values":
        params["field"] = _name(_require(d, "field"), "field")
        values = _require(d, "values")
        if not isinstance(values, list) or not values or not all(isinstance(v, (str, int, float)) for v in values):
            raise RuleDefinitionError("values must be a non-empty list of scalars.")
        params["values"] = values
    elif check == "range":
        params["field"] = _name(_require(d, "field"), "field")
        lo, hi = d.get("min"), d.get("max")
        if lo is None and hi is None:
            raise RuleDefinitionError("range needs min and/or max.")
        for bound in (lo, hi):
            if bound is not None and (isinstance(bound, bool) or not isinstance(bound, (int, float))):
                raise RuleDefinitionError("min/max must be numbers.")
        if lo is not None and hi is not None and lo > hi:
            raise RuleDefinitionError("min must not exceed max.")
        if repair and (lo is None or hi is None):
            raise RuleDefinitionError("A repairable range rule needs both min and max.")
        params.update(min=lo, max=hi)
    elif check == "pattern":
        params["field"] = _name(_require(d, "field"), "field")
        regex = _require(d, "regex")
        if not isinstance(regex, str) or len(regex) > MAX_REGEX_LEN:
            raise RuleDefinitionError(f"regex must be a string of at most {MAX_REGEX_LEN} characters.")
        try:
            params["regex"] = re.compile(regex)
        except re.error as exc:
            raise RuleDefinitionError(f"Invalid regex: {exc}") from exc
    elif check == "age_range":
        params["field"] = _name(_require(d, "field"), "field")
        lo, hi = _require(d, "min_years"), _require(d, "max_years")
        if not all(isinstance(x, int) and not isinstance(x, bool) for x in (lo, hi)) or not 0 <= lo <= hi <= 150:
            raise RuleDefinitionError("min_years/max_years must be integers with 0 <= min <= max <= 150.")
        params.update(min_years=lo, max_years=hi)
    elif check == "date_order":
        params["earlier"] = _name(_require(d, "earlier"), "earlier")
        params["later"] = _name(_require(d, "later"), "later")
        gap = d.get("max_gap_days")
        if gap is not None and (not isinstance(gap, int) or isinstance(gap, bool) or gap < 0):
            raise RuleDefinitionError("max_gap_days must be a non-negative integer.")
        params["max_gap_days"] = gap
        join = d.get("join")
        if join is not None:
            if not isinstance(join, dict):
                raise RuleDefinitionError("join must be an object.")
            params["join"] = {
                "fk": _name(join.get("fk"), "join.fk"),
                "parent_table": _name(join.get("parent_table"), "join.parent_table"),
                "parent_key": _name(join.get("parent_key"), "join.parent_key"),
            }
    elif check == "conditional":
        when, then = _require(d, "when"), _require(d, "then")
        if not isinstance(when, dict) or not isinstance(then, dict):
            raise RuleDefinitionError("when/then must be objects.")
        w = {"field": _name(when.get("field"), "when.field")}
        if isinstance(when.get("prefixes"), list) and when["prefixes"]:
            w["prefixes"] = [str(p) for p in when["prefixes"]]
        elif isinstance(when.get("values"), list) and when["values"]:
            w["values"] = when["values"]
        else:
            raise RuleDefinitionError("when needs a non-empty 'prefixes' or 'values' list.")
        if not isinstance(then.get("values"), list) or not then["values"]:
            raise RuleDefinitionError("then.values must be a non-empty list.")
        params["when"] = w
        params["then"] = {"field": _name(then.get("field"), "then.field"), "values": then["values"]}

    return PlausibilityRule(
        key=key, version=version, domain=domain.strip().lower(), severity=severity, check=check,
        table=table, params=params, explanation=d["explanation"].strip(), rationale=d["rationale"].strip(),
        owner=str(d.get("owner") or "").strip(), tolerance=float(tolerance), repair=repair,
    )
