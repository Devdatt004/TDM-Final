# Domain Plausibility Rules (Step 12)

Generated data must not be logically impossible (a patient born after their own appointment,
blood group "Table"). Plausibility rules catch that before a dataset is written.

## How it fits together

| Piece | Where |
|---|---|
| Rule schema (declarative — no code, no SQL) | `plausibility/rules.py` |
| Evaluation + bounded repair | `plausibility/engine.py` |
| Starter catalogue (proposed) | `plausibility/catalogue/healthcare.json` |
| Storage, versions, DRAFT/ACTIVE | Rule registry, `rule_type = PLAUSIBILITY` (`/api/v1/rules`) |
| Catalogue import / source dry-run | `/api/v1/plausibility/...` |
| Enforcement | `/generate/{table}` and `/generate-related`, before any CSV is written |

## Workflow for a domain owner

1. `POST /api/v1/plausibility/catalogue/healthcare/import` — creates the starter rules as **DRAFT**.
2. `GET /api/v1/plausibility/source-check/healthcare` — runs ACTIVE + DRAFT rules against the real
   source (≤ 1000 rows/table) and reports violation counts/rates only. Use it to calibrate:
   a rule the source itself breaks is either wrong or describes a data-quality issue.
3. Edit a rule (set `owner`, tighten bounds) via `PATCH /api/v1/rules/{id}` — each edit is a new
   immutable version.
4. `POST /api/v1/rules/{id}/activate`. Only ACTIVE rules are enforced.

## Semantics

* **hard** rules must hold. Those marked `repair: true` fix violating generated rows (pick an
  allowed value, resample within a range/age band, move a later date after the earlier one) in at
  most 3 passes; every repair is counted per rule. Any remaining hard violation → HTTP 422 and
  **nothing is written**.
* **soft** rules report a violation rate against `tolerance` and never block.
* **unknown** — a missing/unparseable value or an absent joined parent row — is counted separately,
  never treated as a pass.
* Rules run only on their own domain's tables. Uploaded files and registered sources have no domain,
  so no rules run on them.
* The report (rule key **@ version**, counts, rates, row indexes — never values) is stored on each
  dataset as `synthetic_datasets.validation_report`.

## Findings from the starter catalogue

* The **source** has 155 insurance claims dated before their appointment. `claim_after_appointment`
  is therefore soft; the domain owner must decide whether this is pre-authorisation or bad data.
* `obstetric_codes_require_female` cannot be evaluated on this schema (diagnosis is on
  `appointments`, gender on `patients`); conditional checks are same-row only today.
* Upper bounds such as the 1,000,000 claim cap are placeholders for the domain owner to set.
