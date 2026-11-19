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
from .page_review import normalized, order_type, parent_type

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
    # Read the page's own order from the full local page, so a number printed
    # below the cloud crop is still kept as evidence. Reuses the provider parser.
    from .ocr import parse_document_identifiers
    printed = parse_document_identifiers('\n'.join(line['text'] for line in lines if line['y'] < .31))
    from .ocr import mixed_families
    order = printed.get('work_order') or printed.get('shipment')
    parent = printed.get('rental_order') or printed.get('sales_order')
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
    return dict(document_type=paper, copy=copy_name, order_number=order, parent_order_number=parent,
                mixed_order_types=mixed_families(printed),
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
                expected_pages=int(pagination[2]) if pagination else None)


def save_page_fields(store, page_id, fields):
    """Keep local page evidence even when Azure cannot identify or match the page."""
    with store.engine.begin() as connection:
        upsert(connection, db.page_extractions, ['page_id'], dict(page_id=page_id,
            extracted_at=db.utcnow(), method=fields.get('extraction_method', 'local_document'), fields=fields))


def page_field_records(store):
    """Read per-page evidence, falling back to details saved by older successful matches."""
    records = {r['id']: r['payload'] for r in store.rows(select(db.raw_rows).where(db.raw_rows.c.sheet == 'document_fields'))}
    records.update({r['page_id']: r['fields'] for r in store.rows(select(db.page_extractions))})
    return records


def observe_rental_context(store, page, page_id, record, identifier, kind='rental_order'):
    """Preserve the identified parent order (RO or SO) even when its work order or shipment is unreadable.

    The ``rental_orders`` tables hold every parent order, rental and sales alike;
    their names predate sales orders having shipments.
    """
    if not record.get('parent_order_number') or not record.get('customer'):
        raise ValueError('Order number and customer are required')
    key = {'rental_order': 'parent_order_number', 'sales_order': 'parent_order_number',
           'work_order': 'order_number', 'shipment': 'order_number'}[kind]
    if normalized(identifier, key) != normalized(record.get(key), key):
        raise ValueError('OCR and local order fields disagree')
    record = pd.DataFrame.from_records([record]).to_dict(orient='records')[0]
    with store.engine.begin() as connection:
        customer = upsert(connection, db.customers, ['source_system', 'external_key'], dict(
            source_system='documents', external_key=hashlib.sha256(record['customer'].casefold().encode()).hexdigest(), name=record['customer']))
        existing = connection.execute(select(db.rental_orders).where(db.rental_orders.c.source_system == 'documents',
            db.rental_orders.c.customer_id == customer, db.rental_orders.c.rental_number == record['parent_order_number'])).mappings().first()
        address = record.get('address') or (existing['address'] if existing else '')
        if existing and existing['address'] and record.get('address') and normalized(existing['address'], 'address') != normalized(record['address'], 'address'):
            raise ValueError('Conflicting billing address for the same order')
        rental = upsert(connection, db.rental_orders, ['source_system', 'customer_id', 'rental_number'], dict(
            source_system='documents', customer_id=customer, rental_number=record['parent_order_number'], address=address))
        attempt = connection.scalar(select(db.attempts.c.id).where(db.attempts.c.page_id == page_id)
            .order_by(db.attempts.c.started_at.desc(), db.attempts.c.id.desc()).limit(1))
        previous = connection.scalar(select(db.rental_pages.c.rental_id).where(db.rental_pages.c.page_id == page_id))
        if previous and previous != rental:
            raise ValueError('Conflicting parent order for the same source page')
        upsert(connection, db.rental_pages, ['page_id'], dict(page_id=page_id, rental_id=rental, attempt_id=attempt, fields=record))
    return rental


def observe_order(store, page, page_id, fields, identifier, kind):
    """Persist one extracted dataframe row and return its detected order ID."""
    record = pd.DataFrame.from_records([fields]).to_dict(orient='records')[0]
    if not record.get('order_number') or not record.get('customer'):
        raise ValueError('Required document fields are missing')
    kind_of_order = order_type(record['order_number'])
    if kind_of_order is None:
        raise ValueError('The page must print a W- work order or a shipment number')
    if parent_type(record.get('parent_order_number')) != kind_of_order:
        raise ValueError('A work order needs its RO- and a shipment needs its SO-')
    identifier_field = {'work_order': 'order_number', 'shipment': 'order_number',
                        'rental_order': 'parent_order_number', 'sales_order': 'parent_order_number'}[kind]
    if normalized(identifier, identifier_field) != normalized(record[identifier_field], identifier_field):
        raise ValueError('Local fields disagree with the OCR identifier')
    expected, number = record.get('expected_pages'), record.get('page_number')
    if not expected or not number or not 1 <= number <= expected:
        raise ValueError('Printed page numbering is missing or invalid')
    with store.engine.begin() as connection:
        existing = connection.execute(select(db.orders).where(
            db.orders.c.source_system == 'documents', db.orders.c.order_number == record['order_number'])).mappings().first()
        if existing and existing['expected_pages'] != expected:
            raise ValueError('Conflicting fields for the same order')
        if existing:
            customer_name = connection.scalar(select(db.customers.c.name).where(db.customers.c.id == existing['customer_id']))
            if normalized(customer_name, 'customer') != normalized(record['customer'], 'customer'):
                raise ValueError('Conflicting customer for the same order')
            previous = connection.execute(select(db.raw_rows.c.payload).where(db.raw_rows.c.sheet == 'document_fields',
                db.raw_rows.c.payload['order_number'].as_string() == record['order_number'])).scalars()
            for prior in previous:
                if prior.get('order_number') == record['order_number']:
                    if prior.get('address') and record.get('address') and normalized(prior['address'], 'address') != normalized(record['address'], 'address'):
                        raise ValueError('Conflicting document fields for the same order')
                    if prior.get('parent_order_number') and record.get('parent_order_number') and prior['parent_order_number'] != record['parent_order_number']:
                        raise ValueError('Conflicting parent order for the same work order or shipment')
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
            source_system='documents', order_number=record['order_number'],
            customer_id=customer, ship_to=record.get('destination') or '', status='OPEN',
            order_date=parsed_date(record.get('order_date'), existing['order_date'] if existing else None),
            deadline=parsed_date(record.get('due_date'), existing['deadline'] if existing else None),
            requested_by='', order_type=kind_of_order, expected_pages=expected,
            source_sheet='document_fields', source_id=source))
        if record.get('parent_order_number'):
            parent = connection.scalar(select(db.rental_pages.c.rental_id).where(db.rental_pages.c.page_id == page_id))
            previous = connection.scalar(select(db.rental_tickets.c.rental_id).where(db.rental_tickets.c.order_id == order_id))
            if previous and previous != parent:
                raise ValueError('A work order or shipment cannot silently move to a different order')
            if parent:
                upsert(connection, db.rental_tickets, ['order_id'], dict(order_id=order_id, rental_id=parent))
        return order_id
