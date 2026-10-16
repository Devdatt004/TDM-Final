"""
sample_domains/banking.py

Core schema + deterministic sample data for the BANKING & FINANCIAL SERVICES
domain. Stdlib only (sqlite3 / random) so it can be built and tested without
FastAPI, SQLAlchemy or Faker.

Eleven tables in three areas:

  Core banking     branches, products, customers, accounts, cards, transactions
  Lending          loans, loan_repayments
  Capital markets  securities, portfolios, trades

Relationships are split on purpose, because real banking estates look like this:

  DECLARED   (a FOREIGN KEY constraint exists in the database)
      accounts.customer_id      -> customers.customer_id
      accounts.branch_id        -> branches.branch_id
      accounts.product_id       -> products.product_id
      cards.account_id          -> accounts.account_id
      transactions.account_id   -> accounts.account_id
      loans.customer_id         -> customers.customer_id
      loans.product_id          -> products.product_id
      loan_repayments.loan_id   -> loans.loan_id
      portfolios.customer_id    -> customers.customer_id
      trades.portfolio_id       -> portfolios.portfolio_id
      trades.security_id        -> securities.security_id

  UNDECLARED (the link is real, but no constraint was ever created)
      transactions.card_id               -> cards.card_id         (optional: card-present only)
      loans.disbursement_account_id      -> accounts.account_id   (role-named column)
      loan_repayments.debit_account_id   -> accounts.account_id   (role-named; a few legacy orphans)
      portfolios.settlement_account_id   -> accounts.account_id   (role-named column)
      cards.linked_account_no            -> accounts.account_number  (natural-key copy, not a key)

Sensitive columns use the formats the Pattern Analyzer already recognises
(PAN, Aadhaar, 11-digit account number, IFSC-style branch code, card number),
so profiling classifies them. Card numbers are Luhn-valid and Aadhaar-style
numbers are Verhoeff-valid. No CVV / PIN column exists, on purpose (PCI-DSS).

All values are fictional. Build:  python -m sample_domains.banking [path] [seed]
"""

import os
import random
import sqlite3
import sys
from datetime import date, timedelta

DOMAIN_KEY = "banking"
DEFAULT_DB_FILE = "banking.db"
DEFAULT_SEED = 2026

# Number of NON-EXISTENT account ids planted in loan_repayments.debit_account_id
# (closed / purged accounts - the classic dirty legacy reference).
LEGACY_ORPHAN_ACCOUNTS = 2

BANKING_DDL = """
CREATE TABLE branches (
    branch_id     INTEGER PRIMARY KEY,
    branch_code   TEXT,
    branch_name   TEXT,
    ifsc_code     TEXT,
    city          TEXT,
    state         TEXT
);

CREATE TABLE products (
    product_id        INTEGER PRIMARY KEY,
    product_code      TEXT,
    product_name      TEXT,
    product_category  TEXT,
    interest_rate     REAL,
    min_balance       REAL
);

CREATE TABLE customers (
    customer_id    INTEGER PRIMARY KEY,
    cif_number     TEXT,
    first_name     TEXT,
    last_name      TEXT,
    dob            TEXT,
    gender         TEXT,
    email          TEXT,
    phone          TEXT,
    pan_number     TEXT,
    aadhaar_number TEXT,
    address        TEXT,
    city           TEXT,
    state          TEXT,
    pin_code       TEXT,
    segment        TEXT,
    kyc_status     TEXT,
    customer_since TEXT
);

CREATE TABLE accounts (
    account_id      INTEGER PRIMARY KEY,
    account_number  TEXT,
    customer_id     INTEGER REFERENCES customers(customer_id),
    branch_id       INTEGER REFERENCES branches(branch_id),
    product_id      INTEGER REFERENCES products(product_id),
    account_type    TEXT,
    status          TEXT,
    opened_date     TEXT,
    current_balance REAL,
    currency        TEXT
);

CREATE TABLE cards (
    card_id           INTEGER PRIMARY KEY,
    account_id        INTEGER REFERENCES accounts(account_id),
    linked_account_no TEXT,
    card_number       TEXT,
    card_type         TEXT,
    network           TEXT,
    issued_date       TEXT,
    expiry_date       TEXT,
    status            TEXT,
    daily_limit       REAL
);

CREATE TABLE transactions (
    txn_id       INTEGER PRIMARY KEY,
    account_id   INTEGER REFERENCES accounts(account_id) NOT NULL,
    card_id      INTEGER,
    txn_date     TEXT,
    txn_type     TEXT,
    channel      TEXT,
    amount       REAL,
    description  TEXT,
    status       TEXT
);

CREATE TABLE loans (
    loan_id                 INTEGER PRIMARY KEY,
    customer_id             INTEGER REFERENCES customers(customer_id) NOT NULL,
    product_id              INTEGER REFERENCES products(product_id),
    disbursement_account_id INTEGER NOT NULL,
    loan_type               TEXT,
    principal_amount        REAL,
    interest_rate           REAL,
    tenure_months           INTEGER,
    sanction_date           TEXT,
    status                  TEXT
);

CREATE TABLE loan_repayments (
    repayment_id     INTEGER PRIMARY KEY,
    loan_id          INTEGER REFERENCES loans(loan_id) NOT NULL,
    debit_account_id INTEGER NOT NULL,
    due_date         TEXT,
    paid_date        TEXT,
    amount_due       REAL,
    amount_paid      REAL,
    payment_status   TEXT
);

CREATE TABLE securities (
    security_id    INTEGER PRIMARY KEY,
    isin           TEXT,
    ticker         TEXT,
    security_name  TEXT,
    asset_class    TEXT,
    currency       TEXT
);

CREATE TABLE portfolios (
    portfolio_id          INTEGER PRIMARY KEY,
    customer_id           INTEGER REFERENCES customers(customer_id) NOT NULL,
    settlement_account_id INTEGER NOT NULL,
    risk_profile          TEXT,
    advisory_type         TEXT,
    opened_date           TEXT
);

CREATE TABLE trades (
    trade_id      INTEGER PRIMARY KEY,
    portfolio_id  INTEGER REFERENCES portfolios(portfolio_id) NOT NULL,
    security_id   INTEGER REFERENCES securities(security_id) NOT NULL,
    trade_date    TEXT,
    side          TEXT,
    quantity      INTEGER,
    price         REAL,
    status        TEXT
);
"""

