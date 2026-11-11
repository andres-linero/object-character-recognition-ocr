"""Load fictional tracker records into the single live workspace, without scanning PDFs."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ADK_Agentic import storage as db
from ADK_Agentic.etl import ingest_tracker

ROOT = Path(__file__).resolve().parents[1]


def prepare():
    database = ROOT / 'demo_runtime/workspace.sqlite'
    database.parent.mkdir(exist_ok=True)
    store = db.Store(db.sqlite_url(database))
    try:
        store.migrate()
        manifests = [ROOT / 'demo_data/manifest.json', *sorted(ROOT.glob('demo_batches/*/manifest.json'))]
        for manifest in manifests:
            data = json.loads(manifest.read_text()) if manifest.exists() else {}
            if data.get('generator') == 'ocr-synthetic-demo-v1' and data.get('synthetic') is True:
                ingest_tracker(store, manifest.parent / 'orders.xlsx', 'demo', synthetic=True)
        print(json.dumps(store.counts()))
    finally:
        store.close()
    return database


if __name__ == '__main__':
    prepare()
