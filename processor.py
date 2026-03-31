"""
processor.py — Main intake pipeline.

Run once:   python processor.py --once
Run daemon: python processor.py --watch   (polls every POLL_INTERVAL seconds)

Flow:
  poll Gmail → extract PDF text → GPT field extraction →
  insert DB (case# + matter#) → send client summary email
"""

import os
import time
import argparse
from dotenv import load_dotenv

from database    import init_db, insert_case
from extractor   import process_pdf
from gmail_client import poll_for_intake_emails, send_summary_email

load_dotenv()

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 60))
FIRM_NAME     = os.getenv("FIRM_NAME", "Our Law Firm")


def process_one_email(email_data: dict) -> dict | None:
    """
    Full pipeline for a single email.
    Returns the saved case dict or None on failure.
    """
    sender_email = email_data["sender_email"]
    sender_name  = email_data["sender_name"]
    pdf_name     = email_data["pdf_name"]
    pdf_bytes    = email_data["pdf_bytes"]

    print(f"\n[Pipeline] Processing: {pdf_name} from {sender_email}")

    # ── Step 1: Extract PDF text ──────────────────────────────────────────
    try:
        fields, raw_text, raw_gpt = process_pdf(pdf_bytes)
        print(f"[Pipeline] Extracted {len(raw_text)} chars from PDF")
    except Exception as e:
        print(f"[Pipeline] PDF extraction failed: {e}")
        return None

    # ── Step 2: Use sender email if GPT didn't find one ───────────────────
    if not fields.get("client_email"):
        fields["client_email"] = sender_email
    if not fields.get("client_name") and sender_name:
        fields["client_name"] = sender_name

    # ── Step 3: Save to database ──────────────────────────────────────────
    try:
        case = insert_case(
            fields=fields,
            source_email=sender_email,
            raw_text=raw_text,
            raw_gpt=raw_gpt,
        )
        print(f"[Pipeline] Case saved: {case['case_number']} / {case['client_matter_number']}")
    except Exception as e:
        print(f"[Pipeline] DB insert failed: {e}")
        return None

    # ── Step 4: Send summary email to client ──────────────────────────────
    try:
        send_summary_email(
            to_email=fields["client_email"],
            client_name=fields.get("client_name", "Client"),
            case_number=case["case_number"],
            matter_number=case["client_matter_number"],
            fields=fields,
            firm_name=FIRM_NAME,
        )
    except Exception as e:
        print(f"[Pipeline] Email send failed (case still saved): {e}")

    print(f"[Pipeline] Done — {case['case_number']} flagged in dashboard for review.")
    return case


def run_once():
    """Poll Gmail once and process all new intake emails."""
    init_db()
    emails = poll_for_intake_emails()

    if not emails:
        print("[Pipeline] No new intakes to process.")
        return

    processed = 0
    for email_data in emails:
        result = process_one_email(email_data)
        if result:
            processed += 1

    print(f"\n[Pipeline] Done. Processed {processed}/{len(emails)} emails.")


def run_watch():
    """Daemon mode — poll continuously on POLL_INTERVAL."""
    init_db()
    print(f"[Pipeline] Watching for intake emails every {POLL_INTERVAL}s. Ctrl+C to stop.\n")

    while True:
        try:
            emails = poll_for_intake_emails()
            for email_data in emails:
                process_one_email(email_data)
        except KeyboardInterrupt:
            print("\n[Pipeline] Stopped.")
            break
        except Exception as e:
            print(f"[Pipeline] Error during poll cycle: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Legal intake email processor")
    parser.add_argument("--once",  action="store_true", help="Run one poll cycle and exit")
    parser.add_argument("--watch", action="store_true", help="Run continuously (daemon mode)")
    args = parser.parse_args()

    if args.watch:
        run_watch()
    else:
        run_once()  # default