# What the schema above declares / leaves undeclared - used by tests and docs.
DECLARED_RELATIONSHIPS = [
    ("accounts", "customer_id", "customers", "customer_id"),
    ("accounts", "branch_id", "branches", "branch_id"),
    ("accounts", "product_id", "products", "product_id"),
    ("cards", "account_id", "accounts", "account_id"),
    ("transactions", "account_id", "accounts", "account_id"),
    ("loans", "customer_id", "customers", "customer_id"),
    ("loans", "product_id", "products", "product_id"),
    ("loan_repayments", "loan_id", "loans", "loan_id"),
    ("portfolios", "customer_id", "customers", "customer_id"),
    ("trades", "portfolio_id", "portfolios", "portfolio_id"),
    ("trades", "security_id", "securities", "security_id"),
]
UNDECLARED_RELATIONSHIPS = [
    ("transactions", "card_id", "cards", "card_id"),
    ("loans", "disbursement_account_id", "accounts", "account_id"),
    ("loan_repayments", "debit_account_id", "accounts", "account_id"),
    ("portfolios", "settlement_account_id", "accounts", "account_id"),
]
# A real link that is NOT to a primary key, so it cannot be auto-suggested.
UNDECLARED_NATURAL_KEY = ("cards", "linked_account_no", "accounts", "account_number")


# --------------------------------------------------------------------------
# Check-digit helpers (so sample card / Aadhaar-style numbers are realistic)
# --------------------------------------------------------------------------

def luhn_valid(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    if len(digits) < 2:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _luhn_complete(prefix_digits: str) -> str:
    for check in "0123456789":
        if luhn_valid(prefix_digits + check):
            return prefix_digits + check
    raise AssertionError("unreachable")


_V_D = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],
        [3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],[5,9,8,7,6,0,4,3,2,1],
        [6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],
        [9,8,7,6,5,4,3,2,1,0]]
_V_P = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],
        [8,9,1,6,0,4,3,5,2,7],[9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],
        [2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]]
_V_INV = [0,4,3,2,1,5,6,7,8,9]


def verhoeff_valid(number: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed([x for x in number if x.isdigit()])):
        c = _V_D[c][_V_P[i % 8][int(ch)]]
    return c == 0


def _verhoeff_complete(prefix_digits: str) -> str:
    c = 0
    for i, ch in enumerate(reversed(prefix_digits)):
        c = _V_D[c][_V_P[(i + 1) % 8][int(ch)]]
    return prefix_digits + str(_V_INV[c])


# --------------------------------------------------------------------------
# Sample data
# --------------------------------------------------------------------------

