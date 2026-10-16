"""
Profiling/sampling.py

Step 11 - bounded, optionally stratified sampling for profiling.

Methods
  head        first N rows (SELECT ... LIMIT N). Cheapest; biased toward load order.
  random      uniform sample of N rows.
  stratified  proportional allocation across the values of one column, at
              least one row per stratum, so rare categories are not missed.
  auto        (default) random when the whole table fits in the pool cap -
              then the sample is exact-uniform and reproducible from the seed -
              otherwise head, so large sources are never fully scanned by default.

For random/stratified the connector supplies a bounded POOL of rows (the whole
table when it fits in ``pool_cap``; otherwise a database-side random pool of
``pool_cap`` rows) and the final selection is made here with a seeded RNG.
A sample is reproducible only when the pool was the whole table; the result
says so explicitly.
"""

import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

METHODS = ("auto", "head", "random", "stratified")
DEFAULT_SEED = 42
DEFAULT_POOL_CAP = 10_000
MAX_STRATA = 50


class SamplingError(ValueError):
    pass


@dataclass(frozen=True)
class SamplingSpec:
    method: str = "auto"
    size: int = 50
    seed: Optional[int] = DEFAULT_SEED
    stratify_by: Optional[str] = None
    pool_cap: int = DEFAULT_POOL_CAP

    def __post_init__(self):
        if self.method not in METHODS:
            raise SamplingError(f"Sampling method must be one of: {', '.join(METHODS)}.")
        if self.size < 1:
            raise SamplingError("Sample size must be at least 1.")
        if self.pool_cap < self.size:
            raise SamplingError("Pool cap must be at least the sample size.")
        if self.method == "stratified" and not self.stratify_by:
            raise SamplingError("Stratified sampling needs a stratify_by column.")

    def resolve(self, population: Optional[int]) -> str:
        """Concrete method for a table of ``population`` rows (None = unknown)."""
        if self.method != "auto":
            return self.method
        return "random" if population is not None and population <= self.pool_cap else "head"


def select_rows(pool: list, spec: SamplingSpec, method: str) -> list:
    """Pick ``spec.size`` rows from ``pool`` (already bounded by the connector)."""
    if method == "head" or len(pool) <= spec.size and method == "random":
        return pool[: spec.size]
    rng = random.Random(spec.seed)
    if method == "random":
        return rng.sample(pool, spec.size)
    return _stratified(pool, spec, rng)


def _stratified(pool: list, spec: SamplingSpec, rng: random.Random) -> list:
    if pool and spec.stratify_by not in pool[0]:
        raise SamplingError(f"Column '{spec.stratify_by}' does not exist in this table.")
    strata = defaultdict(list)
    for row in pool:
        strata[row.get(spec.stratify_by)].append(row)
    if len(strata) > MAX_STRATA:
        raise SamplingError(
            f"'{spec.stratify_by}' has more than {MAX_STRATA} distinct values - "
            "choose a lower-cardinality column to stratify by.")
    if len(pool) <= spec.size:
        return list(pool)

    # Proportional allocation with a floor of one row per stratum, then the
    # largest remainders get the leftover rows. Deterministic for a given seed.
    keys = sorted(strata, key=lambda k: (k is None, str(k)))
    if len(keys) > spec.size:
        raise SamplingError(
            f"Sample size {spec.size} is smaller than the {len(keys)} strata of '{spec.stratify_by}'.")
    quotas = {k: len(strata[k]) * spec.size / len(pool) for k in keys}
    alloc = {k: max(1, min(int(quotas[k]), len(strata[k]))) for k in keys}
    remaining = spec.size - sum(alloc.values())
    by_remainder = sorted(keys, key=lambda k: (quotas[k] - int(quotas[k])), reverse=True)
    while remaining > 0:
        progressed = False
        for k in by_remainder:
            if remaining and alloc[k] < len(strata[k]):
                alloc[k] += 1
                remaining -= 1
                progressed = True
        if not progressed:
            break
    while remaining < 0:                       # floors overshot: trim the largest strata
        k = max(keys, key=lambda x: alloc[x])
        alloc[k] -= 1
        remaining += 1

    sample = []
    for k in keys:
        sample.extend(rng.sample(strata[k], alloc[k]))
    return sample


def _info(spec: SamplingSpec, method: str, population, scanned: int, sample_rows: int, reproducible: bool) -> dict:
    return {
        "method": method,
        "requested_method": spec.method,
        "seed": spec.seed if method in ("random", "stratified") else None,
        "stratify_by": spec.stratify_by if method == "stratified" else None,
        "population_rows": population,
        "rows_scanned": scanned,
        "sample_rows": sample_rows,
        "reproducible": reproducible,
    }


def as_spec(limit_or_spec) -> SamplingSpec:
    """Plain int limits keep the historical SELECT ... LIMIT n behaviour."""
    if isinstance(limit_or_spec, SamplingSpec):
        return limit_or_spec
    return SamplingSpec(method="head", size=int(limit_or_spec), pool_cap=max(int(limit_or_spec), 1))


def draw(connector, table_name: str, spec: SamplingSpec, schema=None):
    """Sample a DB table through a DBConnector. Returns (rows, info)."""
    population = connector.count_rows(table_name, schema=schema)
    method = spec.resolve(population)
    if method == "head":
        rows = connector.sample(table_name, limit=spec.size, schema=schema)
        return rows, _info(spec, method, population, len(rows), len(rows),
                           reproducible=population is not None and population <= spec.size)
    whole_table = population is not None and population <= spec.pool_cap
    pool = connector.sample(table_name, limit=spec.pool_cap, schema=schema, random_order=not whole_table)
    rows = select_rows(pool, spec, method)
    return rows, _info(spec, method, population, len(pool), len(rows),
                       reproducible=whole_table and spec.seed is not None)


def draw_from_rows(all_rows: list, spec: SamplingSpec):
    """Sample rows already in memory (uploaded files). Returns (rows, info)."""
    population = len(all_rows)
    method = spec.resolve(population)
    pool = all_rows[: spec.pool_cap]
    rows = select_rows(pool, spec, method)
    return rows, _info(spec, method, population, len(pool), len(rows),
                       reproducible=(method == "head" or (population <= spec.pool_cap and spec.seed is not None)))
