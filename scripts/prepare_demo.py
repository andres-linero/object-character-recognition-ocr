"""Prepare isolated local demo storage from the project's synthetic datasets."""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ADK_Agentic.storage import Store, sqlite_url
from ADK_Agentic.etl import ingest_tracker, register_manifest

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "demo_runtime" / "demo.sqlite"


def prepare():
    manifests = [ROOT / "demo_data/manifest.json", ROOT / "demo_batches/batch_02/manifest.json",
                 ROOT / "demo_batches/batch_03/manifest.json"]
    available = [p for p in manifests if p.exists()]
    if not available:
        raise ValueError("Generate demo_data first with scripts/create_demo_data.py")
    # Validate ownership before importing tracker rows into the unauthenticated demo.
    for manifest in available:
        data = json.loads(manifest.read_text())
        if data.get("synthetic") is not True or data.get("generator") != "ocr-synthetic-demo-v1":
            raise ValueError("Demo accepts only generator-owned synthetic datasets")
    DATABASE.parent.mkdir(exist_ok=True)
    store = Store(sqlite_url(DATABASE))
    try:
        store.migrate()
        for manifest in available:
            result = ingest_tracker(store, manifest.parent / "orders.xlsx", "demo", synthetic=True)
            if result["rows_rejected"]:
                raise ValueError("Synthetic tracker contains rejected rows")
            register_manifest(store, manifest, "demo")
        print(json.dumps(store.counts(), indent=2))
        return DATABASE
    finally:
        store.close()


if __name__ == "__main__":
    print("Demo database:", prepare())