_FIRST = ["Arun", "Meera", "Karthik", "Divya", "Suresh", "Anitha", "Rahul", "Priya", "Vikram", "Lakshmi",
          "Sanjay", "Kavitha", "Naveen", "Deepa", "Ravi", "Sneha", "Manoj", "Pooja", "Ajay", "Revathi"]
_LAST = ["Kumar", "Iyer", "Nair", "Reddy", "Sharma", "Menon", "Pillai", "Gupta", "Rao", "Krishnan",
         "Varma", "Chandran", "Patel", "Desai", "Bose", "Sundaram", "Joshi", "Naidu", "Shetty", "Mehta"]
_CITIES = [("Chennai", "TN"), ("Mumbai", "MH"), ("Bengaluru", "KA"), ("Hyderabad", "TS"), ("Pune", "MH"),
           ("Kochi", "KL"), ("Delhi", "DL"), ("Kolkata", "WB"), ("Coimbatore", "TN"), ("Ahmedabad", "GJ"),
           ("Jaipur", "RJ"), ("Lucknow", "UP")]
_STREETS = ["MG Road", "Anna Salai", "Park Street", "Lake View Road", "Temple Street", "Gandhi Nagar", "Mill Road"]
_PRODUCTS = [
    ("SAV-STD", "Savings Account Standard", "SAVINGS", 3.0, 1000.0),
    ("SAV-PRM", "Savings Account Premium", "SAVINGS", 3.5, 25000.0),
    ("CUR-BUS", "Business Current Account", "CURRENT", 0.0, 50000.0),
    ("SAL-ACC", "Salary Account", "SAVINGS", 3.0, 0.0),
    ("FD-REG", "Fixed Deposit", "DEPOSIT", 6.8, 10000.0),
    ("LN-HOME", "Home Loan", "LOAN", 8.5, 0.0),
    ("LN-PERS", "Personal Loan", "LOAN", 11.5, 0.0),
    ("LN-AUTO", "Auto Loan", "LOAN", 9.2, 0.0),
    ("LN-EDU", "Education Loan", "LOAN", 9.8, 0.0),
    ("CC-GOLD", "Credit Card Gold", "CARD", 36.0, 0.0),
]
_SECURITIES = [
    ("Reliance Industries", "EQUITY"), ("Tata Consultancy Services", "EQUITY"), ("Infosys", "EQUITY"),
    ("HDFC Bank", "EQUITY"), ("ICICI Bank", "EQUITY"), ("Larsen & Toubro", "EQUITY"), ("ITC", "EQUITY"),
    ("Bharti Airtel", "EQUITY"), ("State Bank of India", "EQUITY"), ("Asian Paints", "EQUITY"),
    ("Nifty 50 Index Fund", "MUTUAL_FUND"), ("Balanced Advantage Fund", "MUTUAL_FUND"),
    ("Liquid Fund Direct", "MUTUAL_FUND"), ("Flexi Cap Fund", "MUTUAL_FUND"), ("Small Cap Fund", "MUTUAL_FUND"),
    ("Govt Securities 2033", "BOND"), ("Corporate Bond AAA 2029", "BOND"), ("Tax Free Bond 2031", "BOND"),
    ("Gold ETF", "ETF"), ("Bank Nifty ETF", "ETF"),
]
_TXN_DESC = {
    "DEPOSIT": ["Cash deposit", "Salary credit", "Cheque deposit"],
    "WITHDRAWAL": ["Cash withdrawal", "ATM withdrawal"],
    "TRANSFER": ["Funds transfer", "Rent payment", "Family transfer"],
    "PAYMENT": ["Utility bill payment", "Merchant payment", "Subscription"],
    "FEE": ["Service charge", "Annual card fee"],
}


def _d(rng, start: date, end: date) -> str:
    return (start + timedelta(days=rng.randint(0, (end - start).days))).isoformat()


def _alpha(rng, n):
    return "".join(rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(n))


def _digits(rng, n):
    return "".join(rng.choice("0123456789") for _ in range(n))


DEFAULT_SIZES = {
    "branches": 12, "customers": 180, "accounts": 300, "cards": 220, "transactions": 900,
    "loans": 60, "repayments_per_loan": 8, "securities": 20, "portfolios": 40, "trades": 500,
}


