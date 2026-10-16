"""
metadata_store/seed.py

Seeds the Data Dictionary (metadata_store.data_dictionary) once, on
startup, if it's empty. This is the "business glossary" half of the
Metadata & Knowledge layer (TDD Section 3.1): for every pattern_type the
Pattern Analyzer already knows how to produce (see
pattern_analysis/pattern_types.yaml), we attach a business-friendly name,
a plain description, and a default sensitivity level. The seed list below
spans multiple industries on purpose (healthcare, banking/finance, and
cross-sector identity docs) - the platform isn't tied to any one domain,
and new pattern types from any industry can be added here the same way.

This is intentionally the ONLY place this business context is written
down. The Schema Catalog endpoint, the Query Agent, and the Synthetic
Data Generator all read it from here rather than each hardcoding their
own copy - that's what "reuse the ... Data Dictionary" means in practice.
"""

from metadata_store.models import DataDictionaryEntry

# pattern_type -> (business_name, description, sensitivity_level)
# The keys here are exactly the pattern_type labels pattern_types.yaml
# and pattern_analyzer.py's generic fallback can produce - kept in sync
# by hand since there are only a handful of them.
DATA_DICTIONARY_SEED = {
    "SSN": (
        "Social Security Number",
        "A US government-issued identifier unique to one person.",
        "PHI/PII - High",
    ),
    "DATE": (
        "Date",
        "A calendar date - e.g. date of birth, admission, or discharge.",
        "Sensitive when tied to an individual (e.g. DOB)",
    ),
    "PHONE": (
        "Phone Number",
        "A contact telephone number.",
        "PII - Medium",
    ),
    "ZIP_CODE": (
        "ZIP Code",
        "A 5-digit US postal code.",
        "PII - Low (quasi-identifier)",
    ),
    "ZIP_PLUS4": (
        "ZIP+4 Code",
        "An extended 9-digit US postal code.",
        "PII - Low (quasi-identifier)",
    ),
    "MRN": (
        "Medical Record Number",
        "A hospital-assigned identifier for a patient's medical record.",
        "PHI - High",
    ),
    "INSURANCE_ID": (
        "Insurance ID",
        "A health insurance member or policy identifier.",
        "PHI - High",
    ),
    "CREDIT_CARD": (
        "Credit/Debit Card Number",
        "A payment card number captured during a transaction.",
        "PCI/Financial - High",
    ),
    "ACCOUNT_NUMBER": (
        "Bank Account Number",
        "A customer's bank or financial account identifier.",
        "Financial PII - High",
    ),
    "IFSC_CODE": (
        "Bank Branch Code (IFSC)",
        "A bank branch routing code used to identify the receiving bank in a transfer.",
        "Non-sensitive (context-dependent)",
    ),
    "PAN_NUMBER": (
        "PAN (Tax ID)",
        "A government-issued permanent account number used for tax and financial KYC.",
        "PII - High",
    ),
    "AADHAAR_NUMBER": (
        "National ID Number",
        "A government-issued national identity number, used across banking, healthcare, telecom, and other sectors.",
        "PII - High",
    ),
    "TEXT": (
        "Free Text (alphabetic)",
        "Unstructured alphabetic text - commonly names or short labels.",
        "Potentially PII - review recommended",
    ),
    "TEXT_WITH_SEPARATOR": (
        "Free Text (with punctuation)",
        "Multi-word or punctuated text - commonly emails, addresses, or full names.",
        "Potentially PII - review recommended",
    ),
    "NUMERIC": (
        "Numeric Value",
        "A column composed purely of digits with no recognized specific pattern.",
        "Non-sensitive (context-dependent)",
    ),
    "NUMERIC_WITH_SEPARATOR": (
        "Formatted Number",
        "A numeric value with separators (e.g. dashes) not matching a known specific pattern.",
        "Non-sensitive (context-dependent)",
    ),
    "MIXED_ALPHANUMERIC": (
        "Mixed Alphanumeric",
        "A value mixing letters, digits, and symbols with no recognized specific pattern.",
        "Needs review",
    ),
}


def seed_data_dictionary(db) -> None:
    """
    Idempotent: only inserts entries that don't already exist, and never
    overwrites an entry a human may have since edited by hand in the DB.
    Safe to call on every app startup.
    """
    existing = {row.pattern_type for row in db.query(DataDictionaryEntry.pattern_type).all()}

    for pattern_type, (business_name, description, sensitivity_level) in DATA_DICTIONARY_SEED.items():
        if pattern_type in existing:
            continue
        db.add(DataDictionaryEntry(
            pattern_type=pattern_type,
            business_name=business_name,
            description=description,
            sensitivity_level=sensitivity_level,
        ))

    db.commit()
