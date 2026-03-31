"""
extractor.py — PDF text extraction + GPT field parsing.

Two-stage pipeline:
  1. extract_text_from_pdf()  →  raw text string
  2. extract_fields_with_gpt() →  structured dict

To add a new field:
  - Add it to FIELD_DESCRIPTIONS below
  - Add the column to database.py init_db()
  - That's it. GPT will start extracting it automatically.
"""

import os
import json
import tempfile
import fitz          # PyMuPDF
import pytesseract
from PIL import Image
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ── FIELD DEFINITIONS ─────────────────────────────────────────────────────
# Add new fields here — GPT will extract them automatically.
FIELD_DESCRIPTIONS = {
    "client_name":           "Full legal name of the client",
    "client_email":          "Client email address",
    "client_phone":          "Client phone number",
    "client_address":        "Client mailing or home address",
    "case_type":             "Type of legal matter (e.g. personal injury, family law, immigration, criminal defense)",
    "incident_date":         "Date of the incident or event giving rise to the case (ISO format if possible)",
    "filing_date":           "Date any legal filing was made or is due (ISO format if possible)",
    "incident_description":  "Summary of what happened — the facts of the case as described by the client",
    "injury_severity":       "Severity of injuries or damages (e.g. minor, moderate, severe, none)",
    "opposing_party":        "Name of the opposing party, defendant, or respondent",
    "opposing_counsel":      "Name of opposing attorney or law firm if known",
    "insurance_info":        "Insurance carrier, policy number, or claim number if mentioned",
    "employer_info":         "Client's employer name and role if mentioned",
    "income_details":        "Income or wage information if mentioned",
    "prior_legal_rep":       "Whether client has had prior legal representation for this matter",
    "referral_source":       "How the client heard about or was referred to the firm",
    "signature_present":     "Whether a signature is present on the form (yes/no)",
    "consent_given":         "Whether consent or authorization is indicated (yes/no)",
}

SYSTEM_PROMPT = f"""
You are a legal intake assistant. Extract structured information from legal intake form text.

Return ONLY a valid JSON object with these exact keys. 
If a field is not found or unclear, use null.
Do not include any explanation, markdown, or text outside the JSON.

Fields to extract:
{json.dumps(FIELD_DESCRIPTIONS, indent=2)}
"""


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """
    Extract text from PDF bytes.
    First tries PyMuPDF (fast, works on digital PDFs).
    Falls back to pytesseract OCR for scanned/image PDFs.
    """
    text = ""

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        doc = fitz.open(tmp_path)
        for page in doc:
            text += page.get_text()
        doc.close()

        # If PyMuPDF got almost nothing, the PDF is likely scanned — use OCR
        if len(text.strip()) < 100:
            print("[Extractor] Digital extraction yielded little text — falling back to OCR")
            text = _ocr_pdf(tmp_path)

    finally:
        os.unlink(tmp_path)

    return text.strip()


def _ocr_pdf(pdf_path: str) -> str:
    """Rasterize each PDF page and run pytesseract OCR."""
    doc = fitz.open(pdf_path)
    full_text = ""

    for page_num, page in enumerate(doc):
        mat = fitz.Matrix(2.0, 2.0)  # 2x scale = ~144 DPI for better OCR accuracy
        pix = page.get_pixmap(matrix=mat)

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as img_tmp:
            pix.save(img_tmp.name)
            img_path = img_tmp.name

        try:
            img = Image.open(img_path)
            page_text = pytesseract.image_to_string(img)
            full_text += f"\n--- Page {page_num + 1} ---\n{page_text}"
        finally:
            os.unlink(img_path)

    doc.close()
    return full_text


def extract_fields_with_gpt(raw_text: str) -> tuple[dict, str]:
    """
    Send extracted PDF text to GPT-4o and get structured fields back.
    Returns (fields_dict, raw_gpt_response_string).
    """
    if not raw_text:
        return {k: None for k in FIELD_DESCRIPTIONS}, ""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": f"Extract fields from this intake form:\n\n{raw_text[:12000]}"}
            ]
        )

        raw_gpt = response.choices[0].message.content.strip()

        # Strip markdown fences if GPT wraps in ```json
        if raw_gpt.startswith("```"):
            raw_gpt = raw_gpt.split("```")[1]
            if raw_gpt.startswith("json"):
                raw_gpt = raw_gpt[4:]

        fields = json.loads(raw_gpt)

        # Ensure all expected keys are present
        for key in FIELD_DESCRIPTIONS:
            fields.setdefault(key, None)

        return fields, raw_gpt

    except json.JSONDecodeError as e:
        print(f"[Extractor] JSON parse error: {e}")
        return {k: None for k in FIELD_DESCRIPTIONS}, raw_gpt

    except Exception as e:
        print(f"[Extractor] GPT extraction error: {e}")
        return {k: None for k in FIELD_DESCRIPTIONS}, str(e)


def process_pdf(pdf_bytes: bytes) -> tuple[dict, str, str]:
    """
    Full pipeline: bytes → raw text → structured fields.
    Returns (fields_dict, raw_text, raw_gpt_response).
    """
    raw_text = extract_text_from_pdf(pdf_bytes)
    fields, raw_gpt = extract_fields_with_gpt(raw_text)
    return fields, raw_text, raw_gpt
