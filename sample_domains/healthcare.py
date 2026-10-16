"""Deterministic builder for the fictional healthcare demo source.

Run from the TDM Platform project root:
    python -m sample_domains.healthcare [path] [seed]

The database contains only synthetic demo records. It is rebuilt only when
explicitly invoked, or automatically by the domain registry when missing.
"""
from __future__ import annotations

import os
import random
import sqlite3
import sys
from datetime import date, timedelta

DOMAIN_KEY = "healthcare"
DEFAULT_DB_FILE = "hospital.db"
DEFAULT_SEED = 2026

DEFAULT_SIZES = {
    "patients": 120,
    "doctors": 20,
    "appointments": 300,
    "insurance_claims": 300,
}

HEALTHCARE_DDL = """
CREATE TABLE patients (
    patient_id INTEGER PRIMARY KEY,
    mrn TEXT NOT NULL UNIQUE,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    date_of_birth TEXT NOT NULL,
    gender TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    insurance_member_id TEXT NOT NULL UNIQUE,
    address TEXT,
    city TEXT,
    state TEXT,
    postal_code TEXT,
    blood_group TEXT
);

CREATE TABLE doctors (
    doctor_id INTEGER PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    specialization TEXT NOT NULL,
    department TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    license_number TEXT NOT NULL UNIQUE
);

CREATE TABLE appointments (
    appointment_id INTEGER PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(patient_id),
    doctor_id INTEGER NOT NULL REFERENCES doctors(doctor_id),
    appointment_date TEXT NOT NULL,
    department TEXT NOT NULL,
    diagnosis_code TEXT,
    diagnosis_desc TEXT,
    notes TEXT,
    status TEXT NOT NULL
);

CREATE TABLE insurance_claims (
    claim_id INTEGER PRIMARY KEY,
    appointment_id INTEGER NOT NULL REFERENCES appointments(appointment_id),
    patient_id INTEGER NOT NULL REFERENCES patients(patient_id),
    member_id TEXT NOT NULL,
    claim_date TEXT NOT NULL,
    claim_amount REAL NOT NULL CHECK (claim_amount >= 0),
    claim_status TEXT NOT NULL,
    diagnosis_code TEXT
);
CREATE INDEX idx_appointments_patient_id ON appointments(patient_id);
CREATE INDEX idx_appointments_doctor_id ON appointments(doctor_id);
CREATE INDEX idx_claims_patient_id ON insurance_claims(patient_id);
CREATE INDEX idx_claims_appointment_id ON insurance_claims(appointment_id);
"""

_FIRST_NAMES = ["Aarav", "Aditi", "Anaya", "Arjun", "Diya", "Ishaan", "Kabir", "Meera", "Neha", "Rohan", "Sana", "Vivaan", "Maya", "Kiran", "Nisha", "Dev", "Ira", "Rahul", "Tara", "Zoya"]
_LAST_NAMES = ["Shah", "Patel", "Rao", "Mehta", "Nair", "Iyer", "Kapoor", "Das", "Khan", "Joshi", "Menon", "Kulkarni", "Desai", "Verma", "Sethi", "Pillai"]
_CITIES = [("Bengaluru", "Karnataka", "560001"), ("Mumbai", "Maharashtra", "400001"), ("Pune", "Maharashtra", "411001"), ("Ahmedabad", "Gujarat", "380001"), ("Hyderabad", "Telangana", "500001"), ("Chennai", "Tamil Nadu", "600001"), ("Delhi", "Delhi", "110001"), ("Kochi", "Kerala", "682001")]
_DEPARTMENTS = ["Cardiology", "General Medicine", "Orthopedics", "Pediatrics", "Neurology", "Dermatology", "Oncology", "ENT", "Ophthalmology", "Endocrinology"]
_DIAGNOSES = [("I10", "Essential hypertension"), ("E11.9", "Type 2 diabetes mellitus"), ("J06.9", "Acute upper respiratory infection"), ("M25.5", "Joint pain"), ("R51.9", "Headache"), ("K21.9", "Gastro-esophageal reflux"), ("J30.9", "Allergic rhinitis"), ("Z00.00", "Routine health examination")]
_STREETS = ["Lake View Road", "Park Street", "MG Road", "Green Avenue", "Station Road", "River Lane", "Garden Road", "Hill View"]


def _date_between(rng: random.Random, start: date, end: date) -> str:
    return (start + timedelta(days=rng.randint(0, (end - start).days))).isoformat()


