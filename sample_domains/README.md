# Sample source domains

Built-in demo source databases. The platform is domain-agnostic; each domain is just a SQLite file plus an entry in
`registry.py`. Table names must be unique across domains (checked at startup).

| Domain key | Label | File | Tables |
|---|---|---|---|
| `healthcare` | Healthcare | `hospital.db` | 4 tables (below) |
| `banking` | Banking & Financial Services | `banking.db` | 11 (below) |

Build either database explicitly (deterministic for a seed):

- Healthcare: `python -m sample_domains.healthcare hospital.db 2026`
- Banking: `python -m sample_domains.banking banking.db 2026`

If either database is missing at startup, the domain registry rebuilds it automatically. All records are fictional; do not use generated demo data as real clinical or financial records.

## Healthcare

| Table | Default rows | Purpose and relationships |
|---|---:|---|
| `patients` | 120 | Fictional patient demographics, unique `mrn`, and unique `insurance_member_id` |
| `doctors` | 20 | Fictional provider identities, department/specialization, and unique license number |
| `appointments` | 300 | Visits referencing `patients.patient_id` and `doctors.doctor_id` |
| `insurance_claims` | 300 | Claims referencing both `appointments.appointment_id` and `patients.patient_id`; `member_id` is copied from the matching patient's `insurance_member_id` |

The healthcare builder uses a fixed default seed, supports an explicit seed, enables SQLite foreign-key enforcement, and checks the generated file with `PRAGMA foreign_key_check`.

## Banking & Financial Services

```
Core banking      branches   products   customers
                      \         |          /
                       +---- accounts ----+            cards --- transactions
Lending           loans -- loan_repayments                (card_id optional)
Capital markets   securities   portfolios -- trades
```

| Table | Rows | Key columns | Sensitive columns (classified by profiling) |
|---|---|---|---|
| branches | 12 | branch_id | `ifsc_code` (IFSC_CODE) |
| products | 10 | product_id | - |
| customers | 180 | customer_id | `pan_number` (PAN), `aadhaar_number` (Aadhaar, Verhoeff-valid), `phone`, `dob`, `email`, `address` |
| accounts | 300 | account_id | `account_number` (ACCOUNT_NUMBER, 11 digits) |
| cards | 220 | card_id | `card_number` (CREDIT_CARD, Luhn-valid), `linked_account_no` (ACCOUNT_NUMBER). No CVV/PIN column, by design (PCI-DSS) |
| transactions | 900 | txn_id | - |
| loans | 60 | loan_id | - |
| loan_repayments | 480 | repayment_id | - |
| securities | 20 | security_id | `isin` |
| portfolios | 40 | portfolio_id | - |
| trades | 500 | trade_id | - |

### Relationships

**Declared** (FOREIGN KEY constraints exist): `accounts.customer_id`, `accounts.branch_id`, `accounts.product_id`,
`cards.account_id`, `transactions.account_id`, `loans.customer_id`, `loans.product_id`, `loan_repayments.loan_id`,
`portfolios.customer_id`, `trades.portfolio_id`, `trades.security_id`.

**Undeclared** (real links, no constraint - found by *Find undeclared relationships*):

| Link | Why it is undeclared | Detected by | In the shipped data |
|---|---|---|---|
| `transactions.card_id -> cards.card_id` | optional: only card-present transactions have it | same name as the key | 100% match, 0 orphans; 536 of 900 rows are NULL (non-card transactions) |
| `loans.disbursement_account_id -> accounts.account_id` | role-named column | role-prefixed key | 100% |
| `portfolios.settlement_account_id -> accounts.account_id` | role-named column | role-prefixed key | 100% |
| `loan_repayments.debit_account_id -> accounts.account_id` | role-named, and legacy data has purged accounts | role-prefixed key | **96.1%, 2 orphan accounts** |
| `cards.linked_account_no -> accounts.account_number` | denormalised copy of a natural key, not a primary key | *not auto-detected* | kept consistent by the shared-identifier check |

Semantic rules the sample data follows (and that generation preserves once the links are confirmed): a card
transaction is on the card's own account; a loan's customer owns its disbursement account; repayments are debited
from the loan's account; a portfolio's settlement account belongs to the portfolio's customer.
