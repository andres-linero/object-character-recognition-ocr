"""Build order dataframes from document evidence, without fixture or Excel lookups."""
import hashlib
import json
from datetime import date
from pathlib import Path
import re
import subprocess
import tempfile

import pandas as pd
from sqlalchemy import select, func

from . import storage as db
from .etl import upsert
from .page_review import normalized, rental_number, unify_rental_fields

ROOT = Path(__file__).resolve().parents[1]


def extract_fields(page):
    lines = []
    method = 'pdf_text'
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines', []):
            lines.append(dict(text=' '.join(s['text'] for s in line['spans']),
                              x=line['bbox'][0] / page.rect.width,
                              y=line['bbox'][1] / page.rect.height))
    # Redacted samples can have a new vector header over a full scanned page.
    # Header text alone must not suppress local reading of the scanned body.
    scanned_body = bool(page.get_images()) and not any(.28 <= line['y'] < .9 for line in lines)
    if not lines or scanned_body:
        method = 'local_vision'
        binary = ROOT / 'demo_runtime/read-scan'
        source = ROOT / 'scripts/read_scan.swift'
        if not binary.exists() or binary.stat().st_mtime < source.stat().st_mtime:
            binary.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(['swiftc', '-module-cache-path', tempfile.gettempdir() + '/ocr-swift-cache',
                            str(source), '-o', str(binary)], check=True, capture_output=True, timeout=120)
        with tempfile.TemporaryDirectory(prefix='ocr-local-') as directory:
            image = Path(directory) / 'page.png'
            page.get_pixmap(dpi=160).save(image)
            result = subprocess.run([str(binary), str(image)], check=True, capture_output=True, timeout=60)
            lines = json.loads(result.stdout)
    lines.sort(key=lambda line: (round(line['y'], 3), line['x']))
    text = '\n'.join(line['text'] for line in lines)
    header = '\n'.join(line['text'] for line in lines if line['y'] < .24)
    left = [line['text'] for line in lines if .32 <= line['y'] < .45 and line['x'] < .5]
    right = [line['text'] for line in lines if .32 <= line['y'] < .45 and line['x'] >= .5]

    def match(pattern, value=header):
        found = re.search(pattern, value, re.I)
        return found.group(1) if found else None

    pagination = re.search(r'Page\s+(\d+)\s*/\s*(\d+)', text, re.I)
    paper = next((line['text'].title() for line in lines if .24 <= line['y'] < .28), 'Ticket page')
    copy_name = match(r'(White|Yellow|Blue|Pink)\s+copy')
    # Keep shifted OD values in local evidence even when outside the cloud crop.
    work = match(r'\b((?:W|TK|OD)-\d+)\b', '\n'.join(line['text'] for line in lines if line['y'] < .31))
    parent = match(r'\b(RO-\d+)\b')
    customer_order = match(r'(?:^|\n)\s*(?:(?:Customer|Purchase)\s+)?Order\s*(?:No\.?|Number|#)\s*[:#]?\s*([A-Z0-9][A-Z0-9-]+)')
    if customer_order and customer_order.upper().startswith('OD-'):
        customer_order = None  # OD already occupies the order field, never a fourth identifier.
    unsigned = re.search(r'\b(?:not\s+signed|unsigned|no\s+handwritten[^.\n]*signature|no\s+handwriting,\s*signature)\b[^.\n]*', text, re.I)
    signature_lines = [line['text'] for line in lines if re.search(r'\bsignature\b|\bsigned\s+by\b', line['text'], re.I)]
    widgets = list(page.widgets() or [])
    signature_widgets = [w for w in widgets if w.field_type_string == 'Signature']
    filled_signature = any(w.field_value for w in signature_widgets)
    signature_status = ('digital_signature_present' if filled_signature else 'explicitly_unsigned' if unsigned
                        else 'field_present' if signature_widgets or signature_lines else 'not_determined')
    signature_evidence = ('PDF signature field contains a value; validity has not been verified.' if filled_signature
                          else unsigned.group(0) if unsigned else signature_lines[0] if signature_lines
                          else 'Empty PDF signature field' if signature_widgets else None)
    return unify_rental_fields(dict(document_type=paper, copy=copy_name, work_order=work.upper() if work else None, parent_rental_number=parent.upper() if parent else None,
                customer_order_number=customer_order,
                shipment=match(r'Shipment\s*No\.?\s*(?:SO-)?(\d+)'),
                rental_order=match(r'Rental\s*Agreement\s*No\.?\s*((?:RA|RO)-\d+)'),
                customer=left[1] if len(left) > 1 else None,
                address=left[2] if len(left) > 2 else None,
                destination=right[1] if len(right) > 1 else None,
                delivery_address=right[2] if len(right) > 2 else None,
                contact_email=next((line['text'] for line in lines if re.fullmatch(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', line['text'])), None),
                contact_phone=next((line['text'] for line in lines if re.fullmatch(r'\+?[\d ()-]{10,20}', line['text'])), None),
                order_date=match(r'Order\s+date\s*:\s*(\d{4}-\d{2}-\d{2})', text),
                due_date=match(r'Due\s+date\s*:\s*(\d{4}-\d{2}-\d{2})', text),
                signature_document=bool(re.search(r'acknowledg|signature|proof of delivery', paper, re.I)),
                signature_status=signature_status, signature_evidence=signature_evidence,
                extraction_method=method,
                page_number=int(pagination[1]) if pagination else None,
                expected_pages=int(pagination[2]) if pagination else None))


def save_page_fields(store, page_id, fields):
    """Keep local page evidence even when Azure cannot identify or match the page."""
    with store.engine.begin() as connection:
        upsert(connection, db.page_extractions, ['page_id'], dict(page_id=page_id,
            extracted_at=db.utcnow(), method=fields.get('extraction_method', 'local_document'), fields=fields))


def page_field_records(store):
    """Read per-page evidence, falling back to details saved by older successful matches."""
    records = {r['id']: r['payload'] for r in store.rows(select(db.raw_rows).where(db.raw_rows.c.sheet == 'document_fields'))}
    records.update({r['page_id']: r['fields'] for r in store.rows(select(db.page_extractions))})
    return {page_id: unify_rental_fields(fields) for page_id, fields in records.items()}


def observe_rental_context(store, page, page_id, record, identifier, kind='rental_order'):
    """Preserve the identified RO even when the child TK/work order is unreadable."""
    record = unify_rental_fields(record)
    if not record.get('parent_rental_number') or not record.get('customer'):
        raise ValueError('Rental number and customer are required')
    key = {'rental_order': 'parent_rental_number', 'shipment': 'shipment', 'work_order': 'work_order', 'customer_order': 'customer_order_number'}[kind]
    if normalized(identifier, key) != normalized(record.get(key), key):
        raise ValueError('Rental OCR and local rental fields disagree')
    record = pd.DataFrame.from_records([record]).to_dict(orient='records')[0]
    with store.engine.begin() as connection:
        customer = upsert(connection, db.customers, ['source_system', 'external_key'], dict(
            source_system='documents', external_key=hashlib.sha256(record['customer'].casefold().encode()).hexdigest(), name=record['customer']))
        existing = connection.execute(select(db.rental_orders).where(db.rental_orders.c.source_system == 'documents',
            db.rental_orders.c.customer_id == customer, db.rental_orders.c.rental_number == record['parent_rental_number'])).mappings().first()
        address = record.get('address') or (existing['address'] if existing else '')
        if existing and existing['address'] and record.get('address') and normalized(existing['address'], 'address') != normalized(record['address'], 'address'):
            raise ValueError('Conflicting billing address for the same rental order')
        rental = upsert(connection, db.rental_orders, ['source_system', 'customer_id', 'rental_number'], dict(
            source_system='documents', customer_id=customer, rental_number=record['parent_rental_number'], address=address))
        attempt = connection.scalar(select(db.attempts.c.id).where(db.attempts.c.page_id == page_id)
            .order_by(db.attempts.c.started_at.desc(), db.attempts.c.id.desc()).limit(1))
        previous = connection.scalar(select(db.rental_pages.c.rental_id).where(db.rental_pages.c.page_id == page_id))
        if previous and previous != rental:
            raise ValueError('Conflicting rental order for the same source page')
        upsert(connection, db.rental_pages, ['page_id'], dict(page_id=page_id, rental_id=rental, attempt_id=attempt, fields=record))
    return rental


def observe_order(store, page, page_id, fields, identifier, kind):
    """Persist one extracted dataframe row and return its detected order ID."""
    record = pd.DataFrame.from_records([unify_rental_fields(fields)]).to_dict(orient='records')[0]
    if not record.get('work_order') or not record.get('shipment') or not record.get('customer'):
        raise ValueError('Required document fields are missing')
    identifier_field = {'work_order': 'work_order', 'shipment': 'shipment', 'rental_order': 'parent_rental_number', 'customer_order': 'customer_order_number'}[kind]
    if normalized(identifier, identifier_field) != normalized(record[identifier_field], identifier_field):
        raise ValueError('Local fields disagree with the OCR identifier')
    record['shipment'] = normalized(record['shipment'], 'shipment')
    expected, number = record.get('expected_pages'), record.get('page_number')
    if not expected or not number or not 1 <= number <= expected:
        raise ValueError('Printed page numbering is missing or invalid')
    with store.engine.begin() as connection:
        existing = connection.execute(select(db.orders).where(
            db.orders.c.source_system == 'documents', db.orders.c.order_number == record['work_order'])).mappings().first()
        if existing and (existing['shipment_number'] != record['shipment'] or existing['expected_pages'] != expected):
            raise ValueError('Conflicting fields for the same work order')
        if existing:
            customer_name = connection.scalar(select(db.customers.c.name).where(db.customers.c.id == existing['customer_id']))
            if normalized(customer_name, 'customer') != normalized(record['customer'], 'customer'):
                raise ValueError('Conflicting customer for the same work order')
            previous = connection.execute(select(db.raw_rows.c.payload).where(db.raw_rows.c.sheet == 'document_fields',
                db.raw_rows.c.payload['work_order'].as_string() == record['work_order'])).scalars()
            for prior in previous:
                if prior.get('work_order') == record['work_order']:
                    for key in ('address', 'customer_order_number'):
                        if prior.get(key) and record.get(key) and normalized(prior[key], key) != normalized(record[key], key):
                            raise ValueError('Conflicting document fields for the same work order')
                    if rental_number(prior) and rental_number(record) and rental_number(prior) != rental_number(record):
                        raise ValueError('Conflicting rental number for the same work order')
        source = upsert(connection, db.sources, ['sha256'], dict(
            sha256=page['sha256'], name=Path(page['path']).name, kind='pdf', synthetic=True))
        document_id = connection.scalar(select(db.pages.c.document_id).where(db.pages.c.id == page_id))
        upsert(connection, db.runs, ['id'], dict(id=document_id, kind='document_dataframe',
            started_at=db.utcnow(), finished_at=db.utcnow(), status='success', rows_seen=1, rows_loaded=1, rows_rejected=0))
        upsert(connection, db.raw_rows, ['id'], dict(id=page_id, run_id=document_id,
            source_id=source, sheet='document_fields', row_number=number, payload=record))
        count = connection.scalar(select(func.count()).select_from(db.raw_rows).where(db.raw_rows.c.run_id == document_id))
        connection.execute(db.runs.update().where(db.runs.c.id == document_id).values(rows_seen=count, rows_loaded=count))
        customer = upsert(connection, db.customers, ['source_system', 'external_key'], dict(
            source_system='documents', external_key=hashlib.sha256(record['customer'].casefold().encode()).hexdigest(),
            name=record['customer']))
        def parsed_date(value, fallback):
            try:
                return date.fromisoformat(value) if value else fallback
            except (ValueError, TypeError):
                return fallback
        order_id = upsert(connection, db.orders, ['source_system', 'order_number'], dict(
            source_system='documents', order_number=record['work_order'], shipment_number=record['shipment'],
            customer_id=customer, ship_to=record.get('destination') or '', status='OPEN',
            order_date=parsed_date(record.get('order_date'), existing['order_date'] if existing else None),
            deadline=parsed_date(record.get('due_date'), existing['deadline'] if existing else None),
            requested_by='', order_type='RENTAL', expected_pages=expected,
            source_sheet='document_fields', source_id=source))
        if record.get('parent_rental_number'):
            parent = connection.scalar(select(db.rental_pages.c.rental_id).where(db.rental_pages.c.page_id == page_id))
            previous = connection.scalar(select(db.rental_tickets.c.rental_id).where(db.rental_tickets.c.order_id == order_id))
            if previous and previous != parent:
                raise ValueError('A ticket cannot silently move to a different rental order')
            if parent:
                upsert(connection, db.rental_tickets, ['order_id'], dict(order_id=order_id, rental_id=parent))
        return order_id