def build_healthcare_db(path: str = DEFAULT_DB_FILE, seed: int = DEFAULT_SEED, sizes: dict | None = None) -> dict:
    """Create/replace the healthcare SQLite file and return table row counts."""
    n = dict(DEFAULT_SIZES, **(sizes or {}))
    for table, count in n.items():
        if not isinstance(count, int) or count < 1:
            raise ValueError(f"Size for {table} must be a positive integer")
    if n["appointments"] < 1 or n["insurance_claims"] < 1:
        raise ValueError("appointments and insurance_claims must contain rows")

    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    if os.path.exists(path):
        os.remove(path)

    rng = random.Random(seed)
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        con.executescript(HEALTHCARE_DDL)
        patients = []
        for i in range(1, n["patients"] + 1):
            first = rng.choice(_FIRST_NAMES)
            last = rng.choice(_LAST_NAMES)
            city, state, postal = rng.choice(_CITIES)
            patients.append((
                i, f"MRN{i:06d}", first, last,
                _date_between(rng, date(1940, 1, 1), date(2015, 12, 31)),
                rng.choice(["F", "M", "X"]),
                f"+91-{rng.randint(6000000000, 9999999999)}",
                f"patient{i}@examplehealth.test", f"UH{i:09d}",
                f"{rng.randint(1, 250)} {rng.choice(_STREETS)}", city, state, postal,
                rng.choice(["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]),
            ))
        con.executemany("INSERT INTO patients VALUES (" + ",".join("?" * 14) + ")", patients)

        doctors = []
        for i in range(1, n["doctors"] + 1):
            first = rng.choice(_FIRST_NAMES)
            last = rng.choice(_LAST_NAMES)
            department = _DEPARTMENTS[(i - 1) % len(_DEPARTMENTS)]
            doctors.append((i, first, last, department, department, f"doctor{i}@examplehealth.test",
                            f"+91-{rng.randint(6000000000, 9999999999)}", f"LIC{i:07d}"))
        con.executemany("INSERT INTO doctors VALUES (?,?,?,?,?,?,?,?)", doctors)

        appointments = []
        appointment_patient = {}
        for i in range(1, n["appointments"] + 1):
            patient_id = rng.randint(1, n["patients"])
            doctor_id = rng.randint(1, n["doctors"])
            department = doctors[doctor_id - 1][4]
            diagnosis_code, diagnosis_desc = rng.choice(_DIAGNOSES)
            appointments.append((i, patient_id, doctor_id,
                                 _date_between(rng, date(2025, 1, 1), date(2026, 9, 30)),
                                 department, diagnosis_code, diagnosis_desc,
                                 rng.choice(["Follow-up visit", "Initial consultation", "Routine review", "Diagnostic review"]),
                                 rng.choices(["COMPLETED", "SCHEDULED", "CANCELLED"], [75, 20, 5])[0]))
            appointment_patient[i] = patient_id
        con.executemany("INSERT INTO appointments VALUES (?,?,?,?,?,?,?,?,?)", appointments)

        claims = []
        for i in range(1, n["insurance_claims"] + 1):
            appointment_id = rng.randint(1, n["appointments"])
            patient_id = appointment_patient[appointment_id]
            patient = patients[patient_id - 1]
            appointment = appointments[appointment_id - 1]
            claims.append((i, appointment_id, patient_id, patient[8],
                           _date_between(rng, date(2025, 1, 1), date(2026, 9, 30)),
                           round(rng.uniform(500, 125000), 2),
                           rng.choices(["APPROVED", "PENDING", "REJECTED", "PAID"], [45, 25, 10, 20])[0],
                           appointment[5]))
        con.executemany("INSERT INTO insurance_claims VALUES (?,?,?,?,?,?,?,?)", claims)
        con.commit()

        fk_errors = con.execute("PRAGMA foreign_key_check").fetchall()
        if fk_errors:
            raise RuntimeError(f"Generated healthcare database has foreign-key violations: {fk_errors[:5]}")
        return {table: n[table] for table in ("patients", "doctors", "appointments", "insurance_claims")}
    except Exception:
        con.rollback()
        con.close()
        if os.path.exists(path):
            os.remove(path)
        raise
    finally:
        try:
            con.close()
        except Exception:
            pass


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB_FILE
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_SEED
    for table, count in build_healthcare_db(output, seed).items():
        print(f"{table:<20} {count:>6}")
    print(f"written to {output}")
