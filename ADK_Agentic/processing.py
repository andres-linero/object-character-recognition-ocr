"""Database-backed page registration, OCR attempts and explicit retry behavior."""
from pathlib import Path

import fitz
from sqlalchemy import select

try:
    from . import storage as db
    from .etl import checksum, upsert
except ImportError:
    import storage as db
    from etl import checksum, upsert


def register_pdf(store, path, synthetic=False):
    path = Path(path).resolve()
    with fitz.open(path) as pdf:
        total = len(pdf)
    if total < 1:
        raise ValueError("Document must contain at least one page")
    with store.engine.begin() as connection:
        document_id = upsert(connection, db.documents, ["sha256"],
            {"sha256": checksum(path), "path": str(path), "page_count": total, "synthetic": synthetic})
        for number in range(1, total + 1):
            upsert(connection, db.pages, ["document_id", "page_number"],
                   {"document_id": document_id, "page_number": number})
    return document_id


def process_page(store, page_id, source_system="tracker", extractor=None, on_stage=None, document_driven=False):
    """Commit an attempt before calling the provider; retain failures for explicit retry."""
    from .ocr import ParsedIdentifier, extract_order_identity
    if extractor is None:
        extractor = extract_order_identity
    with store.engine.connect() as connection:
        page = connection.execute(select(db.pages.c.page_number, db.documents.c.path, db.documents.c.sha256)
            .select_from(db.pages.join(db.documents)).where(db.pages.c.id == page_id)).mappings().one()
    attempt_id = db.uid()
    with store.engine.begin() as connection:
        connection.execute(db.attempts.insert().values(id=attempt_id, page_id=page_id,
            provider="azure_document_intelligence", started_at=db.utcnow(), status="running"))
    identifier = error = None
    try:
        path = Path(page["path"])
        if checksum(path) != page["sha256"]:
            raise ValueError("Document changed after registration")
        with fitz.open(path) as pdf:
            source = pdf[page["page_number"] - 1]
            fields = None
            if document_driven:
                from .document_data import extract_fields, save_page_fields
                fields = extract_fields(source)
                save_page_fields(store, page_id, fields)
            rect = source.rect
            crop = fitz.Rect(rect.width / 2, 0, rect.width, rect.height / 4)
            image = source.get_pixmap(dpi=200, clip=crop).tobytes("png")
        parsed = extractor(image, crop_header=False)
        if on_stage:
            on_stage("matching")
        if isinstance(parsed, ParsedIdentifier):
            identifier, kind = parsed.value, parsed.kind
        else:
            # Compatibility callbacks return W- work orders or numeric shipments.
            identifier = str(parsed).strip() if parsed is not None else None
            kind = "work_order" if identifier and identifier.upper().startswith(("W-", "TK-", "OD-")) else "shipment"
        if fields is not None:
            fields['ocr_identifiers'] = parsed.identifiers if isinstance(parsed, ParsedIdentifier) else {}
            fields['ocr_identifier_kind'] = kind if identifier else None
            save_page_fields(store, page_id, fields)
        identifier_conflict = False
        if document_driven and isinstance(parsed, ParsedIdentifier):
            from .page_review import normalized
            names = {'shipment': 'shipment', 'work_order': 'work_order', 'rental_order': 'parent_rental_number', 'customer_order': 'customer_order_number'}
            identifier_conflict = any(fields.get(names[k]) and normalized(value, names[k]) != normalized(fields[names[k]], names[k])
                for k, value in parsed.identifiers.items() if k in names)
            if identifier_conflict:
                error = 'identifier_fields_disagree'
        if fields is not None and fields.get('rental_number_conflict'):
            identifier_conflict = True
            error = 'rental_number_conflict'
        detected = None
        rental_id = None
        if document_driven and identifier and fields.get('parent_rental_number'):
            from .document_data import observe_rental_context
            try:
                rental_id = observe_rental_context(store, page, page_id, fields, identifier, kind)
            except ValueError:
                error = 'rental_order_conflict'
        if document_driven and (fields.get('work_order') or '').startswith('OD-'):
            # RO/SO can group several orders. A local full-page read of OD must
            # not hide a failed read of OD inside the fixed provider crop.
            provider_order = parsed.identifiers.get('work_order') if isinstance(parsed, ParsedIdentifier) else None
            provider_order = provider_order or (identifier if kind == 'work_order' else None)
            if not provider_order:
                identifier_conflict = True
                error = error or 'order_number_not_read'
        if document_driven and identifier and not identifier_conflict and (not fields.get('parent_rental_number') or rental_id):
            from .document_data import observe_order
            try:
                detected = observe_order(store, page, page_id, fields, identifier, kind)
            except ValueError:
                error = 'ticket_identifier_missing' if rental_id and not fields.get('work_order') else 'document_fields_incomplete_or_conflicting'
        column = db.orders.c.order_number if kind == "work_order" else db.orders.c.shipment_number
        with store.engine.begin() as connection:
            matches = [detected] if detected else [] if document_driven or not identifier or kind in {'customer_order', 'rental_order'} else connection.execute(select(db.orders.c.id).where(
                db.orders.c.source_system == source_system,
                column == identifier)).scalars().all()
            if len(matches) == 1:
                upsert(connection, db.associations, ["order_id", "page_id", "method"],
                    {"order_id": matches[0], "page_id": page_id, "method": "azure_ocr"})
                status = "success"
            else:
                status = "no_match"
                error = error or ("unknown_or_ambiguous_order" if identifier else "identifier_not_found")
            connection.execute(db.attempts.update().where(db.attempts.c.id == attempt_id).values(
                status=status, identifier=identifier, error_code=error, finished_at=db.utcnow()))
    except Exception as exc:
        http_status = getattr(exc, "status_code", None)
        status, error = "error", f"HTTP{http_status}" if isinstance(http_status, int) else type(exc).__name__
        with store.engine.begin() as connection:
            connection.execute(db.attempts.update().where(db.attempts.c.id == attempt_id).values(
                status=status, error_code=error, finished_at=db.utcnow()))
    return {"attempt_id": attempt_id, "status": status, "identifier": identifier, "error_code": error}


def process_batch(store, limit=10, retry_errors=False, source_system="tracker", extractor=None):
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100 pages")
    history = {}
    for record in store.rows(select(db.attempts.c.page_id, db.attempts.c.status, db.attempts.c.started_at)
                             .order_by(db.attempts.c.started_at)):
        history[record["page_id"]] = record["status"]
    candidates = store.rows(select(db.pages.c.id).select_from(db.pages.join(db.documents))
                            .order_by(db.documents.c.path, db.pages.c.page_number))
    approved = {r['page_id'] for r in store.rows(select(db.page_approvals.c.page_id))}
    ready = [p["id"] for p in candidates if p['id'] not in approved and (p["id"] not in history or
             (retry_errors and history[p["id"]] == "error"))][:limit]
    return [process_page(store, page, source_system, extractor) for page in ready]
