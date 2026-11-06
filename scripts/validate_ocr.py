"""Stage two synthetic batches and verify live Azure OCR against page ground truth.

Run from the OCR repository with --limit 1 for a smoke test, then --limit 120.
Only cropped synthetic headers are sent. Credentials and raw OCR text are never reported.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values
from sqlalchemy import select
from ADK_Agentic import storage as db
from ADK_Agentic.etl import checksum, ingest_tracker, upsert
from ADK_Agentic.processing import process_page, register_pdf

INPUT = ROOT / "demo_batches/ocr_validation/incoming_scans"
RUNTIME = ROOT / "demo_runtime"
DATABASE = RUNTIME / "ocr_validation.sqlite"
REPORT = RUNTIME / "ocr_validation_report.json"


def prepare():
    INPUT.mkdir(parents=True, exist_ok=True)
    RUNTIME.mkdir(exist_ok=True)
    store = db.Store(db.sqlite_url(DATABASE))
    store.migrate()
    rows, fields, batches = [], None, []
    for number in (2, 3):
        folder = ROOT / f"demo_batches/batch_{number:02d}"
        manifest = json.loads((folder / "manifest.json").read_text())
        if manifest.get("generator") != "ocr-synthetic-demo-v1" or manifest.get("synthetic") is not True:
            raise ValueError("Only the generated synthetic batches may be submitted by this validator")
        source = ROOT / f"demo_batches/batch_{number:02d}_60_pages.pdf"
        target = INPUT / source.name
        if target.exists() and checksum(target) != checksum(source):
            raise ValueError("Existing staged PDF differs; refusing to overwrite")
        if not target.exists():
            shutil.copy2(source, target)
        with (folder / "orders.csv").open(newline="") as handle:
            reader = csv.DictReader(handle)
            if fields is not None and fields != reader.fieldnames:
                raise ValueError("Tracker schemas differ")
            fields = reader.fieldnames
            rows.extend(reader)
        expectations = [dict(shipment=ticket["shipment"], copy=page["copy"], paper=page["document_type"])
                        for ticket in manifest["tickets"] for page in ticket["pages"]]
        batches.append((target, expectations))
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    tracker = INPUT.parent / "tracker.csv"
    tracker.write_text(buffer.getvalue())
    outcome = ingest_tracker(store, tracker, "demo", synthetic=True)
    if outcome["rows_rejected"]:
        raise ValueError("Tracker validation rejected rows")
    todo = []
    for pdf, expectations in batches:
        document_id = register_pdf(store, pdf, synthetic=True)
        with store.engine.begin() as connection:
            total = connection.scalar(select(db.documents.c.page_count).where(db.documents.c.id == document_id))
            if total != len(expectations):
                raise ValueError("Batch PDF and expected page counts disagree")
            for number, expectation in enumerate(expectations, 1):
                page_id = connection.scalar(select(db.pages.c.id).where(
                    db.pages.c.document_id == document_id, db.pages.c.page_number == number))
                order_id = connection.scalar(select(db.orders.c.id).where(
                    db.orders.c.source_system == "demo", db.orders.c.shipment_number == expectation["shipment"]))
                upsert(connection, db.associations, ["order_id", "page_id", "method"],
                    dict(order_id=order_id, page_id=page_id, method="synthetic_manifest"))
                todo.append(dict(page_id=page_id, document=pdf.name, page=number, **expectation))
    return store, todo


def write_report(todo, results):
    records = []
    for item in todo:
        actual = results.get(item["page_id"])
        records.append(dict(document=item["document"], page=item["page"], paper=item["paper"], copy=item["copy"],
            expected=item["shipment"], actual=actual.get("identifier") if actual else None,
            outcome=("passed" if actual["status"] == "success" and actual["identifier"] == item["shipment"] else
                     "error" if actual["status"] == "error" else "mismatch") if actual else "pending",
            error_code=actual.get("error_code") if actual else None))
    counts = {name: sum(row["outcome"] == name for row in records) for name in ("passed", "mismatch", "error", "pending")}
    report = dict(updated_at=datetime.now(timezone.utc).isoformat(), provider="Azure Document Intelligence prebuilt-read",
                  synthetic=True, expected_tickets=len({p["shipment"] for p in todo}), total_pages=len(todo), **counts, pages=records)
    temporary = REPORT.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(REPORT)
    csv_report = REPORT.with_suffix(".csv")
    csv_temporary = REPORT.with_suffix(".csv.tmp")
    with csv_temporary.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    csv_temporary.replace(csv_report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=1, help="Max new page attempts; first page must pass before proceeding")
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 120:
        parser.error("limit must be 1 through 120")
    if not args.prepare_only:
        values = dotenv_values(ROOT / ".env")
        for name in ("AZURE_DOC_INTEL_ENDPOINT", "AZURE_DOC_INTEL_KEY"):
            value = (values.get(name) or os.getenv(name) or "").strip()
            if not value:
                parser.error(f"Configure {name} in local .env")
            os.environ[name] = value
    store, todo = prepare()
    try:
        print(f"Staged {len(todo)} pages /20 tickets. Tracker and validation DB ready.", flush=True)
        results = {row["page_id"]: row for row in store.rows(select(db.attempts).order_by(db.attempts.c.started_at))}
        report = write_report(todo, results)
        if args.prepare_only:
            return 0
        attempted = consecutive_errors = 0
        for index, item in enumerate(todo):
            previous = results.get(item["page_id"])
            needs_attempt = not previous or (args.retry_errors and previous["status"] == "error")
            if needs_attempt and attempted >= args.limit:
                break
            if needs_attempt:
                result = process_page(store, item["page_id"], source_system="demo")
                results[item["page_id"]] = result
                attempted += 1
                report = write_report(todo, results)
                consecutive_errors = consecutive_errors + 1 if result["status"] == "error" else 0
                if attempted == 1 or attempted % 5 == 0 or index == len(todo) - 1:
                    print(json.dumps({key: report[key] for key in ("passed", "mismatch", "error", "pending")}), flush=True)
                if result.get("error_code") in ("HTTP401", "HTTP403", "HTTP404") or consecutive_errors >= 3:
                    print("Stopped after provider/access failures; inspect safe error codes in the local report.", flush=True)
                    break
                time.sleep(1.0)
            first = results.get(todo[0]["page_id"])
            if index == 0 and (not first or first["status"] != "success" or first["identifier"] != item["shipment"]):
                print("Smoke test did not pass; remaining pages were not submitted.", flush=True)
                break
        report = write_report(todo, results)
        print(json.dumps({key: report[key] for key in ("total_pages", "passed", "mismatch", "error", "pending")}), flush=True)
        print("Report:", REPORT, flush=True)
        return 1 if report["error"] or report["mismatch"] else 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
