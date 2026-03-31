"""
gmail_client.py — Gmail integration.

Two jobs:
  1. poll_for_intake_emails() — find unread emails with PDF attachments
  2. send_summary_email()     — reply to client with case summary + flag for lawyer

Setup (one-time):
  1. Go to console.cloud.google.com → New Project
  2. Enable Gmail API
  3. Create OAuth 2.0 credentials (Desktop App)
  4. Download as credentials.json → place in project root
  5. Run `python gmail_client.py` once to complete OAuth flow in browser
     Token is saved to token.json — no browser needed after that.
"""

import os
import base64
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",  # needed to mark as read
]

CREDENTIALS_PATH = os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")
TOKEN_PATH        = os.getenv("GMAIL_TOKEN_PATH", "token.json")
INTAKE_EMAIL      = os.getenv("INTAKE_EMAIL", "")


def get_gmail_service():
    """Authenticate and return Gmail API service. Handles token refresh automatically."""
    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_PATH):
                raise FileNotFoundError(
                    f"credentials.json not found at {CREDENTIALS_PATH}.\n"
                    "Download it from Google Cloud Console → APIs & Services → Credentials."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def poll_for_intake_emails() -> list[dict]:
    """
    Fetch unread emails with PDF attachments.
    Returns list of dicts: { message_id, sender_email, sender_name, subject, pdf_bytes }
    Marks processed emails as read automatically.
    """
    service = get_gmail_service()
    results = []

    # Search for unread emails with attachments
    query = "is:unread has:attachment filename:pdf"
    response = service.users().messages().list(userId="me", q=query).execute()
    messages = response.get("messages", [])

    if not messages:
        print("[Gmail] No new intake emails found.")
        return results

    print(f"[Gmail] Found {len(messages)} unread email(s) with PDF attachments.")

    for msg_ref in messages:
        msg_id = msg_ref["id"]
        msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()

        sender_email, sender_name, subject = _parse_headers(msg)
        pdf_list = _extract_pdf_attachments(service, msg_id, msg)

        if not pdf_list:
            continue

        for pdf_name, pdf_bytes in pdf_list:
            results.append({
                "message_id":   msg_id,
                "sender_email": sender_email,
                "sender_name":  sender_name,
                "subject":      subject,
                "pdf_name":     pdf_name,
                "pdf_bytes":    pdf_bytes,
            })

        # Mark as read so we don't process it again
        service.users().messages().modify(
            userId="me",
            id=msg_id,
            body={"removeLabelIds": ["UNREAD"]}
        ).execute()

    return results


def _parse_headers(msg: dict) -> tuple[str, str, str]:
    headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
    raw_from = headers.get("From", "")
    subject  = headers.get("Subject", "(No Subject)")

    # Parse "Name <email>" format
    if "<" in raw_from:
        name  = raw_from.split("<")[0].strip().strip('"')
        email = raw_from.split("<")[1].rstrip(">").strip()
    else:
        name  = ""
        email = raw_from.strip()

    return email, name, subject


def _extract_pdf_attachments(service, msg_id: str, msg: dict) -> list[tuple[str, bytes]]:
    """Recursively find and download PDF attachments from message parts."""
    pdfs = []

    def walk_parts(parts):
        for part in parts:
            if part.get("parts"):
                walk_parts(part["parts"])
            mime = part.get("mimeType", "")
            filename = part.get("filename", "")
            if mime == "application/pdf" or filename.lower().endswith(".pdf"):
                attachment_id = part["body"].get("attachmentId")
                if attachment_id:
                    attachment = service.users().messages().attachments().get(
                        userId="me", messageId=msg_id, id=attachment_id
                    ).execute()
                    data = base64.urlsafe_b64decode(attachment["data"])
                    pdfs.append((filename or "intake.pdf", data))

    parts = msg["payload"].get("parts", [])
    walk_parts(parts)
    return pdfs


def send_summary_email(
    to_email: str,
    client_name: str,
    case_number: str,
    matter_number: str,
    fields: dict,
    firm_name: str = "Our Law Firm"
) -> bool:
    """
    Send a confirmation + summary email back to the client.
    Returns True on success.
    """
    service = get_gmail_service()

    subject = f"[{case_number}] Your Intake Has Been Received — {firm_name}"

    # Build a human-readable summary of extracted fields
    field_labels = {
        "case_type":            "Case Type",
        "incident_date":        "Incident Date",
        "incident_description": "Incident Summary",
        "injury_severity":      "Injury Severity",
        "opposing_party":       "Opposing Party",
        "insurance_info":       "Insurance Info",
    }

    summary_lines = []
    for key, label in field_labels.items():
        val = fields.get(key)
        if val:
            summary_lines.append(f"  • {label}: {val}")

    summary_block = "\n".join(summary_lines) if summary_lines else "  (Fields will be reviewed by our team)"

    body = f"""Dear {client_name or 'Client'},

Thank you for submitting your intake form. We have received your information and a member of our team will be in touch to schedule your initial consultation.

─────────────────────────────────
CASE REFERENCE NUMBERS
─────────────────────────────────
Case Number:          {case_number}
Client Matter Number: {matter_number}

Please save these numbers — you will need them for all future correspondence.

─────────────────────────────────
INFORMATION WE RECEIVED
─────────────────────────────────
{summary_block}

─────────────────────────────────

If any of the above information looks incorrect or if you have additional details to share, please reply to this email.

Our team will review your intake and reach out within 1–2 business days to schedule a consultation.

Sincerely,
{firm_name}

───
This is an automated confirmation email. Please do not reply with sensitive documents — use our secure portal or contact us directly.
"""

    message = MIMEMultipart()
    message["to"]      = to_email
    message["subject"] = subject
    message.attach(MIMEText(body, "plain"))

    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(
        userId="me",
        body={"raw": encoded}
    ).execute()

    print(f"[Gmail] Summary email sent to {to_email} for {case_number}")
    return True


# ── Run this file directly once to complete OAuth setup ───────────────────
if __name__ == "__main__":
    print("Authenticating with Gmail...")
    svc = get_gmail_service()
    profile = svc.users().getProfile(userId="me").execute()
    print(f"Connected as: {profile['emailAddress']}")
    print("OAuth setup complete. token.json has been saved.")
