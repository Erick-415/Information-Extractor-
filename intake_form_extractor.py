"""
Legal Intake Form Extractor
============================
Extracts data from personal injury intake forms (PDF, PNG, JPEG),
validates fields, and generates a structured case file.

Dependencies:
    pip3 install pymupdf pillow pytesseract openai python-dotenv

Also requires: tesseract-ocr (system package)
    Ubuntu/Debian: sudo apt install tesseract-ocr
    Mac: brew install tesseract
"""

import os
import re
import json
import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    from PIL import Image
    import pytesseract
except ImportError:
    pytesseract = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


# ─────────────────────────────────────────────────────────────────────────────
# 1. DATA MODEL
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PersonalInfo:
    name: Optional[str] = None
    dob: Optional[str] = None
    ssn: Optional[str] = None
    address: Optional[str] = None
    drivers_license: Optional[str] = None
    phone: Optional[str] = None
    employer: Optional[str] = None
    employer_address: Optional[str] = None
    supervisor_name: Optional[str] = None
    work_phone: Optional[str] = None
    occupation: Optional[str] = None
    employment_start_date: Optional[str] = None
    salary: Optional[str] = None
    health_insurance: Optional[str] = None
    dates_lost_from_work_start: Optional[str] = None
    dates_lost_from_work_end: Optional[str] = None
    total_compensation_lost: Optional[str] = None


@dataclass
class AccidentInfo:
    date_of_accident: Optional[str] = None
    time_of_day: Optional[str] = None
    day_of_week: Optional[str] = None
    location: Optional[str] = None
    weather_conditions: Optional[str] = None
    person_who_caused_accident: Optional[str] = None
    defendant_insurer: Optional[str] = None
    defendant_policy_number: Optional[str] = None
    filed_reports_with_insurer: Optional[str] = None
    witnesses: list = field(default_factory=list)
    description: Optional[str] = None
    police_report: Optional[str] = None
    police_agency: Optional[str] = None
    client_insurance_policy: Optional[str] = None
    client_insurance_company: Optional[str] = None
    client_insurance_agent: Optional[str] = None
    insurance_claim_made: Optional[str] = None


@dataclass
class MedicalInfo:
    injury_description: Optional[str] = None
    hospitals: Optional[str] = None
    doctors: Optional[str] = None
    medical_procedures: Optional[str] = None
    medications: Optional[str] = None
    other_special_damages: Optional[str] = None
    prior_accidents: Optional[str] = None
    prior_legal_proceedings: Optional[str] = None


@dataclass
class CaseFile:
    case_id: str = field(default_factory=lambda: f"CASE-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}")
    created_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    source_file: Optional[str] = None
    personal_info: PersonalInfo = field(default_factory=PersonalInfo)
    accident_info: AccidentInfo = field(default_factory=AccidentInfo)
    medical_info: MedicalInfo = field(default_factory=MedicalInfo)
    validation_report: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# 2. FILE → RAW TEXT
# ─────────────────────────────────────────────────────────────────────────────

def extract_text_from_pdf(pdf_path: str) -> str:
    if fitz is None:
        raise ImportError("Run: pip3 install pymupdf")
    doc = fitz.open(pdf_path)
    return "\n".join(page.get_text() for page in doc)


def extract_text_from_image(image_path: str) -> str:
    if pytesseract is None:
        raise ImportError("Run: pip3 install pytesseract pillow")
    return pytesseract.image_to_string(Image.open(image_path))


