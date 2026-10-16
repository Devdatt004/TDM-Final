"""
privacy/validation.py

Step 13 - can a released dataset reveal source records?

Pure functions over in-memory rows. The caller supplies a bounded sample of
the source, the output rows, and column roles:

  identifiers        direct identifiers (SSN, MRN, email, account number...)
  quasi_identifiers  attributes that identify in combination (DOB, gender,
                     postal code, city...)
  compare            all non-key columns (surrogate keys are excluded: a
                     synthetic id of 17 matching a source id of 17 is chance)
  substituted        masked datasets only: columns replaced by generated values

Masked datasets are row-aligned with the source (row i masks source row i), so
their leakage check asks the sharper question "does a protected cell still hold
THIS row's original value?" rather than "does it occur anywhere in the source".

Metrics (all reported as counts and rates, never values)
  identifier_leakage    output identifier values that occur in the source column
  exact_row_matches     output rows equal to a source row on every compare column
  near_row_matches      ... equal on all but one compare column (not exact)
  unique_qi_matches     output rows whose quasi-identifier combination is UNIQUE
                        in the source sample - a re-identification proxy
  k_anonymity           smallest quasi-identifier class in the output and the
                        share of output rows in classes smaller than k
  utility               per-column distribution distance to the source

These are disclosure-risk heuristics on a source SAMPLE, not proofs. Nothing
here is differential privacy; see docs/PRIVACY_VALIDATION.md.
"""

from collections import Counter
from dataclasses import dataclass, field

CATEGORICAL_MAX_DISTINCT = 50
QUANTILES = (0.1, 0.25, 0.5, 0.75, 0.9)

# Builtin release policy, by dataset kind. Rates are fractions of output rows.
BUILTIN_POLICY_VERSION = "builtin-1"
BUILTIN_POLICY = {
    "synthetic": {
        "max_identifier_leakage_rate": 0.0,
        "max_exact_row_match_rate": 0.0,
        "max_near_row_match_rate": 0.01,
        "max_unique_qi_match_rate": 0.05,
        "k": 5,
    },
    "masked": {
        # Masked rows map 1:1 to source rows by design, so row-match checks do
        # not apply; what matters is that protected columns never carry the
        # row's original value and that pass-through quasi-identifiers do not
        # single people out. Substitutes may coincide by chance (two people
        # called "David"), hence a small allowance.
        "max_identifier_leakage_rate": 0.0,
        "max_substitute_coincidence_rate": 0.02,
        "max_exact_row_match_rate": None,
        "max_near_row_match_rate": None,
        "max_unique_qi_match_rate": 0.05,
        "k": 5,
    },
}


@dataclass
class Roles:
    identifiers: list = field(default_factory=list)
    quasi_identifiers: list = field(default_factory=list)
    compare: list = field(default_factory=list)
    substituted: list = field(default_factory=list)


def _norm(v):
    if v is None:
        return None
    s = " ".join(str(v).split()).lower()
    if not s:
        return None
    try:
        f = float(s)
        return str(int(f)) if f == int(f) else str(f)
    except ValueError:
        return s


def _tuple(row, cols):
    return tuple(_norm(row.get(c)) for c in cols)


def _rate(n, d):
    return round(n / d, 4) if d else 0.0


def identifier_leakage(output, source, identifiers):
    per_col = {}
    total_values = total_hits = 0
    for col in identifiers:
        src = {_norm(r.get(col)) for r in source} - {None}
        vals = [_norm(r.get(col)) for r in output]
        vals = [v for v in vals if v is not None]
        hits = sum(1 for v in vals if v in src)
        per_col[col] = {"values": len(vals), "found_in_source": hits, "rate": _rate(hits, len(vals))}
        total_values += len(vals)
        total_hits += hits
    return {"columns": per_col, "found_in_source": total_hits, "rate": _rate(total_hits, total_values)}


def aligned_leakage(output, source, columns):
    """Masked data: cells that still equal the same row's original value."""
    per_col = {}
    total_values = total_hits = 0
    for col in columns:
        pairs = [(_norm(o.get(col)), _norm(s.get(col))) for o, s in zip(output, source)]
        pairs = [(o, s) for o, s in pairs if o is not None and s is not None]
        hits = sum(1 for o, s in pairs if o == s)
        per_col[col] = {"values": len(pairs), "equal_to_original": hits, "rate": _rate(hits, len(pairs))}
        total_values += len(pairs)
        total_hits += hits
    return {"columns": per_col, "found_in_source": total_hits, "rate": _rate(total_hits, total_values)}


def row_matches(output, source, compare):
    if len(compare) < 2:
        return {"exact": 0, "near": 0, "exact_rate": 0.0, "near_rate": 0.0, "compared_columns": len(compare)}
    full = {_tuple(r, compare) for r in source}
    # "near" = equal on all but one column: index the source once per left-out column.
    leave_one_out = [
        {t[:i] + t[i + 1:] for t in full} for i in range(len(compare))
    ]
    exact = near = 0
    for r in output:
        t = _tuple(r, compare)
        if all(v is None for v in t):
            continue
        if t in full:
            exact += 1
        elif any(t[:i] + t[i + 1:] in leave_one_out[i] for i in range(len(compare))):
            near += 1
    return {"exact": exact, "near": near, "exact_rate": _rate(exact, len(output)),
            "near_rate": _rate(near, len(output)), "compared_columns": len(compare)}


