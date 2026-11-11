"""Link legacy rental-agreement labels to the same RO using saved page evidence."""
from pathlib import Path
import sys

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ADK_Agentic import storage as db
from ADK_Agentic.document_data import page_field_records, observe_rental_context
from ADK_Agentic.etl import upsert
from ADK_Agentic.page_review import normalized, canonical_rental_number


def link_existing(store):
    fields = page_field_records(store)
    latest = {}
    for attempt in store.rows(select(db.attempts).order_by(db.attempts.c.started_at, db.attempts.c.id)):
        latest[attempt['page_id']] = attempt
    linked = set()
    parents = {r['order_id']: canonical_rental_number(r['rental_number']) for r in store.rows(
        select(db.rental_tickets.c.order_id, db.rental_orders.c.rental_number).select_from(db.rental_tickets.join(db.rental_orders)))}
    for association in store.rows(select(db.associations).where(db.associations.c.method == 'azure_ocr')):
        page_id, order_id = association['page_id'], association['order_id']
        record, attempt = fields.get(page_id, {}), latest.get(page_id, {})
        if not record.get('parent_rental_number') or record.get('rental_number_conflict') or attempt.get('status') != 'success':
            continue
        identifier = attempt.get('identifier')
        kind = next((kind for kind, key in [('rental_order', 'parent_rental_number'), ('work_order', 'work_order'), ('shipment', 'shipment')]
            if record.get(key) and normalized(identifier, key) == normalized(record[key], key)), None)
        if not kind:
            continue
        if order_id in parents and parents[order_id] != record['parent_rental_number']:
            raise ValueError('A ticket has conflicting rental numbers; manual review is required')
        parent = observe_rental_context(store, {}, page_id, record, identifier, kind)
        with store.engine.begin() as connection:
            previous = connection.scalar(select(db.rental_tickets.c.rental_id).where(db.rental_tickets.c.order_id == order_id))
            if previous and previous != parent:
                raise ValueError('A ticket has conflicting rental numbers; manual review is required')
            upsert(connection, db.rental_tickets, ['order_id'], dict(order_id=order_id, rental_id=parent))
        linked.add(order_id)
    return len(linked)


if __name__ == '__main__':
    store = db.Store(db.sqlite_url(ROOT / 'demo_runtime/workspace.sqlite'))
    try:
        store.migrate()
        print(f'{link_existing(store)} existing tickets linked to their printed rental number. No OCR calls or page assignments changed.')
    finally:
        store.close()
