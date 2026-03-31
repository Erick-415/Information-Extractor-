"""
app.py — Flask dashboard for the lawyer.

Routes:
  GET  /              → all cases, filterable by status
  GET  /case/<number> → full case detail
  POST /case/<number>/status → update status + notes
"""

import os
from flask import Flask, render_template, request, redirect, url_for, jsonify
from dotenv import load_dotenv
from database import init_db, get_all_cases, get_case, update_case_status

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")

STATUSES = ["new", "under_review", "consultation_scheduled", "retained", "declined", "closed"]


@app.before_request
def setup():
    init_db()


@app.route("/")
def index():
    status_filter = request.args.get("status", "all")
    cases = get_all_cases()

    if status_filter != "all":
        cases = [c for c in cases if c["status"] == status_filter]

    # Count by status for the nav badges
    all_cases = get_all_cases()
    counts = {s: sum(1 for c in all_cases if c["status"] == s) for s in STATUSES}
    counts["all"] = len(all_cases)

    return render_template("index.html",
        cases=cases,
        statuses=STATUSES,
        current_filter=status_filter,
        counts=counts
    )


@app.route("/case/<case_number>")
def case_detail(case_number):
    case = get_case(case_number)
    if not case:
        return "Case not found", 404
    return render_template("case_detail.html", case=case, statuses=STATUSES)


@app.route("/case/<case_number>/status", methods=["POST"])
def update_status(case_number):
    new_status = request.form.get("status")
    notes      = request.form.get("notes", "").strip()

    if new_status not in STATUSES:
        return jsonify({"error": "Invalid status"}), 400

    update_case_status(case_number, new_status, notes or None)
    return redirect(url_for("case_detail", case_number=case_number))


@app.route("/api/cases")
def api_cases():
    """JSON endpoint — useful for future integrations."""
    return jsonify(get_all_cases())


@app.route("/api/case/<case_number>")
def api_case(case_number):
    case = get_case(case_number)
    if not case:
        return jsonify({"error": "Not found"}), 404
    return jsonify(case)


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5050)