def build_banking_db(path: str = DEFAULT_DB_FILE, seed: int = DEFAULT_SEED, sizes: dict | None = None) -> dict:
    """Create (replace) the banking SQLite file and fill it. Returns {table: row_count}."""
    n = dict(DEFAULT_SIZES, **(sizes or {}))
    rng = random.Random(seed)
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.executescript(BANKING_DDL)

    today = date(2026, 9, 30)

    branches = []
    for i in range(1, n["branches"] + 1):
        city, state = _CITIES[(i - 1) % len(_CITIES)]
        branches.append((i, f"BR{1000 + i}", f"{city} Main Branch" if i <= len(_CITIES) else f"{city} Annexe {i}",
                         f"TDMB0{100000 + i * 37:06d}"[:11], city, state))
    con.executemany("INSERT INTO branches VALUES (?,?,?,?,?,?)", branches)

    con.executemany("INSERT INTO products VALUES (?,?,?,?,?,?)",
                    [(i + 1, *p) for i, p in enumerate(_PRODUCTS)])
    deposit_products = [i + 1 for i, p in enumerate(_PRODUCTS) if p[2] in ("SAVINGS", "CURRENT")]
    loan_products = {p[0]: i + 1 for i, p in enumerate(_PRODUCTS) if p[2] == "LOAN"}

    customers, used_pan, used_aad = [], set(), set()
    for i in range(1, n["customers"] + 1):
        city, state = rng.choice(_CITIES)
        first, last = rng.choice(_FIRST), rng.choice(_LAST)
        while True:
            pan = f"{_alpha(rng, 5)}{_digits(rng, 4)}{_alpha(rng, 1)}"
            if pan not in used_pan:
                used_pan.add(pan); break
        while True:
            raw = _verhoeff_complete(str(rng.randint(2, 9)) + _digits(rng, 10))
            aad = f"{raw[:4]} {raw[4:8]} {raw[8:]}"
            if aad not in used_aad:
                used_aad.add(aad); break
        customers.append((
            i, f"CIF{10000000 + i}", first, last, _d(rng, date(1950, 1, 1), date(2004, 12, 31)),
            rng.choice(["M", "F"]), f"{first.lower()}.{last.lower()}{i}@examplebank.test",
            f"{rng.randint(200, 999)}-{rng.randint(200, 999)}-{rng.randint(1000, 9999)}",
            pan, aad, f"{rng.randint(1, 250)} {rng.choice(_STREETS)}", city, state, _digits(rng, 6),
            rng.choices(["RETAIL", "PREMIUM", "PRIORITY"], [70, 22, 8])[0],
            rng.choices(["VERIFIED", "PENDING", "EXPIRED"], [88, 8, 4])[0],
            _d(rng, date(2005, 1, 1), date(2025, 12, 31))))
    con.executemany("INSERT INTO customers VALUES (" + ",".join("?" * 17) + ")", customers)

    accounts, used_acct = [], set()
    for i in range(1, n["accounts"] + 1):
        cust = rng.randint(1, n["customers"])
        pid = rng.choice(deposit_products)
        while True:
            num = str(rng.randint(2, 9)) + _digits(rng, 10)
            if num not in used_acct:
                used_acct.add(num); break
        accounts.append((i, num, cust, rng.randint(1, n["branches"]), pid,
                         _PRODUCTS[pid - 1][2], rng.choices(["ACTIVE", "DORMANT", "CLOSED"], [88, 8, 4])[0],
                         _d(rng, date(2008, 1, 1), date(2026, 6, 30)),
                         round(rng.uniform(500, 2500000), 2), "INR"))
    con.executemany("INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?,?,?)", accounts)
    acct_owner = {a[0]: a[2] for a in accounts}
    acct_number = {a[0]: a[1] for a in accounts}
    active_ids = [a[0] for a in accounts if a[6] == "ACTIVE"]

    cards, used_card = [], set()
    for i in range(1, n["cards"] + 1):
        acct = rng.choice(active_ids)
        while True:
            body = rng.choice(["4", "5"]) + _digits(rng, 14)
            full = _luhn_complete(body)
            if full not in used_card:
                used_card.add(full); break
        issued = _d(rng, date(2021, 1, 1), date(2026, 3, 31))
        y, m, d_ = (int(x) for x in issued.split("-"))
        cards.append((i, acct, acct_number[acct], f"{full[:4]}-{full[4:8]}-{full[8:12]}-{full[12:]}",
                      rng.choice(["DEBIT", "DEBIT", "CREDIT"]), "VISA" if full[0] == "4" else "MASTERCARD",
                      issued, date(y + 5, m, min(d_, 28)).isoformat(),
                      rng.choices(["ACTIVE", "BLOCKED", "EXPIRED"], [90, 6, 4])[0],
                      float(rng.choice([25000, 50000, 100000, 200000]))))
    con.executemany("INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?)", cards)
    card_account = {c[0]: c[1] for c in cards}
    card_ids = list(card_account)

    txns = []
    for i in range(1, n["transactions"] + 1):
        if rng.random() < 0.40:                                   # card-present: ATM / POS
            card = rng.choice(card_ids)
            acct, channel = card_account[card], rng.choice(["ATM", "POS"])
            ttype = "WITHDRAWAL" if channel == "ATM" else "PAYMENT"
        else:                                                     # no card involved
            card, acct = None, rng.choice(list(acct_owner))
            channel = rng.choice(["UPI", "NEFT", "BRANCH", "ONLINE"])
            ttype = rng.choices(["DEPOSIT", "TRANSFER", "PAYMENT", "FEE"], [30, 35, 30, 5])[0]
        txns.append((i, acct, card, _d(rng, date(2025, 10, 1), today), ttype, channel,
                     round(rng.uniform(50, 150000), 2), rng.choice(_TXN_DESC[ttype]),
                     rng.choices(["SUCCESS", "FAILED", "REVERSED"], [95, 3, 2])[0]))
    con.executemany("INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?)", txns)

    loans = []
    for i in range(1, n["loans"] + 1):
        acct = rng.choice(active_ids)
        code = rng.choice(list(loan_products))
        rate = _PRODUCTS[loan_products[code] - 1][4]
        loans.append((i, acct_owner[acct], loan_products[code], acct, _PRODUCTS[loan_products[code] - 1][1],
                      float(rng.choice([200000, 500000, 1000000, 2500000, 5000000])), rate,
                      rng.choice([12, 24, 36, 60, 120, 240]), _d(rng, date(2022, 1, 1), date(2026, 3, 31)),
                      rng.choices(["ACTIVE", "CLOSED", "NPA"], [80, 15, 5])[0]))
    con.executemany("INSERT INTO loans VALUES (?,?,?,?,?,?,?,?,?,?)", loans)

    # legacy orphans: repayments debited from accounts that were later purged
    max_acct = max(acct_owner)
    orphan_loans = set(rng.sample(range(1, n["loans"] + 1), LEGACY_ORPHAN_ACCOUNTS))
    orphan_ids = {ln: max_acct + 100 + k for k, ln in enumerate(sorted(orphan_loans), start=1)}
    reps, rid = [], 1
    for loan in loans:
        start = date.fromisoformat(loan[8])
        emi = round(loan[5] / loan[7] * (1 + loan[6] / 100), 2)
        debit = orphan_ids.get(loan[0], loan[3])
        for k in range(n["repayments_per_loan"]):
            due = start + timedelta(days=30 * (k + 1))
            paid = due <= today
            reps.append((rid, loan[0], debit, due.isoformat(),
                         (due + timedelta(days=rng.randint(0, 4))).isoformat() if paid else None,
                         emi, emi if paid else 0.0, "PAID" if paid else "UPCOMING"))
            rid += 1
    con.executemany("INSERT INTO loan_repayments VALUES (?,?,?,?,?,?,?,?)", reps)

    secs = []
    for i in range(1, n["securities"] + 1):
        name, cls = _SECURITIES[(i - 1) % len(_SECURITIES)]
        secs.append((i, f"IN{_alpha(rng, 1)}{_digits(rng, 3)}{_alpha(rng, 2)}{_digits(rng, 4)}",
                     (name.split()[0][:4]).upper() + str(i), name, cls, "INR"))
    con.executemany("INSERT INTO securities VALUES (?,?,?,?,?,?)", secs)

    ports = []
    for i in range(1, n["portfolios"] + 1):
        acct = rng.choice(active_ids)
        ports.append((i, acct_owner[acct], acct, rng.choice(["CONSERVATIVE", "BALANCED", "AGGRESSIVE"]),
                      rng.choice(["DISCRETIONARY", "ADVISORY", "EXECUTION_ONLY"]),
                      _d(rng, date(2015, 1, 1), date(2026, 3, 31))))
    con.executemany("INSERT INTO portfolios VALUES (?,?,?,?,?,?)", ports)

    trades = [(i, rng.randint(1, n["portfolios"]), rng.randint(1, n["securities"]),
               _d(rng, date(2025, 10, 1), today), rng.choice(["BUY", "SELL"]), rng.randint(1, 500),
               round(rng.uniform(20, 3500), 2), rng.choices(["SETTLED", "PENDING", "CANCELLED"], [90, 7, 3])[0])
              for i in range(1, n["trades"] + 1)]
    con.executemany("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?)", trades)

    con.commit()
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}
    con.close()
    return counts


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB_FILE
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_SEED
    for table, rows in build_banking_db(target, seed).items():
        print(f"{table:18s}{rows:>6d}")
    print(f"written to {target}")
