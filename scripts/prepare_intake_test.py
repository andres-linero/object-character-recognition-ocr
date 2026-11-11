"""Stage the three generated scan PDFs; optionally run at most 18 paid Azure page calls."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import dotenv_values
from sqlalchemy import select
from ADK_Agentic import storage as db
from ADK_Agentic.etl import ingest_tracker, register_manifest
from ADK_Agentic.processing import process_page

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--process", action="store_true", help="Use configured Azure credentials; incurs charges")
    args = parser.parse_args()
    dataset = ROOT / "demo_batches/intake_test_03"
    manifest = json.loads((dataset / "manifest.json").read_text())
    if manifest.get("generator") != "ocr-synthetic-demo-v1" or manifest.get("synthetic") is not True or manifest["count"] != 3 or manifest.get("total_pages") != 18:
        raise ValueError("Generate the three-ticket synthetic intake dataset first")
    store = db.Store(db.sqlite_url(ROOT / "demo_runtime/intake_test.sqlite"))
    try:
        store.migrate()
        ingest_tracker(store, dataset / "orders.xlsx", "demo", synthetic=True)
        register_manifest(store, dataset / "manifest.json", "demo")
        if args.process:
            values = dotenv_values(ROOT / ".env")
            for name in ("AZURE_DOC_INTEL_ENDPOINT", "AZURE_DOC_INTEL_KEY"):
                value = values.get(name) or os.getenv(name)
                if not value:
                    raise ValueError(f"Configure {name}")
                os.environ[name] = value
            history = {}
            for row in store.rows(select(db.attempts).order_by(db.attempts.c.started_at)):
                history[row["page_id"]] = row
            failures = 0
            for page in store.rows(select(db.pages).order_by(db.pages.c.document_id, db.pages.c.page_number)):
                if page["id"] in history:
                    continue
                result = process_page(store, page["id"], "demo")
                print(json.dumps({"page_id": page["id"], **result}), flush=True)
                failures = failures + 1 if result["status"] != "success" else 0
                if failures >= 3 or result.get("error_code") in {"HTTP401", "HTTP403", "HTTP404"}:
                    print("Stopped after provider or matching failures; inspect OCR activity.", flush=True)
                    break
        print(json.dumps(store.counts()), flush=True)
    finally:
        store.close()


if __name__ == "__main__":
    main()