def get_raw_text(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(file_path)
    elif ext in (".png", ".jpg", ".jpeg"):
        return extract_text_from_image(file_path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")


# ─────────────────────────────────────────────────────────────────────────────
# 3. AI FIELD EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """
You are a legal data extraction assistant. Given the raw text of a personal injury
intake form, extract every field below and return ONLY valid JSON. Use null for blank fields.

{
  "personal_info": {
    "name": null, "dob": null, "ssn": null, "address": null,
    "drivers_license": null, "phone": null, "employer": null,
    "employer_address": null, "supervisor_name": null, "work_phone": null,
    "occupation": null, "employment_start_date": null, "salary": null,
    "health_insurance": null, "dates_lost_from_work_start": null,
    "dates_lost_from_work_end": null, "total_compensation_lost": null
  },
  "accident_info": {
    "date_of_accident": null, "time_of_day": null, "day_of_week": null,
    "location": null, "weather_conditions": null,
    "person_who_caused_accident": null, "defendant_insurer": null,
    "defendant_policy_number": null, "filed_reports_with_insurer": null,
    "witnesses": [], "description": null, "police_report": null,
    "police_agency": null, "client_insurance_policy": null,
    "client_insurance_company": null, "client_insurance_agent": null,
    "insurance_claim_made": null
  },
  "medical_info": {
    "injury_description": null, "hospitals": null, "doctors": null,
    "medical_procedures": null, "medications": null,
    "other_special_damages": null, "prior_accidents": null,
    "prior_legal_proceedings": null
  }
}

Form text:
{form_text}
"""


def extract_fields_with_ai(raw_text: str, api_key: str) -> dict:
    if OpenAI is None:
        raise ImportError("Run: pip3 install openai")

    client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=2048,
        messages=[
            {"role": "system", "content": "You are a legal data extraction assistant. Return only valid JSON."},
            {"role": "user", "content": EXTRACTION_PROMPT.format(form_text=raw_text)}
        ]
    )

    text = response.choices[0].message.content.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return json.loads(text)


# ─────────────────────────────────────────────────────────────────────────────
# 4. VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

REQUIRED_FIELDS = {
    "personal_info": ["name", "dob", "ssn", "address", "phone", "employer", "occupation"],
    "accident_info": ["date_of_accident", "location", "description"],
    "medical_info": ["injury_description"],
}


def validate_ssn(v):
    return bool(v) and re.sub(r"[-\s]", "", v).isdigit() and len(re.sub(r"[-\s]", "", v)) == 9

def validate_date(v):
    if not v: return False
    return any(re.fullmatch(p, v.strip()) for p in [
        r"\d{1,2}/\d{1,2}/\d{2,4}", r"\d{4}-\d{2}-\d{2}", r"[A-Za-z]+ \d{1,2},? \d{4}"
    ])

def validate_phone(v):
    return bool(v) and len(re.sub(r"\D", "", v)) >= 10


def run_validation(case: CaseFile) -> dict:
    report = {"filled_count": 0, "total_count": 0,
              "missing_required": [], "type_errors": [], "completeness_pct": 0.0}

    sections = {
        "personal_info": asdict(case.personal_info),
        "accident_info": asdict(case.accident_info),
        "medical_info": asdict(case.medical_info),
    }

    DATE_FIELDS = {"dob", "date_of_accident", "employment_start_date",
                   "dates_lost_from_work_start", "dates_lost_from_work_end"}
    PHONE_FIELDS = {"phone", "work_phone"}

    for sec, data in sections.items():
        for fname, val in data.items():
            if fname == "witnesses":
                report["total_count"] += 1
                if val: report["filled_count"] += 1
                continue
            report["total_count"] += 1
            if val not in (None, "", []):
                report["filled_count"] += 1
                v = str(val)
                if fname in DATE_FIELDS and not validate_date(v):
                    report["type_errors"].append({"field": f"{sec}.{fname}", "issue": f"'{v}' is not a valid date"})
                elif fname == "ssn" and not validate_ssn(v):
                    report["type_errors"].append({"field": f"{sec}.{fname}", "issue": "SSN must be 9 digits"})
                elif fname in PHONE_FIELDS and not validate_phone(v):
                    report["type_errors"].append({"field": f"{sec}.{fname}", "issue": f"'{v}' is not a valid phone"})
            if fname in REQUIRED_FIELDS.get(sec, []) and val in (None, "", []):
                report["missing_required"].append(f"{sec}.{fname}")

    report["completeness_pct"] = round(report["filled_count"] / report["total_count"] * 100, 1)
    return report


# ─────────────────────────────────────────────────────────────────────────────
# 5. BUILD + SAVE CASE FILE
# ─────────────────────────────────────────────────────────────────────────────

def dict_to_case_file(extracted: dict, source_file: str) -> CaseFile:
    case = CaseFile(source_file=source_file)
    for f in PersonalInfo.__dataclass_fields__:
        if f in extracted.get("personal_info", {}):
            setattr(case.personal_info, f, extracted["personal_info"][f])
    for f in AccidentInfo.__dataclass_fields__:
        if f in extracted.get("accident_info", {}):
            setattr(case.accident_info, f, extracted["accident_info"][f])
    for f in MedicalInfo.__dataclass_fields__:
        if f in extracted.get("medical_info", {}):
            setattr(case.medical_info, f, extracted["medical_info"][f])
    return case


def print_report(case: CaseFile):
    v = case.validation_report
    print(f"\n{'='*60}")
    print(f"  CASE FILE  |  {case.case_id}")
    print(f"{'='*60}")
    print(f"  Source  : {case.source_file}")
    print(f"  Fields  : {v['filled_count']}/{v['total_count']} ({v['completeness_pct']}%)")
    print()
    if v["missing_required"]:
        print("  ⚠  MISSING REQUIRED:")
        for m in v["missing_required"]: print(f"      - {m}")
    else:
        print("  ✓  All required fields present.")
    print()
    if v["type_errors"]:
        print("  ✗  TYPE ERRORS:")
        for e in v["type_errors"]: print(f"      - {e['field']}: {e['issue']}")
    else:
        print("  ✓  No type errors.")
    print("="*60)


def save_case_file(case: CaseFile, output_dir="case_files") -> str:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{case.case_id}.json")
    with open(path, "w") as f:
        json.dump(asdict(case), f, indent=2)
    print(f"  Saved → {path}")
    return path


# ─────────────────────────────────────────────────────────────────────────────
# 6. MAIN PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

def process_intake_form(file_path: str, api_key: str, output_dir="case_files") -> CaseFile:
    print(f"\n[1/4] Reading: {file_path}")
    raw_text = get_raw_text(file_path)

    print("[2/4] Extracting fields with AI...")
    extracted = extract_fields_with_ai(raw_text, api_key)

    print("[3/4] Building case file...")
    case = dict_to_case_file(extracted, source_file=file_path)

    print("[4/4] Validating...")
    case.validation_report = run_validation(case)

    print_report(case)
    save_case_file(case, output_dir)
    return case


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 intake_form_extractor.py <form.pdf|png|jpg> [output_dir]")
        sys.exit(1)

    # Load API key from .env file
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        print("Error: set OPENAI_API_KEY in your .env file")
        sys.exit(1)

    output_dir = sys.argv[2] if len(sys.argv) > 2 else "case_files"
    process_intake_form(sys.argv[1], api_key=key, output_dir=output_dir)