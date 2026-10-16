# TDM Platform — Demo Guide

A complete walkthrough of the TDM Platform for someone seeing it for the first time:
what it is for, the sample data, every page, the use cases each page serves, what
happens behind every button, and a ready-to-run demo script.

---

## Contents

1. [What the platform does](#1-what-the-platform-does)
2. [Key ideas in plain words](#2-key-ideas-in-plain-words)
3. [The sample data](#3-the-sample-data)
4. [Starting the app for a demo](#4-starting-the-app-for-a-demo)
5. [Users, roles and the development login](#5-users-roles-and-the-development-login)
6. [The 20-minute demo script](#6-the-20-minute-demo-script)
7. [Page-by-page guide](#7-page-by-page-guide)
   - [Data Source Connector (shared by several pages)](#71-data-source-connector-shared-by-several-pages)
   - [Dashboard](#72-dashboard)
   - [Profiling](#73-profiling)
   - [Human Review](#74-human-review)
   - [Synthetic Data Generation](#75-synthetic-data-generation)
   - [Data Relationship Validation](#76-data-relationship-validation)
   - [Masking](#77-masking)
   - [Knowledge Base](#78-knowledge-base)
   - [Query Agent](#79-query-agent)
   - [Logs](#710-logs)
8. [Features without a page (server only)](#8-features-without-a-page-server-only)
9. [Use cases end to end](#9-use-cases-end-to-end)
10. [Safety rules the platform enforces](#10-safety-rules-the-platform-enforces)
11. [Known limitations to mention honestly](#11-known-limitations-to-mention-honestly)
12. [Troubleshooting](#12-troubleshooting)
13. [Glossary](#13-glossary)

---

## 1. What the platform does

Companies hold real data about real people: patients' names, birth dates and
diagnoses; customers' bank accounts, card numbers and national ID numbers.
Software teams need realistic data to **test** new systems, but using the real
thing is risky — a tester's laptop, a bug report or an outside contractor could
leak it.

**Test Data Management (TDM)** solves this. The TDM Platform:

1. **Discovers** what is inside a table or file (*Profiling*).
2. **Classifies** which columns are sensitive, with evidence and a confidence
   score (*Classification*).
3. **Asks a person** whenever it is unsure (*Human Review*).
4. **Produces safe test data**, either by
   - **masking**: disguising real rows so identities are hidden but the data still
     behaves realistically and tables still join, or
   - **synthetic generation**: inventing brand-new rows that look like the real
     ones.
5. **Checks the result** before anyone can download it: no impossible values
   (*plausibility rules*) and no leaked real data (*privacy release gate*).
6. **Records everything** — who did what, when and why (*activity and audit logs*).

Nothing in the platform modifies the source data. Sources are only ever read.

---

## 2. Key ideas in plain words

| Term | Meaning |
|---|---|
| **Source** | Where data comes from: a built-in sample database, an uploaded file, a database you connect to, or a registered source. |
| **Profiling run** | One analysis of one table. Every click of *Run Profiling* creates a new run; the newest run is the one that counts. |
| **Format verdict** | Whether a column's **format** clearly matches a specific known ID type (SSN, MRN, phone…). Says nothing about sensitivity. |
| **Sensitivity** | Whether a column holds personal data: *Sensitive*, *Unknown* (no evidence found — not proof it is safe) or *Not sensitive* (a reviewer said so). |
| **Confidence** | A rule-based evidence score (not a probability). Under 80% with some evidence → goes to Human Review. |
| **Masking** | Disguising real rows: IDs become consistent codes, names/dates/addresses are replaced, harmless columns are copied. |
| **Synthetic data** | Entirely invented rows built from each column's detected format. Never sees real values. |
| **Release gate** | The privacy check every generated or masked dataset must pass before it can be downloaded. |
| **Plausibility rule** | A domain rule such as "a patient cannot be born after their appointment", used to repair or reject generated data. |
| **Audit log** | A tamper-evident, append-only record of security-relevant actions. |

No large language model (LLM) is used for profiling, classification, masking,
generation or checks. Name/place detection uses **spaCy**, a small open-source
model that runs offline on the server. The only optional LLM use is the **Query
Agent** chat, and only if an `ANTHROPIC_API_KEY` is configured.

---

## 3. The sample data

Two built-in sample databases contain realistic **fake** data, so the platform can
be demonstrated without any real personal data. They are rebuilt automatically if
missing.

### Healthcare — `hospital.db`

| Table | Rows | Columns (highlights) | Interesting for the demo |
|---|---|---|---|
| `patients` | 120 | `patient_id`, `mrn`, `first_name`, `last_name`, `date_of_birth`, `gender` (M/F/X), `phone`, `email`, `insurance_member_id`, `address`, `city`, `state`, `postal_code`, `blood_group` | Most sensitive columns; `state` triggers Human Review (state names look like person names to the name detector). |
| `doctors` | — | names, specialization, department, email, phone, licence number | Good small table for masking. |
| `appointments` | — | `appointment_id`, `patient_id`, `doctor_id`, `appointment_date`, `department`, `diagnosis_code` (ICD-10, e.g. `E11.9`), `diagnosis_desc`, `notes`, `status` | Links patients and doctors; diagnosis columns show a current detection gap (see §11). |
| `insurance_claims` | — | `claim_id`, `appointment_id`, `patient_id`, `member_id`, `claim_date`, `claim_amount`, `claim_status`, `diagnosis_code` | 155 claims are dated **before** their appointment in the source itself — a real data-quality finding. |

### Banking & Financial Services — `banking.db`

11 tables: `customers` (names, DOB, PAN, Aadhaar, phone, email, address),
`accounts`, `cards`, `transactions` (free-text `description` triggers Human
Review), `branches`, `products`, `loans`, `loan_repayments`, `portfolios`,
`securities`, `trades`.

Table names are unique across both databases, so a table name always identifies
its domain.

---

## 4. Starting the app for a demo

You need two programs running: the **backend** (the server that does the work,
port 8000) and the **frontend** (the website, port 5500).

### Backend

From the `TDM Platform` folder, in PowerShell:

```powershell
$env:TDM_AUTH_MODE = "development"
$env:TDM_DATA_DIR  = "D:\Homework\tdm-devdata"
D:\Homework\tdm-venv\Scripts\python.exe -m alembic upgrade head
D:\Homework\tdm-venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

- `TDM_AUTH_MODE=development` — no login; you act as a built-in admin/steward.
  **Never use this on a shared or public machine.**
- `TDM_DATA_DIR` — where the platform keeps its own database, uploads and
  generated files. Everything you do in a demo persists here across restarts.
- `alembic upgrade head` — creates or updates the platform's database structure.

### Frontend

From `TDM Platform\frontend-react`:

```powershell
npm run dev
```

Open **http://localhost:5500**. The badge at the top right of the Dashboard
should say **Live**. The server's interactive API documentation is at
**http://localhost:8000/docs**.

### Starting from a clean slate

To demo from zero, stop the backend and point `TDM_DATA_DIR` at a new, empty
folder (or delete the old one). The sample databases are recreated automatically.

### Development-mode differences to be aware of

| Behaviour | In development mode |
|---|---|
| Login | None — every request is the user `developer` with roles admin + steward. |
| Masking key | Temporary; masked codes change every time the server restarts. |
| File encryption | Generated/uploaded files are written unencrypted (with a warning). |
| Startup checks | Production refuses to start without secrets; development only warns. |

---

## 5. Users, roles and the development login

The platform has four roles. The server enforces them on every request.

| Role | Can |
|---|---|
| **admin** | Everything, including deleting relationships and overriding a blocked dataset. |
| **steward** | Read real data: run profiling, mask, connect sources, import rules. |
| **reviewer** | Decide Human Review items; read results, logs and reports. |
| **tester** | Generate synthetic data and download released datasets. Cannot read real data or decide reviews. |

In development mode the website sends `X-Dev-User: developer` and
`X-Dev-Roles: admin,steward` on every request, so all pages work. In production
these headers are ignored and a signed login token (JWT) is required.

---

## 6. The 20-minute demo script

A suggested order that tells the whole story. Each step links to the detailed
page section.

| # | Page | Do this | Point out |
|---|---|---|---|
| 1 | Dashboard | Open the site. | *Live* badge, empty counters, "No activity yet". |
| 2 | Profiling | Table `patients`, sample size `200`, **Run Profiling**. | Column table: format verdict vs **Sensitivity / Confidence / Why / Review**; `state` is *Waiting for review*. |
| 3 | Profiling | Switch to `appointments`, run it. | Mostly *Unknown*; only `patient_id` is sensitive; nothing goes to review — and why. |
| 4 | Human Review | Open the `patients.state` card. | Evidence "Text mentions a person's name", 65% confidence. |
| 5 | Human Review | Choose **Not sensitive**, reason "State names, not people", **Approve**. | Hint text says what masking will do; decision is recorded with name and time. |
| 6 | Masking | Table `patients`, 10 rows, **Generate Masked Preview**. | Per-column actions: IDs → codes, names → replaced, `state` copied because a reviewer approved it. Joins stay intact. |
| 7 | Synthetic Data | Table `patients`, 20 rows, **Generate & Preview**. | Invented rows; gender column contains random words — realism limitation. |
| 8 | *(server)* | Activate the gender and blood-group plausibility rules (§8.1). Generate again. | Gender is now M/F/X — rules repaired the data before saving. |
| 9 | Data Relationship Validation | Domain *Healthcare*, tick `appointments`, **Generate & validate**. | `patients` and `doctors` auto-added; 100% integrity score; no orphans. |
| 10 | Knowledge Base | Table `patients`. | *Dictionary default* vs *Detected sensitivity* — `patient_id` disagrees, and masking trusts the detected one. |
| 11 | Query Agent | Ask "Which columns in patients are sensitive?" | Without an API key it shows the authorized metadata it would use; it can never read raw rows. |
| 12 | Logs | Scroll through. | Every step you just did is in the activity log; review decisions are in the audit log. |

---

## 7. Page-by-page guide

### 7.1 Data Source Connector (shared by several pages)

Appears at the top of **Profiling** and **Synthetic Data Generation** (Masking and
Knowledge Base use the same table selection). It answers "where does the data
come from?". Three connector types:

#### 🗄️ Database

- **SQLite (Demo)** — always connected. The table dropdown lists all 15 sample
  tables from both domains.
- **Oracle / MSSQL / PostgreSQL / MySQL** — a form for host, port, database (or
  service name), username, password and schema. **Connect** tests the connection
  and lists its tables; they then appear in table dropdowns prefixed with the
  database type (e.g. `postgresql.customers`). **Disconnect** forgets it.
  - The connection lives only in the server's memory for your session; the
    password is never saved.
  - If the server lacks the driver, the form says which package to install.
  - Hosts can be restricted with `TDM_ALLOWED_DB_HOSTS`.

#### 📄 Flat File

Upload a **.csv**, **.xml** or **.txt** file (max ~5 MB) by picking or dropping it.
Behind the scenes (the *landing zone*):

1. Extension and size are checked.
2. Content must be plain text — binary or disguised files are rejected.
3. The file is parsed in memory; if it cannot be parsed nothing is stored.
4. It is saved under a random name (never your filename) and encrypted when keys
   are configured.
5. It appears in table dropdowns under its (cleaned) file name.
6. Uploading a file with the same name replaces the earlier one.
7. Uploaded files are deleted automatically after 30 days (their analysis
   history is kept).

#### 🔗 Registered Source

Pick a source that an administrator registered through the server
(`/api/v1/sources`). Registered sources store connection details and a
**reference** to credentials (`env://…` or `vault://…`) — never the password
itself. Choose the source, then one of its tables. Profiling, masking and
generation then read from that source.

---

### 7.2 Dashboard

**Purpose:** a live overview of what the platform has done.

**What you see**

- **Live / Connecting badge** — whether the website can reach the server, and
  when the numbers were last refreshed (they refresh automatically).
- **Recent activity card** — the latest action (e.g. *Synthetic Data Generation*),
  who did it, on which source, its status and how long ago.
- **Fields classified** — total columns analysed, summed over **all** profiling runs
  (profiling the same table twice counts its columns twice).
- **High confidence** — columns whose **format verdict** was *High confidence*.
- **Needs review** — columns whose **format verdict** was *Needs review*.
  ⚠️ This is the format verdict count, **not** the number of items in the Human
  Review tab.
- **Recent activity table** — the last three actions with user, source, field
  count, status and time. With no activity, a **Run Profiling** button takes you
  to the Profiling page.

**Use cases**

- Check the platform is up before a demo.
- See at a glance what the team has been doing.

---

### 7.3 Profiling

**Purpose:** analyse a table or file to learn what each column contains and which
columns are sensitive. **Every other feature depends on profiling** — masking,
synthetic generation and the Knowledge Base all use the latest profiling run.

**How to use**

1. Choose the source in the Data Source Connector (§7.1).
2. Enter a **sample size** (1–1000 rows; default 50).
3. Click **Run Profiling**.

**What happens when you click Run Profiling**

1. **Permission check** — only admins and stewards may profile (it reads real
   data). The action is written to the activity log as "started".
2. **Reading rows (read-only)** — the platform counts the table's rows and picks a
   sample:
   - table of up to 10,000 rows → a random but repeatable sample (fixed seed, so
     the same click gives the same sample);
   - bigger table → the first N rows, so huge tables are never fully scanned.
3. **Recording the structure** — column names and native types go into the
   Schema Catalog (Knowledge Base).
4. **Four analyses per column**:
   - *Pattern analyser* — the most common value format and the percentage of
     values that match it.
   - *Format verdict* — *High confidence* if the format is a specific known ID
     type with ≥ 90% match, otherwise *Needs review*.
   - *Profiler* — percentage of blanks and number of distinct values.
   - *Sensitivity classifier* — sensitive / unknown with a confidence and
     evidence (details below).
5. **Aggregate statistics** — ranges, spread, value shapes; details are hidden
   for sensitive columns.
6. **Saving everything in one step** — the run, every column's results,
   statistics, sensitivity, and a **Human Review item** for each uncertain
   column. If anything fails, nothing is saved.
7. The activity log entry becomes "N rows sampled, M fields classified".

**The Column details table**

| Column | Meaning |
|---|---|
| Column | Column name. |
| Pattern Type | Detected format, e.g. `MRN`, `DATE`, `PHONE`, `TEXT`, `NUMERIC`. |
| Pattern | Shape of values: digits → `D`, letters → `A`, e.g. `AAADDDDDD` for `MRN000042`. |
| Match % | Share of sampled values matching that format. |
| Null % | Share of blank values. |
| Distinct | Number of different values in the sample. |
| Format verdict | *High confidence* / *Needs review* — format only (see legend on the page). |
| Sensitivity | *Sensitive* (red), *Unknown* (grey) or *Not sensitive* (green). |
| Confidence | Evidence score, e.g. 95%. A dash means no evidence. |
| Why | Plain-English evidence, e.g. "Column name suggests MRN", "Values look like EMAIL", "Text mentions a person's name". |
| Review | *Decided automatically*, *Not needed*, *Waiting for review #N*, or *Approved / Rejected by …*. |

**How sensitivity is decided** — five kinds of clue, each with a fixed score; the
column keeps its highest score:

| Clue | Example | Score |
|---|---|---|
| Column name | `ssn`, `date_of_birth`, `card_number`, `aadhaar` | 0.98 |
| | `email`, `mrn`, `patient_id`, `account_number`, `pan` | 0.95 |
| | `phone`, `first_name`, `last_name`, `address`, `insurance_id` | 0.90 |
| Value format from profiling | SSN-shaped values × share matching | up to 0.95 |
| Value patterns with checks | emails 0.90, SSNs 0.85, phones 0.75, card numbers passing the **Luhn** check-digit test 0.65, US doctor IDs (NPI) with a valid check digit 0.65 | × share matching |
| Approved word lists | values found in a configured list | 0.75 |
| Name/place detection (spaCy, offline) | free text mentioning a person or a place | 0.65 |

| Highest score | Result |
|---|---|
| No evidence | **Unknown** — no review |
| Under 0.80 | **Sensitive, needs Human Review** |
| 0.80 or more | **Sensitive**, decided automatically |

**Use cases**

- First look at an unfamiliar table or file.
- Finding out which columns must be protected before sharing data.
- Feeding the masking and synthetic-data features.

**Demo tips**

- `patients` shows the full range: auto-sensitive columns, *Unknown* columns
  and `state` waiting for review.
- `appointments` shows that *Needs review* in the format verdict does **not**
  create review items.
- Profiling the same table again creates a new run and new review items; older
  runs stay in history but no longer count.

---

### 7.4 Human Review

**Purpose:** let a person confirm or correct the platform's uncertain
sensitivity guesses, and stop test data being produced until they have.

**When items appear:** only after profiling, and only for columns where the
classifier found **some** evidence but scored **under 80%**. Confidently
sensitive and evidence-free (*Unknown*) columns never appear here.

**What a card shows**

- `table.column`, review number, profiling run number and source.
- **Proposed pattern**, **sensitivity**, **confidence** and **created** time.
- **Evidence** codes (e.g. `free_text_contains_person_entity`).
- For pending items: an optional **pattern correction**, the **Final
  sensitivity** dropdown with a hint about its effect, and a required **Decision
  reason**.
- For decided items: who decided, the final sensitivity, the reason and when.

**The three sensitivity choices**

| Choice | Masking will… |
|---|---|
| **Sensitive** | disguise the column. |
| **Unknown — requires caution** | still disguise the column, to be safe. |
| **Not sensitive** | copy the column unchanged. This is the only way to mark a column harmless. |

**Approve vs Reject**

| Button | Means | Effect |
|---|---|---|
| **Approve** | "Use this classification (with my corrections)." | Saves the final values, marks the column approved, unlocks generation/masking once nothing else in that run is pending. |
| **Reject** | "The evidence can't be trusted." | Marks it rejected; the table **stays locked** until it is profiled again and the new item is decided. |

**Which to use**

| Situation | Action |
|---|---|
| Correctly flagged as sensitive | Approve, keep *Sensitive*. |
| Flagged but harmless (e.g. state names) | Approve, choose *Not sensitive*. |
| Sensitive but wrong type | Approve with a corrected pattern type. |
| Not sure, or data looks broken | Reject, fix the cause, profile again. |

**Behind the scenes**

- A reason is mandatory; empty reasons are refused.
- Every decision goes to the tamper-evident **audit log**.
- An item can be decided only once; two reviewers clicking at the same time
  cannot both succeed.
- **Generation lock:** while any review-required column of the table's latest
  run is not approved, *Synthetic Data Generation* and *Masking* for that table
  are refused with "Human review is required before…".
- Testers cannot decide reviews.

**The status filter** shows *Pending*, *Approved*, *Rejected* or *All* items.

**Use cases**

- Data stewards confirming what is personal data before a dataset is shared.
- An auditable trail of who decided what about sensitive data and why.

**Good to know**

- Decisions apply to one column of one profiling run. They do not carry over to
  other tables, other files, or re-profiles of the same table.

---

### 7.5 Synthetic Data Generation

**Purpose:** create entirely invented rows that look like the source table, for
testing without any real values.

**How to use**

1. Choose the source table (it must have been profiled — a green banner confirms
   it, an amber one warns you if not).
2. Enter the number of rows (up to 1000).
3. Click **Generate & Preview**. The first 10 rows are shown, and a **Download
   CSV** link appears.

**How rows are made (no AI)** — with the **Faker** library, each cell
independently, using the first rule that applies:

1. **Detected format** — SSN, phone, MRN (`MRN` + 6 digits), card number,
   PAN/Aadhaar shapes, dates (birth dates for "dob/birth" columns).
2. **Column name** — `email`, names (company names for e.g. `bank_name`),
   `address`, `city`, `state`, `…_id` (unique numbers), `age`.
3. **Generic format** — plain text gets a random word, numbers 1–9999.
4. **Native type** as a last resort.

The generator only uses each column's **format**, never its real values, so no
real value can leak into synthetic data.

**After generating, before saving**

1. **Human Review lock** — refused if the table's latest run has undecided review
   items.
2. **Plausibility rules** — active rules repair impossible values (e.g. random
   gender words → M/F/X). If a hard rule still fails, nothing is saved and the
   page shows why.
3. **Privacy release gate** — checks for leaked real identifiers, copied rows and
   rare combinations. A failed check marks the dataset **BLOCKED**: the preview is
   withheld, the page explains why, and downloads are refused until an admin
   overrides it.
4. The CSV is written (encrypted when keys are configured) and recorded as a
   dataset with its validation report.

**Use cases**

- Filling a test environment with realistic-looking records.
- Load and performance testing with as many rows as needed.
- Sharing data with vendors where even disguised real data is not allowed.

**Limitations to mention:** columns are generated independently and don't follow
the real distributions (see §11).

---

### 7.6 Data Relationship Validation

**Purpose:** generate **several related tables together** so every link between
them stays valid — no appointment pointing at a patient who doesn't exist.

**Sections of the page**

1. **Source domain** — choose *Healthcare* or *Banking*.
2. **Relationship graph**
   - Relationships come from two places: **declared** foreign keys in the
     database, and **undeclared** logical links you confirm.
   - **Refresh / discover** re-reads the database structure.
   - **Generation order (parents first)** shows the order tables are created.
   - The relationships table lists child column → parent column, type
     (declared/undeclared) and whether the link may be empty.
   - **Find undeclared relationships** suggests links nobody declared (e.g. a
     column named like another table's key whose values nearly all exist in that
     table). It computes counts only — no row values are read. **Accept** turns a
     suggestion into a confirmed link.
   - The raw metadata graph is shown for technical users.
3. **Generate related tables**
   - Tick the tables you need. Their parent tables are added automatically
     (marked "added: parent of a selected table").
   - Set rows per table (defaults follow the source size, max 1000).
   - **Every parent gets at least one child** — optional coverage guarantee.
   - **Seed (optional)** — the same seed reproduces the same data.
   - **Generate & validate**.
4. **Validation report**
   - **Integrity score** — valid references ÷ all references × 100.
   - **Checks** — keys unique and filled, no orphans, required links filled,
     parent/child counts consistent, multi-level joins resolve, sibling links
     agree (e.g. a claim's patient equals its appointment's patient), copied
     identifiers match, distribution of children per parent compared with the
     source.
   - **Relationships** — child/parent rows, valid references, orphans, children
     per parent (min / avg / max).
   - **Generated tables** — rows and a **Download CSV** link per table, plus a
     preview. Files are published **only if validation passes**.

**Behind the scenes:** the same Human Review lock, plausibility rules and privacy
gate as single-table generation apply to the whole set.

**Use cases**

- Building a complete, consistent test database (patients + doctors +
  appointments + claims).
- Proving to QA that the generated data has no broken links.

---

### 7.7 Masking

**Purpose:** produce a disguised copy of **real** rows — realistic because it
starts from real data, but with identities removed — and keep relationships
working across tables.

**Sections of the page**

1. **Table selection** (shared source selection).
2. **Masking Recommendations** — per column: pattern type, *Dictionary default*
   (generic label for the format), *Detected sensitivity* (the real
   classification) and a recommended technique. The actual masking run follows
   **Detected sensitivity**.
3. **Masked sample preview** — enter a row count, click **Generate Masked
   Preview**. You get:
   - a **per-column action table** (*Column / Action / Why*),
   - a note about which key was used (development mode uses a temporary key),
   - the masked rows, saved as a CSV dataset.

**What happens to each column**

| Action | Applies to | Example |
|---|---|---|
| **tokenize (join key)** | `id`, `…_id` and relationship keys | `patient_id 42` → `pz_k1_x7f…`; the same patient gets the same code in every table, so joins still work |
| **tokenize (identifier)** | direct identifiers: SSN, MRN, email, phone, account/card numbers, PAN, Aadhaar | `MRN000042` → `pz_k1_q2d…` |
| **substitute** | other sensitive data: names, addresses, birth dates, free text with names; and columns a reviewer marked *Unknown* | `Arjun` → `Nicole Lester` |
| **passthrough** | columns with no sensitivity evidence, or marked *Not sensitive* by a reviewer | `gender`, `blood_group` copied |

Codes come from **HMAC-SHA-256** with a secret key: the same value always gives the
same code, but without the key nobody can work out the original or test guesses.
Different identifier types get different codes even for equal values.

**Checks before release**

- Human Review lock for the table.
- **Privacy gate for masked data** — tokenized columns must never equal the
  row's original value; substituted values may coincide by chance at most 2%;
  quasi-identifier combinations unique in the source are limited.

**Use cases**

- Realistic test data for systems that must behave like production.
- Sharing data across teams while keeping cross-table joins.

**Demo tip:** mask `patients`, then `appointments` — the masked `patient_id`
codes in both files match.

---

### 7.8 Knowledge Base

**Purpose:** the platform's catalogue of what it knows about tables and data
types — the "metadata layer" other features reuse.

**Sections**

1. **Schema Catalog & Data Dictionary** (for the selected table):

   | Column | Meaning |
   |---|---|
   | Column / Native Type | name and database type (e.g. `INTEGER`, `TEXT`) |
   | Pattern Type | detected format from the latest profiling run |
   | Business Name | plain-English meaning of the format, e.g. "Medical Record Number" |
   | Dictionary default | generic sensitivity label for that **format** (e.g. "PHI - High") |
   | Detected sensitivity | what profiling and review concluded for **this** column |
   | Review | review state of that column |
   | Format verdict | as on the Profiling page |

2. **Data Dictionary — Business Glossary**: every known pattern type with its
   business name, description and default sensitivity label.

**Why two sensitivity columns?** The dictionary label is based on format only.
The detected sensitivity also uses column names, value checks, name detection
and human decisions. Example: `patient_id` is a plain number, so its dictionary
default is "Non-sensitive (context-dependent)", but its name reveals it is a
patient identifier, so its detected sensitivity is **Sensitive**. Masking and the
privacy checks use the detected sensitivity.

**Use cases**

- Documentation of data assets for governance.
- Explaining to business users what each column means.

---

### 7.9 Query Agent

**Purpose:** ask questions in plain English about what the platform has found,
e.g. "Which columns in patients are sensitive?" or "What is waiting for review?"

**How it works**

- **With an `ANTHROPIC_API_KEY`** configured on the server: Claude answers, using
  only a fixed set of read-only tools:

  | Tool | Who | Returns |
  |---|---|---|
  | list profiled tables | reviewer+ | tables and their latest runs |
  | run summary | reviewer+ | per-column format, verdict, blanks, distinct, sensitivity |
  | column metrics | reviewer+ | aggregate statistics (no category values) |
  | review queue | reviewer+ | review items and their evidence |
  | release status | steward+ | dataset release status and failed privacy checks |

- **Without a key** (the default demo setup): it shows the authorized metadata it
  would have used — tables and the latest run summary — instead of an English
  answer.

**Security controls**

- It can never read raw rows, run database queries, change anything or approve
  anything.
- It is offered only the tools your role allows, and every call is re-checked by
  the server — tricking the model cannot widen its access.
- Limits: 2000-character questions, 6 steps, 60 seconds, 10 questions per minute
  per user.
- Every question and tool call is logged (without the question text).

**Use cases:** quick answers for managers and reviewers without learning the UI.

---

### 7.10 Logs

**Purpose:** see everything the platform has done, and manage how long logs are
kept.

**Sections**

1. **Log retention** — activity log entries older than the retention period
   (default **5 days**) are deleted automatically; shows how many entries are
   stored, the oldest one and the last cleanup. **Clean up now** runs it immediately.
2. **Activity log** — every operational action (profiling, uploads, generation,
   masking, relationship discovery, cleanups) with time, user, source, type,
   status, details and output file. Filter by activity and user; **Refresh**.
3. **Audit log** — security-relevant events: review decisions, rule changes,
   downloads, blocked downloads, privacy overrides, agent tool calls, retention
   purges. It is **append-only and hash-chained**: entries cannot be edited or
   deleted, and tampering is detectable. It is never purged.
4. **File locations** — where the server reads and writes files (uploads,
   generated output), with counts and sizes.
5. **File output generation** — every generated or masked file with source, who
   generated it, user and row count.

**Use cases:** auditing, troubleshooting a failed run, proving who released which
dataset.

---

## 8. Features without a page (server only)

These work today through the server API (try them at
**http://localhost:8000/docs**). Screens for them would be a natural next step.

### 8.1 Plausibility rules (healthcare)

Rules that stop impossible synthetic data. Nine starter rules ship as **drafts**;
a domain expert should review and activate them.

| Rule | Type | Effect |
|---|---|---|
| Patient age 0–120 | hard, repairs | resamples impossible birth dates |
| Gender is M/F/X | hard, repairs | replaces random words |
| Blood group is one of the 8 ABO/Rh groups | hard, repairs | replaces invalid values |
| Appointment status valid | hard, repairs | SCHEDULED / COMPLETED / CANCELLED |
| Appointment not before birth | hard | cross-table date check |
| Diagnosis codes ICD-10 shaped | hard | cannot repair → rejects the dataset |
| Claim amount 1–1,000,000 | hard, repairs | resamples |
| Claim within a year after its appointment | soft (5% tolerance) | warning only — the source itself breaks it |
| Obstetric codes for female patients | soft | example of a conditional rule |

To activate in a demo:

1. `POST /api/v1/plausibility/catalogue/healthcare/import` — creates the drafts.
2. `GET /api/v1/rules?rule_type=PLAUSIBILITY` — find the rule ids.
3. `POST /api/v1/rules/{id}/activate` — enforce a rule.
4. `GET /api/v1/plausibility/source-check/healthcare` — see how the real data
   scores against each rule (counts only).

### 8.2 Privacy override

When the privacy gate blocks a dataset:

- `GET /api/v1/datasets/{id}/validation` — full plausibility + privacy evidence.
- `POST /api/v1/datasets/{id}/release-override` with a reason of at least 10
  characters — **admin only**; recorded on the dataset and in the audit log.
- `GET /api/v1/datasets` — all datasets with their release status.

### 8.3 Other server features

- **Source registry** (`/api/v1/sources`) — register databases with credential
  references (`env://` or `vault://`); plaintext passwords are refused.
- **Rule registry** (`/api/v1/rules`) — versioned rules with draft/active states;
  every edit creates a new version.
- **Jobs and workflows** (`/api/v1/jobs`, `/api/v1/workflows`) — tracked
  long-running work and enforced step-by-step processes.
- **Profiling statistics** (`/api/v1/results/{run_id}/metrics`) and
  **relationship health** (`/api/v1/relationships/health`).
- **Privacy release policy** — per-domain thresholds via a registry rule
  `privacy.release_policy.<domain>`.

---

## 9. Use cases end to end

### A. "Give QA a safe copy of the patient tables"

1. Profiling → `patients`, `appointments`, `doctors`.
2. Human Review → decide every pending item.
3. Masking → mask each table. Codes match across tables, so joins work.
4. Download the CSVs (released only if the privacy gate passes).

### B. "We need 1,000 realistic fake patients with appointments"

1. Profiling → `patients`, `doctors`, `appointments`.
2. Human Review → decide pending items.
3. *(Optional)* activate plausibility rules (§8.1).
4. Data Relationship Validation → tick `appointments`, 1000 patients, **Generate &
   validate** → download when the integrity score passes.

### C. "What personal data is in this CSV a partner sent us?"

1. Profiling → Flat File → upload the CSV → Run Profiling.
2. Read the Sensitivity / Why columns; decide review items.
3. Knowledge Base for business names; Logs for the record.

### D. "Prove who approved releasing this dataset"

Logs → Audit log: review decisions, downloads, blocked downloads and overrides,
each with user and time. Dataset evidence via `GET /api/v1/datasets/{id}/validation`.

---

## 10. Safety rules the platform enforces

| Rule | Where |
|---|---|
| Sources are read-only | all connectors |
| Only stewards/admins read real data | profiling, masking, connectors |
| Undecided reviews block generation and masking | generation, masking |
| Impossible data repaired or rejected | plausibility rules |
| Leaky datasets cannot be downloaded without an audited admin override | privacy gate |
| Passwords are never stored; sources hold only references | source registry |
| Files encrypted at rest (when keys are set) | uploads, generated and masked files |
| Old files deleted automatically (30 days) | retention |
| Every important action is logged; audit log cannot be altered | logs |
| AI assistant limited to read-only, role-checked tools | Query Agent |
| Production refuses to start without its secrets | startup checks |

---

## 11. Known limitations to mention honestly

1. **Synthetic realism** — columns are generated independently with generic
   rules: plain text gets random words (gender becomes "Perform"), name columns
   get full names, real distributions and links between columns (age vs
   diagnosis) are not reproduced. Plausibility rules fix some of this.
2. **Health data detection gap** — diagnosis codes and descriptions are not
   recognised as sensitive (they come out *Unknown*), so they are neither
   reviewed nor masked. A rule for diagnosis/condition/medication columns and
   ICD-10-shaped values would close this.
3. **Dashboard "Needs review" counter** counts format verdicts, not Human Review
   items.
4. **Review decisions don't carry over** between runs or datasets; reviewers may
   repeat the same decision.
5. **Name detection makes mistakes** — place names can look like person names;
   that is why uncertain results go to a human.
6. **Plausibility rules and privacy overrides have no screens yet** (server
   only).
7. **Query Agent needs an API key** for English answers.
8. **SQLite** is fine for one user; multi-user production should move to
   PostgreSQL.
9. **Development mode** uses a temporary masking key (codes change on restart)
   and writes files unencrypted.

---

## 12. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Dashboard stuck on **Connecting…** | Backend not running, or the website's address isn't allowed (`TDM_ALLOWED_ORIGINS`). Start the backend; check http://localhost:8000/health. |
| "Human review is required before generating data…" | The table's latest profiling run has pending or rejected review items. Decide them, or re-profile after a rejection. |
| "has not been profiled yet" | Run Profiling on that table first. |
| Synthetic preview is empty and says **BLOCKED** | The privacy gate failed. Check `GET /api/v1/datasets/{id}/validation`; an admin can override with a reason. |
| Download returns **410 Gone** | The dataset passed its 30-day retention and its file was deleted. Generate it again. |
| Masked codes differ from yesterday | Development mode uses a temporary key that changes on restart. Set `TDM_PSEUDONYM_KEYS` for stable codes. |
| Query Agent replies with raw data | No `ANTHROPIC_API_KEY` configured — expected in the demo setup. |
| Upload rejected "not plain text" | The file contains binary/control characters; export it as plain CSV/XML/TXT. |
| Server refuses to start: "unsafe configuration" | Production mode without secrets. For a local demo set `TDM_AUTH_MODE=development`; for production see `docs/DATA_LIFECYCLE.md`. |

---

## 13. Glossary

| Term | Meaning |
|---|---|
| **Aadhaar / PAN** | Indian national identity number / tax ID number. |
| **Audit log** | Append-only, hash-chained record of security-relevant actions. |
| **Domain** | A family of related tables: healthcare or banking. |
| **Faker** | Open-source library that produces realistic fake values. |
| **Foreign key** | A column pointing at another table's row (e.g. `appointments.patient_id`). |
| **HMAC** | Keyed one-way code: same input + key → same code; irreversible without the key. |
| **ICD-10** | International diagnosis code system, e.g. `E11.9` (type 2 diabetes). |
| **Luhn check** | Check-digit formula used to validate card numbers. |
| **MRN** | Medical Record Number — a hospital's patient ID. |
| **NER / spaCy** | Named-entity recognition — finding names of people and places in text; spaCy is the offline library used. |
| **Orphan** | A child row pointing at a parent that doesn't exist. |
| **PHI / PII** | Protected Health Information / Personally Identifiable Information. |
| **Quasi-identifier** | An attribute that identifies people in combination (birth date + postcode + gender). |
| **Release gate** | Privacy check required before a dataset can be downloaded. |
| **Seed** | A number that makes random choices repeatable. |
| **Tokenize** | Replace a value with a consistent code. |