def qi_risk(output, source, qis, k):
    if not qis:
        return {"quasi_identifiers": [], "unique_in_source_matches": 0, "rate": 0.0,
                "min_class_size": None, "rows_in_small_classes_rate": 0.0, "k": k}
    src_counts = Counter(_tuple(r, qis) for r in source)
    src_unique = {t for t, n in src_counts.items() if n == 1 and any(v is not None for v in t)}
    out_tuples = [_tuple(r, qis) for r in output]
    matches = sum(1 for t in out_tuples if t in src_unique)
    out_counts = Counter(out_tuples)
    small = sum(n for n in out_counts.values() if n < k)
    return {
        "quasi_identifiers": list(qis),
        "unique_in_source_matches": matches,
        "rate": _rate(matches, len(output)),
        "min_class_size": min(out_counts.values()) if out_counts else None,
        "rows_in_small_classes_rate": _rate(small, len(output)),
        "k": k,
    }


def _numeric(vals):
    out = []
    for v in vals:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            return None
    return out


def _quantile(sorted_vals, q):
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def utility(output, source, compare):
    """Per column: total variation distance (categorical) or mean absolute
    quantile shift scaled by the source IQR-ish spread (numeric). 0 = identical."""
    cols = {}
    for col in compare:
        s_vals = [r.get(col) for r in source if r.get(col) not in (None, "")]
        o_vals = [r.get(col) for r in output if r.get(col) not in (None, "")]
        if not s_vals or not o_vals:
            continue
        s_num, o_num = _numeric(s_vals), _numeric(o_vals)
        if s_num is not None and o_num is not None and len(set(s_num)) > CATEGORICAL_MAX_DISTINCT:
            s_num.sort(), o_num.sort()
            spread = (_quantile(s_num, 0.9) - _quantile(s_num, 0.1)) or 1.0
            shift = sum(abs(_quantile(s_num, q) - _quantile(o_num, q)) for q in QUANTILES) / len(QUANTILES)
            cols[col] = {"metric": "quantile_shift", "value": round(shift / spread, 4)}
            continue
        s_c, o_c = Counter(_norm(v) for v in s_vals), Counter(_norm(v) for v in o_vals)
        if len(s_c) > CATEGORICAL_MAX_DISTINCT:
            continue                      # free text / ids: no meaningful distribution
        keys = set(s_c) | set(o_c)
        tvd = 0.5 * sum(abs(s_c[k] / len(s_vals) - o_c[k] / len(o_vals)) for k in keys)
        cols[col] = {"metric": "total_variation", "value": round(tvd, 4)}
    mean = round(sum(c["value"] for c in cols.values()) / len(cols), 4) if cols else None
    return {"columns": cols, "mean_distance": mean}


def assess(output: list, source: list, roles: Roles, kind: str, policy: dict = None,
           policy_ref: str = BUILTIN_POLICY_VERSION) -> dict:
    """Run every check and apply the release policy for ``kind``."""
    policy = policy or BUILTIN_POLICY[kind]
    aligned = kind == "masked"
    if aligned:
        leak = aligned_leakage(output, source, roles.identifiers)
        substitutes = aligned_leakage(output, source, roles.substituted)
    else:
        leak = identifier_leakage(output, source, roles.identifiers)
        substitutes = None
    rows = row_matches(output, source, roles.compare)
    qi = qi_risk(output, source, roles.quasi_identifiers, policy.get("k", 5))

    checks = []

    def gate(name, value, limit, detail):
        if limit is None:
            checks.append({"check": name, "status": "not_applicable", "value": value, "limit": None, "detail": detail})
        else:
            checks.append({"check": name, "status": "pass" if value <= limit else "fail",
                           "value": value, "limit": limit, "detail": detail})

    gate("identifier_leakage", leak["rate"], policy.get("max_identifier_leakage_rate"),
         f"{leak['found_in_source']} identifier value(s) " +
         ("still equal the row's original value" if aligned else "also occur in the source sample"))
    if substitutes is not None:
        gate("substitute_coincidence", substitutes["rate"], policy.get("max_substitute_coincidence_rate"),
             f"{substitutes['found_in_source']} substituted value(s) happen to equal the row's original value")
    gate("exact_row_matches", rows["exact_rate"], policy.get("max_exact_row_match_rate"),
         f"{rows['exact']} output row(s) copy a source row")
    gate("near_row_matches", rows["near_rate"], policy.get("max_near_row_match_rate"),
         f"{rows['near']} output row(s) differ from a source row in only one column")
    gate("unique_qi_matches", qi["rate"], policy.get("max_unique_qi_match_rate"),
         f"{qi['unique_in_source_matches']} output row(s) carry a quasi-identifier combination unique in the source")

    return {
        "kind": kind,
        "policy": policy_ref,
        "thresholds": policy,
        "output_rows": len(output),
        "source_rows_compared": len(source),
        "roles": {"identifiers": roles.identifiers, "quasi_identifiers": roles.quasi_identifiers,
                  "compared_columns": roles.compare, "substituted": roles.substituted},
        "passed": all(c["status"] != "fail" for c in checks),
        "checks": checks,
        "identifier_leakage": leak,
        "substitute_coincidence": substitutes,
        "row_matches": rows,
        "quasi_identifier_risk": qi,
        "utility": utility(output, source, roles.compare),
        "note": "Heuristic disclosure-risk checks on a bounded source sample; not differential privacy.",
    }
