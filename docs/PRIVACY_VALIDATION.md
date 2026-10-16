# Privacy Validation and Release Gate (Step 13)

Schema validity is not a privacy guarantee. Every synthetic, related and masked dataset is
assessed against the source before it can be downloaded.

## Threat model

| | Assumption |
|---|---|
| **Audience** | Testers and developers in non-production environments; datasets may leak further (copied to laptops, tickets, vendors). |
| **Attacker knowledge** | Knows some real people in the source (a colleague's birth date, gender, postcode) and may hold public data. Does **not** hold the source DB or the pseudonymization key. |
| **Goal** | Recognise a real person in a released dataset, or learn a sensitive attribute about them. |
| **Released fields** | Every column in the output file. |
| **Out of scope** | Formal membership inference against a trained model, differential privacy. **This is not DP**; no privacy budget exists. |

## Checks

| Check | Question | Synthetic | Masked |
|---|---|---|---|
| `identifier_leakage` | Do direct identifiers (SSN, MRN, email, phone, account/card numbers, address…) carry real values? | any source value | the row's own original value (rows are aligned 1:1) |
| `substitute_coincidence` | Did a substituted value happen to equal the original? | — | ≤ 2 % (two people can share a first name) |
| `exact_row_matches` | Is any output row a copy of a source row (non-key columns)? | 0 % | n/a |
| `near_row_matches` | …identical except for one column? | ≤ 1 % | n/a |
| `unique_qi_matches` | Does an output row carry a quasi-identifier combination (DOB, gender, postcode, city, state…) that is **unique** in the source? Re-identification proxy. | ≤ 5 % | ≤ 5 % |
| k-anonymity (info) | Smallest QI class in the output; share of rows in classes smaller than k = 5. | report | report |
| utility (info) | Per-column distance to the source (total variation / scaled quantile shift; 0 = identical). | report | report |

Column roles come from the latest profiling classifications; surrogate keys (`id`, `*_id`, graph keys)
are excluded from row comparisons because a synthetic id of 17 matching a real id of 17 is chance.
Comparisons use up to 10,000 source rows (head sample) — the report states how many.

## Trade-offs behind the defaults (`builtin-1`)

* **0 % identifier leakage / exact copies.** No legitimate reason for a real SSN or a whole real
  record to appear; any hit means memorisation or a generator bug.
* **1 % near copies.** Low-cardinality tables (status, plan, gender) make "differs in one column"
  occasionally unavoidable; tighten to 0 for small, wide sensitive tables.
* **5 % source-unique QI matches.** Lower means less re-identification risk but forces the generator
  to distort DOB/postcode distributions, reducing utility. The utility report shows that cost.

## Policy and overrides

* Override thresholds per domain with an ACTIVE registry rule `privacy.release_policy.<domain>`
  (or `.default`), `rule_type = PRIVACY`, e.g. `{"synthetic": {"k": 10, "max_near_row_match_rate": 0}}`.
  Invalid policies are rejected on write; the report records `policy` as `key@vN` or `builtin-1`.
* A failed gate writes the file but marks the dataset **BLOCKED**: the preview is withheld and
  `GET /generate/download/{id}` returns 409 (the attempt is audited).
* `POST /api/v1/datasets/{id}/release-override` — **admin only**, reason ≥ 10 characters; stores actor,
  reason and time on the dataset and writes a `Privacy Gate Override` audit event.
* `GET /api/v1/datasets/{id}/validation` shows the full plausibility + privacy evidence.
* Datasets created before this gate have `release_status = NULL` and download as before.

## Current findings on the sample domains

All six sample generate/mask runs pass. Utility is the weak side: synthetic `patients` scores
mean distance **1.0** (the generator ignores source distributions — e.g. gender becomes a random
word), masked tables 0.2–0.4. Improving generator fidelity is separate work; the metric now makes
the gap visible.
