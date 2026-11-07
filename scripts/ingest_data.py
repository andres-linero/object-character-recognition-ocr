"""Run versioned migrations and tracker ETL against an explicit database URL."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
from ADK_Agentic.storage import Store
from ADK_Agentic.etl import ingest_tracker, register_manifest
from ADK_Agentic.processing import register_pdf


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--tracker", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--source-system", default="tracker")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("Set DATABASE_URL locally or pass --database-url")
    store = Store(args.database_url)
    try:
        store.migrate()
        if args.tracker:
            print(json.dumps(ingest_tracker(store, args.tracker, args.source_system)))
        if args.manifest:
            print(json.dumps({"expected_pages_registered": register_manifest(store, args.manifest, args.source_system)}))
        if args.pdf:
            print(json.dumps({"document_id": register_pdf(store, args.pdf)}))
        print(json.dumps(store.counts()))
    finally:
        store.close()


if __name__ == "__main__":
    main()
