"""
database.py — SQLite case storage.
Schema is intentionally wide and extensible.
To add a new field: add a column to SCHEMA and a key to FIELD_MAP in extractor.py.
"""

import sqlite3
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv("DATABASE_PATH", "cases.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist. Safe to call on every startup."""
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cases (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,

            -- Identifiers
            case_number           TEXT UNIQUE NOT NULL,
            client_matter_number  TEXT UNIQUE NOT NULL,

            -- Client info
            client_name           TEXT,
            client_email          TEXT,
            client_phone          TEXT,
            client_address        TEXT,

            -- Case info
            case_type             TEXT,
            incident_date         TEXT,
            filing_date           TEXT,
            incident_description  TEXT,
            injury_severity       TEXT,

            -- Parties
            opposing_party        TEXT,
            opposing_counsel      TEXT,

            -- Background
            insurance_info        TEXT,
            employer_info         TEXT,
            income_details        TEXT,
            prior_legal_rep       TEXT,
            referral_source       TEXT,

            -- Consent / signatures
            signature_present     TEXT,
            consent_given         TEXT,

            -- Meta
            source_email          TEXT,
            status                TEXT DEFAULT 'new',
            created_at            TEXT NOT NULL,
            updated_at            TEXT NOT NULL,
            notes                 TEXT,

            -- Raw extracted text (for debugging / re-extraction)
            raw_pdf_text          TEXT,
            raw_gpt_response      TEXT
        )
    """)
    conn.commit()
    conn.close()
    print(f"[DB] Initialized at {DB_PATH}")


def generate_case_number():
    """Auto-incrementing case number: CASE-2025-0001"""
    conn = get_conn()
    row = conn.execute("SELECT COUNT(*) as cnt FROM cases").fetchone()
    count = row["cnt"] + 1
    conn.close()
    year = datetime.now().year
    return f"CASE-{year}-{count:04d}"


def generate_matter_number():
    """Client matter number: CM-2025-0001"""
    conn = get_conn()
    row = conn.execute("SELECT COUNT(*) as cnt FROM cases").fetchone()
    count = row["cnt"] + 1
    conn.close()
    year = datetime.now().year
    return f"CM-{year}-{count:04d}"


def insert_case(fields: dict, source_email: str, raw_text: str, raw_gpt: str) -> dict:
    """
    Insert a new case. Returns the full case row as a dict.
    `fields` is the extracted dict from GPT.
    """
    now = datetime.now().isoformat()
    case_number = generate_case_number()
    matter_number = generate_matter_number()

    conn = get_conn()
    conn.execute("""
        INSERT INTO cases (
            case_number, client_matter_number,
            client_name, client_email, client_phone, client_address,
            case_type, incident_date, filing_date, incident_description, injury_severity,
            opposing_party, opposing_counsel,
            insurance_info, employer_info, income_details, prior_legal_rep, referral_source,
            signature_present, consent_given,
            source_email, status, created_at, updated_at,
            raw_pdf_text, raw_gpt_response
        ) VALUES (
            :case_number, :client_matter_number,
            :client_name, :client_email, :client_phone, :client_address,
            :case_type, :incident_date, :filing_date, :incident_description, :injury_severity,
            :opposing_party, :opposing_counsel,
            :insurance_info, :employer_info, :income_details, :prior_legal_rep, :referral_source,
            :signature_present, :consent_given,
            :source_email, :status, :created_at, :updated_at,
            :raw_pdf_text, :raw_gpt_response
        )
    """, {
        "case_number": case_number,
        "client_matter_number": matter_number,
        **{k: fields.get(k) for k in [
            "client_name", "client_email", "client_phone", "client_address",
            "case_type", "incident_date", "filing_date", "incident_description", "injury_severity",
            "opposing_party", "opposing_counsel",
            "insurance_info", "employer_info", "income_details", "prior_legal_rep", "referral_source",
            "signature_present", "consent_given",
        ]},
        "source_email": source_email,
        "status": "new",
        "created_at": now,
        "updated_at": now,
        "raw_pdf_text": raw_text,
        "raw_gpt_response": raw_gpt,
    })
    conn.commit()

    case = conn.execute(
        "SELECT * FROM cases WHERE case_number = ?", (case_number,)
    ).fetchone()
    conn.close()
    return dict(case)


def get_all_cases():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM cases ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_case(case_number: str):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM cases WHERE case_number = ?", (case_number,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_case_status(case_number: str, status: str, notes: str = None):
    now = datetime.now().isoformat()
    conn = get_conn()
    if notes:
        conn.execute(
            "UPDATE cases SET status=?, notes=?, updated_at=? WHERE case_number=?",
            (status, notes, now, case_number)
        )
    else:
        conn.execute(
            "UPDATE cases SET status=?, updated_at=? WHERE case_number=?",
            (status, now, case_number)
        )
    conn.commit()
    conn.close()
