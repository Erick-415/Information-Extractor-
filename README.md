# Legal Intake Processor

Automated pipeline that watches a Gmail inbox for intake PDFs, extracts structured case data using GPT-4o, saves to a database, sends the client a confirmation email, and surfaces everything in a web dashboard for the lawyer.

---

## Flow

```
New email with PDF attachment
        ↓
Gmail API polls inbox (every 60s or on-demand)
        ↓
PyMuPDF extracts text (falls back to pytesseract OCR if scanned)
        ↓
GPT-4o extracts structured fields → JSON
        ↓
SQLite saves case (auto case# + matter#)
        ↓
Gmail API sends summary confirmation to client
        ↓
Dashboard flags case as "new" for lawyer review
```

---

## Project Structure

```
legal-intake/
├── app.py              # Flask dashboard (lawyer UI)
├── processor.py        # Main pipeline — run this to process emails
├── extractor.py        # PDF text extraction + GPT field parsing
├── gmail_client.py     # Gmail API: polling + sending
├── database.py         # SQLite schema + queries
├── templates/
│   ├── index.html      # Case list dashboard
│   └── case_detail.html# Individual case view
├── requirements.txt
├── .env.example        # Copy to .env and fill in
└── README.md
```

---

## Setup

### 1. Install dependencies

```bash
cd legal-intake
pip install -r requirements.txt
```

For OCR support (scanned PDFs), also install Tesseract:
```bash
# macOS
brew install tesseract

# Ubuntu/Debian
sudo apt install tesseract-ocr
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:
- `OPENAI_API_KEY` — your OpenAI key
- `INTAKE_EMAIL` — the Gmail address that receives intake forms
- `FLASK_SECRET_KEY` — any random string

### 3. Set up Gmail API (one-time)

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or use an existing one)
3. Enable the **Gmail API**
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
5. Choose **Desktop App**, download the JSON file
6. Rename it to `credentials.json` and place it in the `legal-intake/` folder
7. Run the auth setup once:

```bash
python gmail_client.py
```

A browser window will open — log in with the intake Gmail account and approve access.
A `token.json` file is saved. You won't need to do this again.

---

## Running

### Process emails once (manual / cron)

```bash
python processor.py --once
```

### Watch mode (continuous daemon)

```bash
python processor.py --watch
```

Polls every 60 seconds by default. Change `POLL_INTERVAL` in `.env`.

### Launch dashboard

```bash
python app.py
```

Open [http://localhost:5050](http://localhost:5050) in your browser.

---

## Adding New Fields

1. Open `extractor.py`
2. Add your field to `FIELD_DESCRIPTIONS`:
   ```python
   "your_new_field": "Description of what to extract",
   ```
3. Open `database.py`
4. Add a column to the `CREATE TABLE` statement in `init_db()`:
   ```sql
   your_new_field  TEXT,
   ```
5. Add the key to the `insert_case()` field list
6. (Optional) Add it to `case_detail.html` to display it

That's it — GPT will start extracting the new field automatically.

---

## Case Statuses

Cases move through these statuses (update from the dashboard):

| Status | Meaning |
|--------|---------|
| `new` | Just received, needs lawyer review |
| `under_review` | Lawyer is reviewing |
| `consultation_scheduled` | Initial consult booked |
| `retained` | Client retained the firm |
| `declined` | Case declined |
| `closed` | Matter closed |

---

## API Endpoints

The Flask app also exposes JSON endpoints for future integrations:

```
GET /api/cases          → all cases as JSON array
GET /api/case/<number>  → single case as JSON
```

---

## Notes

- Processed emails are automatically marked as read so they aren't re-ingested
- Raw PDF text and raw GPT response are stored in the DB for debugging and re-extraction
- SQLite is a local file (`cases.db`) — to migrate to PostgreSQL, swap the connection in `database.py`
- The `credentials.json` and `token.json` files contain sensitive OAuth data — add them to `.gitignore`
