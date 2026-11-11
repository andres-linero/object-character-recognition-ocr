"""Read existing scan details locally, without retrying Azure or changing matches."""
import argparse
from pathlib import Path
import sys

import fitz
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ADK_Agentic import storage as db
from ADK_Agentic.document_data import extract_fields, save_page_fields
from ADK_Agentic.etl import checksum


def extract_existing(store, roots, refresh=False):
    existing = {p['page_id'] for p in store.rows(select(db.page_extractions.c.page_id))}
    count = 0
    for document in store.rows(select(db.documents).where(db.documents.c.synthetic.is_(True))):
        path = Path(document['path']).resolve()
        if not any(path.is_relative_to(Path(root).resolve()) for root in roots):
            raise ValueError('Document is outside the allowed source directories')
        selected = store.rows(select(db.pages).where(db.pages.c.document_id == document['id']).order_by(db.pages.c.page_number))
        selected = [p for p in selected if refresh or p['id'] not in existing]
        if not selected:
            continue
        if checksum(path) != document['sha256']:
            raise ValueError('Document changed after registration')
        with fitz.open(path) as pdf:
            fields = [(page['id'], extract_fields(pdf[page['page_number'] - 1])) for page in selected]
        if checksum(path) != document['sha256']:
            raise ValueError('Document changed during local extraction')
        for page_id, record in fields:
            save_page_fields(store, page_id, record)
            count += 1
        print(f'Extracted {len(fields)} pages locally from {path.name}', flush=True)
    return count


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT / 'demo_runtime/workspace.sqlite')
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error('Workspace database does not exist')
    store = db.Store(db.sqlite_url(args.database))
    try:
        store.migrate()
        count = extract_existing(store, [ROOT / 'Scans', ROOT / 'demo_data', ROOT / 'demo_batches'], args.refresh)
        print(f'{count} pages updated. OCR attempts, order matches and approvals unchanged.')
    finally:
        store.close()
