"""
plausibility/engine.py

Step 12 - evaluate plausibility rules over a dataset {table: [row dicts]}
and optionally repair generated rows.

Each rule/row outcome is one of
  pass        the rule holds
  violation   the rule is broken
  unknown     a value is missing or unparseable (or a joined parent row is
              absent), so the rule cannot be decided - counted separately,
              never silently treated as a pass
  n/a         a conditional rule whose 'when' does not apply

Reports contain counts, rates and row INDEXES only - never field values.
Repair is bounded (MAX_PASSES) and every repair is counted per rule.
"""

import random
from datetime import date, datetime, timedelta

MAX_PASSES = 3
MAX_REFS = 10


def _parse_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.strip()[:19]).date()
        except ValueError:
            return None
    return None


def _number(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _blank(v):
    return v is None or (isinstance(v, str) and not v.strip())


def _age_years(dob, today):
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


class _Context:
    def __init__(self, tables, today):
        self.tables = tables
        self.today = today
        self._indexes = {}

    def parent_row(self, table, key, value):
        idx = self._indexes.get((table, key))
        if idx is None:
            idx = {str(r.get(key)): r for r in self.tables.get(table, []) if r.get(key) is not None}
            self._indexes[(table, key)] = idx
        return idx.get(str(value)) if value is not None else None


def _outcome(rule, row, ctx):
    p = rule.params
    c = rule.check
    if c == "allowed_values":
        v = row.get(p["field"])
        if _blank(v):
            return "unknown"
        return "pass" if v in p["values"] or str(v) in {str(x) for x in p["values"]} else "violation"
    if c == "range":
        v = _number(row.get(p["field"]))
        if v is None:
            return "unknown"
        if p["min"] is not None and v < p["min"] or p["max"] is not None and v > p["max"]:
            return "violation"
        return "pass"
    if c == "pattern":
        v = row.get(p["field"])
        if _blank(v):
            return "unknown"
        return "pass" if p["regex"].fullmatch(str(v)) else "violation"
    if c == "age_range":
        dob = _parse_date(row.get(p["field"]))
        if dob is None:
            return "unknown"
        if dob > ctx.today:
            return "violation"
        return "pass" if p["min_years"] <= _age_years(dob, ctx.today) <= p["max_years"] else "violation"
    if c == "date_order":
        later = _parse_date(row.get(p["later"]))
        if "join" in p:
            j = p["join"]
            parent = ctx.parent_row(j["parent_table"], j["parent_key"], row.get(j["fk"]))
            if parent is None:
                return "unknown"
            earlier = _parse_date(parent.get(p["earlier"]))
        else:
            earlier = _parse_date(row.get(p["earlier"]))
        if earlier is None or later is None:
            return "unknown"
        if later < earlier:
            return "violation"
        if p["max_gap_days"] is not None and (later - earlier).days > p["max_gap_days"]:
            return "violation"
        return "pass"
    if c == "conditional":
        w, t = p["when"], p["then"]
        trigger = row.get(w["field"])
        if _blank(trigger):
            return "unknown"
        s = str(trigger)
        applies = (any(s.startswith(x) for x in w["prefixes"]) if "prefixes" in w
                   else s in {str(x) for x in w["values"]})
        if not applies:
            return "n/a"
        v = row.get(t["field"])
        if _blank(v):
            return "unknown"
        return "pass" if str(v) in {str(x) for x in t["values"]} else "violation"
    raise ValueError(f"Unknown check {c}")


def _repair(rule, row, ctx, rng):
    """Mutate ``row`` so the rule holds. Returns True if a repair was made."""
    p = rule.params
    c = rule.check
    if c == "allowed_values":
        row[p["field"]] = rng.choice(p["values"])
        return True
    if c == "range":
        value = rng.uniform(p["min"], p["max"])          # parse() guarantees both bounds
        row[p["field"]] = int(round(value)) if isinstance(row.get(p["field"]), int) else round(value, 2)
        return True
    if c == "age_range":
        age = rng.randint(p["min_years"], p["max_years"])
        dob = ctx.today - timedelta(days=age * 365 + rng.randint(0, 364))
        row[p["field"]] = dob.isoformat()
        return True
    if c == "date_order":
        if "join" in p:
            j = p["join"]
            parent = ctx.parent_row(j["parent_table"], j["parent_key"], row.get(j["fk"]))
            earlier = _parse_date(parent.get(p["earlier"])) if parent else None
        else:
            earlier = _parse_date(row.get(p["earlier"]))
        if earlier is None:
            return False
        gap = p["max_gap_days"] if p["max_gap_days"] is not None else 90
        row[p["later"]] = (earlier + timedelta(days=rng.randint(0, gap))).isoformat()
        return True
    if c == "conditional":
        row[p["then"]["field"]] = rng.choice(p["then"]["values"])
        return True
    return False                      # pattern: no safe automatic repair


def _applicable(rules, domain, tables):
    return [r for r in rules if r.domain == domain and r.table in tables]


def evaluate(tables: dict, rules: list, domain: str, today=None) -> dict:
    """Validate without changing anything. Returns a report."""
    today = today or date.today()
    ctx = _Context(tables, today)
    report_rules = []
    for rule in _applicable(rules, domain, tables):
        counts = {"pass": 0, "violation": 0, "unknown": 0, "n/a": 0}
        refs = []
        for i, row in enumerate(tables[rule.table]):
            o = _outcome(rule, row, ctx)
            counts[o] += 1
            if o == "violation" and len(refs) < MAX_REFS:
                refs.append(i)
        decided = counts["pass"] + counts["violation"]
        rate = counts["violation"] / decided if decided else 0.0
        if rule.severity == "hard":
            status = "fail" if counts["violation"] else "pass"
        else:
            status = "warn" if rate > rule.tolerance else "pass"
        report_rules.append({
            "rule": rule.ref, "severity": rule.severity, "check": rule.check, "table": rule.table,
            "explanation": rule.explanation, "status": status,
            "rows_checked": len(tables[rule.table]), "violations": counts["violation"],
            "unknown": counts["unknown"], "not_applicable": counts["n/a"],
            "violation_rate": round(rate, 4), "tolerance": rule.tolerance if rule.severity == "soft" else None,
            "violating_row_indexes": refs,
        })
    skipped = sorted({r.ref for r in rules if r.domain == domain and r.table not in tables})
    return {
        "domain": domain,
        "rules_evaluated": len(report_rules),
        "rules_not_applicable": skipped,
        "hard_failures": sum(1 for r in report_rules if r["status"] == "fail"),
        "soft_warnings": sum(1 for r in report_rules if r["status"] == "warn"),
        "passed": all(r["status"] != "fail" for r in report_rules),
        "rules": report_rules,
    }


def repair_and_evaluate(tables: dict, rules: list, domain: str, seed=None, today=None) -> dict:
    """Repair generated rows in place for hard rules with ``repair`` enabled,
    in bounded passes (later repairs can break earlier rules), then evaluate."""
    today = today or date.today()
    rng = random.Random(seed)
    repairs = {}
    hard = [r for r in _applicable(rules, domain, tables) if r.severity == "hard" and r.repair]
    passes = 0
    for passes in range(1, MAX_PASSES + 1):
        ctx = _Context(tables, today)
        changed = 0
        for rule in hard:
            for row in tables[rule.table]:
                if _outcome(rule, row, ctx) == "violation" and _repair(rule, row, ctx, rng):
                    repairs[rule.ref] = repairs.get(rule.ref, 0) + 1
                    changed += 1
        if not changed:
            break
    report = evaluate(tables, rules, domain, today=today)
    report["repairs"] = repairs
    report["repair_passes"] = passes
    return report
