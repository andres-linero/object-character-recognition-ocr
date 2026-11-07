"""Explicit paid Azure OCR batch; never invoked by the synthetic preview."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
from ADK_Agentic.storage import Store
from ADK_Agentic.processing import process_batch


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--source-system", default="tracker")
    args = parser.parse_args()
    for key in ("DATABASE_URL", "AZURE_DOC_INTEL_ENDPOINT", "AZURE_DOC_INTEL_KEY"):
        if not os.getenv(key):
            parser.error(f"Configure {key} in your local .env first")
    store = Store(os.environ["DATABASE_URL"])
    try:
        store.migrate()
        print(json.dumps(process_batch(store, args.limit, args.retry_errors, args.source_system), indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    main()
