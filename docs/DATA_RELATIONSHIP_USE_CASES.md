# Data relationships in Test Data Management: declared vs undeclared

A **relationship** says "this column in a child table points at that key in a parent table". Test data is only
useful if those links still work after it is generated, masked or subset. The platform distinguishes two kinds:

| | **Declared** | **Undeclared** (logical / implicit) |
|---|---|---|
| Definition | A FOREIGN KEY constraint exists in the source database | The link is real, but no constraint was ever created |
| Where it comes from | Read from the schema by *Re-discover from source* (no row values) | Suggested by *Find undeclared relationships*, then **confirmed by a steward** |
| Trust | Enforced by the database | Only as good as the evidence: name convention + values found in the parent |
| Stored as | `origin = "discovered"` (replaced on every re-discovery) | `origin = "manual"` (kept across re-discovery; only an admin can delete) |
| Used when generating | Yes | Yes - identically, once confirmed |

Banking and financial-services estates are full of undeclared links: constraints are dropped for bulk-load speed,
cores were migrated from mainframes, warehouses never had them, and many columns are deliberately optional.
The sample `banking` domain contains both kinds on purpose (see `sample_domains/README.md`).

---

## Declared relationships - use cases

| # | Use case | Banking example | What the platform does |
|---|---|---|---|
| D1 | **Parent-first generation.** Never create a child before its parent exists | customers -> accounts -> transactions | Topological order; a cycle is rejected with the tables named |
| D2 | **Orphan-free data.** Every FK value exists in the parent | `accounts.customer_id` always matches a customer | Keys come from an identifier registry, so an orphan cannot be produced; validated before publish |
| D3 | **Pull in what is needed.** Ask for one table, get a working set | Selecting `trades` also generates portfolios, securities, customers | Parent tables are added automatically and flagged "auto-included" |
| D4 | **Multi-level joins.** A child still joins all the way up | transaction -> account -> customer, loan_repayment -> loan -> customer | `multi_level_joins` check on every row |
| D5 | **One entity, one answer.** Two paths to the same parent must agree | A card transaction's account equals the card's account | Sibling-FK derivation + `path_consistency` check |
| D6 | **Publish gate.** Bad data never reaches testers | Any orphan, empty required FK or duplicate key blocks the whole run | Nothing is written unless the integrity score is 100% and every hard check passes |
| D7 | **Schema drift.** The database changed | A new FK was added to `loans` | *Re-discover from source* replaces declared rows, keeps confirmed undeclared ones |
| D8 | **Realistic shape.** Fan-out like production | ~8 repayments per loan | Informational `distribution` check against the source's children-per-parent |

## Undeclared relationships - use cases

| # | Use case | Banking example | How it is found | TDM treatment | Support |
|---|---|---|---|---|---|
| U1 | **Constraint-free legacy core / warehouse.** Every link is undeclared | A mainframe-migrated ledger loaded without FKs | Name conventions + values exist in parent (>= 95%) | Steward accepts the real ones; generation then behaves as in D1-D6 | Supported |
| U2 | **Role-named keys.** The column name says the role, not the table | `settlement_account_id`, `debit_account_id`, `disbursement_account_id` -> `accounts.account_id` | `<role>_<parent key>` convention | Same as a declared FK | Supported |
| U3 | **Optional references.** Only some rows have the link | `transactions.card_id` is empty for UPI/NEFT/branch transactions | Same-name key; NULLs are ignored when matching | NULL share is kept; the account is still filled, and a card transaction uses the card's own account | Supported |
| U4 | **Dirty legacy references.** Some values point at rows that no longer exist | `loan_repayments.debit_account_id`: 96.1%, 2 purged accounts | Match % and orphan count are shown beside each suggestion | The steward decides; **synthetic data is orphan-free** even though the source is not - tell testers it is cleaner than production | Supported |
| U5 | **Cross-path consistency that only exists logically.** | A loan's customer must own its disbursement account | Derived once both links are known | `path_consistency` enforces it | Supported |
| U6 | **Denormalised natural-key copies.** The same business value stored twice | `cards.linked_account_no` = `accounts.account_number` | Not suggested (target is not a primary key) | The shared-identifier check copies the parent's value and validates it | Partial - consistent, but not a graph edge |
| U7 | Composite keys | (branch_code, account_no) | - | Reported as skipped | **Not yet** |
| U8 | Links across databases / systems | Core banking <-> card switch <-> trading platform | - | One source database per domain today | **Not yet** |
| U9 | Polymorphic links | `entity_type` + `entity_id` | - | - | **Not yet** |
| U10 | Uploaded CSV/XML/TXT files | - | Files carry no keys | - | **Not yet** |

**Why U2-U5 matter - measured.** On the banking sample, generating 80 rows per table with only the declared FKs
produced card transactions whose `card_id` pointed at a card on a *different* account in **80 of 80** cases, and loans
whose customer did not own the disbursement account in **80 of 80**. After confirming the four undeclared links, both
were **0** (0 of 34 card transactions, 0 of 80 loans) and the validation report passed at 100%.

## Governance workflow for undeclared relationships

1. **Discover** - *Re-discover from source* loads the declared FKs (steward or admin).
2. **Suggest** - *Find undeclared relationships* lists candidates with match % and orphan count (steward or admin). Nothing is saved.
3. **Confirm** - *Accept* stores it as an undeclared relationship (steward or admin). A cycle is rejected.
4. **Generate** - the confirmed link is used exactly like a declared one (tester and above).
5. **Validate** - the report scores every relationship; only a 100% run is published.
6. **Retire** - only an admin can delete an undeclared relationship; declared ones cannot be deleted (they come from the schema).

Suggestion rules (all must hold): the column name follows a key convention (same name as a single-column primary key,
`<table>_id`, or `<role>_<key>`); the SQL types are compatible; at least 95% of the column's distinct values exist in
the parent. Only distinct-value *counts* are computed in the database - no row values are read.
Self-references are never suggested, and the generic key name `id` is never matched by the role-prefix rule (it would match every `..._id` column).

## Choosing between them

- The database declares it -> **declared**; nothing to do.
- It is real but undeclared and the name follows a convention -> **accept the suggestion**, after checking the orphan count.
- It is real but the name gives no clue (or the target is a non-key column) -> not auto-detected. The API has
  `POST /relationships` (the columns must exist and a cycle is rejected), but there is no manual-entry form in the UI,
  and links to non-key columns have not been tested.
- It is a coincidence (two unrelated `status_id` columns) -> **do not accept**; the evidence is only a name and overlapping values.
