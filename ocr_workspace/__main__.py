"""Start Order Scanner with ``uv run --locked python -m ocr_workspace``."""
from pathlib import Path

import uvicorn

from . import storage as db


def main():
    root = Path(__file__).resolve().parents[1]
    database = root / "demo_runtime/workspace.sqlite"
    if not database.exists():
        database.parent.mkdir(parents=True, exist_ok=True)
        store = db.Store(db.sqlite_url(database))
        try:
            store.migrate()
        finally:
            store.close()
    uvicorn.run("ocr_workspace.web_api:app", host="127.0.0.1", port=8700,
                timeout_graceful_shutdown=5)


if __name__ == "__main__":
    main()
