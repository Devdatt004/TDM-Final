"""
Profiling/aggregate_metrics.py

Step 11 - per-column aggregate metrics computed from a profiling sample.

Only aggregates leave this module. Privacy rules for what is emitted:

  * Every column: counts, null rate, distinct ratio, cardinality class,
    length statistics and value SHAPES (format signatures, digits->D,
    letters->A), never the values themselves.
  * Non-sensitive numeric/date columns: min/max, quantiles, histogram.
  * Sensitive numeric/date columns: inner quantiles only (p05-p95) and no
    min/max/histogram - extremes single out individuals (oldest patient,
    largest balance). Dates are coarsened to year-month.
  * Category frequencies only for non-sensitive, low-cardinality columns,
    and only for values seen at least K_MIN times (small cells suppressed).

All metrics describe the SAMPLE; ``sample_based`` says whether the sample
was smaller than the table (so distinct counts etc. are estimates).
"""

import math
import statistics
from collections import Counter
from datetime import date, datetime, timedelta

from Profiling.profiler import get_format_signature

METRICS_VERSION = "1.0"
K_MIN = 5                          # minimum count for a category value to be reported
MAX_CATEGORIES = 20
CATEGORICAL_MAX_DISTINCT = 50
HISTOGRAM_BINS = 10
MAX_SIGNATURE_LEN = 40
QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)
_EPOCH = datetime(1970, 1, 1)      # timedelta arithmetic: datetime.timestamp() fails pre-1970 on Windows


def _is_blank(v):
    return v is None or (isinstance(v, str) and not v.strip())


def _as_number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return None if isinstance(v, float) and not math.isfinite(v) else float(v)
    if isinstance(v, str):
        try:
            f = float(v.strip().replace(",", ""))
            return f if math.isfinite(f) else None
        except ValueError:
            return None
    return None


def _as_date(v):
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    if isinstance(v, str) and 8 <= len(v.strip()) <= 32:
        text = v.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text).replace(tzinfo=None)
        except ValueError:
            return None
    return None


def _infer_type(values):
    """numeric / datetime / text, by >= 95 % of non-null values parsing."""
    if not values:
        return "empty"
    threshold = math.ceil(len(values) * 0.95)
    # Strings that look like zero-padded codes (ZIP 01234, account 000123) are identifiers, not numbers.
    looks_code = sum(1 for v in values if isinstance(v, str) and len(v.strip()) > 1 and v.strip().startswith("0")
                     and v.strip().isdigit())
    if looks_code < len(values) * 0.05 and sum(_as_number(v) is not None for v in values) >= threshold:
        return "numeric"
    if sum(_as_date(v) is not None for v in values) >= threshold:
        return "datetime"
    return "text"


def _quantile(sorted_vals, q):
    """Linear-interpolated quantile of an already sorted list."""
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def _round(x):
    return round(x, 4) if isinstance(x, float) else x


def _numeric_metrics(nums, sensitive):
    nums = sorted(nums)
    out = {"quantiles": {f"p{int(q * 100):02d}": _round(_quantile(nums, q)) for q in QUANTILES}}
    out["mean"] = _round(statistics.fmean(nums))
    out["stddev"] = _round(statistics.pstdev(nums)) if len(nums) > 1 else 0.0
    if sensitive:
        out["suppressed"] = ["min", "max", "histogram"]
        return out
    out["min"], out["max"] = _round(nums[0]), _round(nums[-1])
    if nums[0] == nums[-1]:
        out["histogram"] = {"edges": [nums[0], nums[-1]], "counts": [len(nums)]}
    else:
        width = (nums[-1] - nums[0]) / HISTOGRAM_BINS
        counts = [0] * HISTOGRAM_BINS
        for x in nums:
            counts[min(int((x - nums[0]) / width), HISTOGRAM_BINS - 1)] += 1
        out["histogram"] = {"edges": [_round(nums[0] + i * width) for i in range(HISTOGRAM_BINS + 1)],
                            "counts": counts}
    return out


def _date_metrics(dates, sensitive):
    ordinals = sorted((d - _EPOCH).total_seconds() for d in dates)

    def fmt(ts):
        d = _EPOCH + timedelta(seconds=ts)
        return d.strftime("%Y-%m") if sensitive else d.isoformat(timespec="seconds")

    out = {"quantiles": {f"p{int(q * 100):02d}": fmt(_quantile(ordinals, q)) for q in QUANTILES}}
    if sensitive:
        out["suppressed"] = ["min", "max"]
        out["granularity"] = "month"
    else:
        out["min"], out["max"] = fmt(ordinals[0]), fmt(ordinals[-1])
    return out


def column_metrics(values, sensitive: bool, population_rows=None) -> dict:
    total = len(values)
    present = [v for v in values if not _is_blank(v)]
    texts = [str(v) for v in present]
    distinct = len(set(texts))
    distinct_ratio = distinct / len(present) if present else 0.0
    if not present:
        cardinality = "empty"
    elif distinct == 1:
        cardinality = "constant"
    elif distinct == len(present):
        cardinality = "unique"
    elif distinct <= CATEGORICAL_MAX_DISTINCT:
        cardinality = "low"
    else:
        cardinality = "high"

    inferred = _infer_type(present)
    lengths = [len(t) for t in texts]
    sig_counts = Counter(get_format_signature(t)[:MAX_SIGNATURE_LEN] for t in texts)

    out = {
        "metrics_version": METRICS_VERSION,
        "sample_rows": total,
        "population_rows": population_rows,
        "sample_based": population_rows is None or total < population_rows,
        "null_count": total - len(present),
        "null_rate": round((total - len(present)) / total, 4) if total else 0.0,
        "distinct_count": distinct,
        "distinct_ratio": round(distinct_ratio, 4),
        "cardinality": cardinality,
        "inferred_type": inferred,
        "sensitive": sensitive,
        "length": ({"min": min(lengths), "max": max(lengths), "mean": round(statistics.fmean(lengths), 2)}
                   if lengths else None),
        "formats": [{"signature": s, "share": round(n / len(texts), 4)} for s, n in sig_counts.most_common(5)],
    }
    if inferred == "numeric":
        out["numeric"] = _numeric_metrics([_as_number(v) for v in present], sensitive)
    elif inferred == "datetime":
        out["datetime"] = _date_metrics([_as_date(v) for v in present], sensitive)

    if sensitive:
        out["top_values"] = None
        out["top_values_suppressed"] = "sensitive column"
    elif cardinality in ("constant", "low"):
        freq = Counter(texts)
        kept = [{"value": v, "count": n} for v, n in freq.most_common(MAX_CATEGORIES) if n >= K_MIN]
        out["top_values"] = kept
        hidden = sum(1 for n in freq.values() if n < K_MIN)
        if hidden:
            out["top_values_suppressed"] = f"{hidden} value(s) seen fewer than {K_MIN} times"
    else:
        out["top_values"] = None
        out["top_values_suppressed"] = f"{cardinality} cardinality"
    return out


def table_metrics(rows: list, sensitivity: dict, population_rows=None) -> dict:
    """{column: metrics}. ``sensitivity`` maps column -> True if classified sensitive."""
    if not rows:
        return {}
    return {
        col: column_metrics([r.get(col) for r in rows], bool(sensitivity.get(col)), population_rows)
        for col in rows[0].keys()
    }
