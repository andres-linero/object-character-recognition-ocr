"""Initialize an empty document-driven workspace. Never preload tracker rows."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ADK_Agentic import storage as db

ROOT = Path(__file__).resolve().parents[1]


def prepare():
    database = ROOT / 'demo_runtime/workspace.sqlite'
    database.parent.mkdir(exist_ok=True)
    store = db.Store(db.sqlite_url(database))
    try:
        store.migrate()
        print(json.dumps(store.counts()))
    finally:
        store.close()
    return database


if __name__ == '__main__':
    prepare()
