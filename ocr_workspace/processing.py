"""Database-backed page registration, OCR attempts and explicit retry behavior."""
import hashlib
from pathlib import Path

import pymupdf as fitz
from sqlalchemy import select

from . import storage as db
from .etl import checksum, upsert

PROVIDER = "azure_document_intelligence"
CACHE_PROVIDER = "ocr_result_cache"


def _cached_identity(store, crop_hash):
    """Return (hit, parsed) for a header crop already read by the current parser version."""
    from .ocr import PARSER_VERSION, ParsedIdentifier
    with store.engine.connect() as connection:
        row = connection.execute(select(db.ocr_cache).where(
            db.ocr_cache.c.crop_sha256 == crop_hash)).mappings().first()
    if row is None or row["parser_version"] != PARSER_VERSION:
        return False, None
    if not row["identifier"]:
        return True, None
    return True, ParsedIdentifier(row["kind"], row["identifier"], dict(row["identifiers"] or {}))


def _remember_identity(store, crop_hash, parsed):
    """Store only completed provider reads; errors are never cached and stay retryable."""
    from .ocr import PARSER_VERSION
    with store.engine.begin() as connection:
        upsert(connection, db.ocr_cache, ["crop_sha256"], {
            "crop_sha256": crop_hash, "parser_version": PARSER_VERSION,
            "kind": parsed.kind if parsed else None, "identifier": parsed.value if parsed else None,
            "identifiers": dict(parsed.identifiers) if parsed else {}, "created_at": db.utcnow()})


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


def process_page(store, page_id, source_system="tracker", extractor=None, on_stage=None, document_driven=False,
                 use_cache=True):
    """Commit an attempt before calling the provider; retain failures for explicit retry.

    The default provider is billed per page, so its result is cached by the
    SHA-256 of the exact header crop it would receive. Injected extractors
    (tests, alternate providers) always run and never read or write the cache.
    """
    from .ocr import PARENT_OF, ParsedIdentifier, extract_order_identity, mixed_families, parse_identifier
    use_cache = use_cache and extractor is None
    if extractor is None:
        extractor = extract_order_identity
    with store.engine.connect() as connection:
        page = connection.execute(select(db.pages.c.page_number, db.documents.c.path, db.documents.c.sha256)
            .select_from(db.pages.join(db.documents)).where(db.pages.c.id == page_id)).mappings().one()
    attempt_id = db.uid()
    with store.engine.begin() as connection:
        connection.execute(db.attempts.insert().values(id=attempt_id, page_id=page_id,
            provider=PROVIDER, started_at=db.utcnow(), status="running"))
    identifier = error = None
    cached = False
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
        crop_hash = hashlib.sha256(image).hexdigest()
        if use_cache:
            cached, parsed = _cached_identity(store, crop_hash)
        if not cached:
            parsed = extractor(image, crop_header=False)
            if use_cache and (parsed is None or isinstance(parsed, ParsedIdentifier)):
                _remember_identity(store, crop_hash, parsed)
        if on_stage:
            on_stage("matching")
        if isinstance(parsed, ParsedIdentifier):
            identifier, kind, identifiers = parsed.value, parsed.kind, parsed.identifiers
        else:
            # Injected extractors may return a bare "W-0000001", "Shipment 00001",
            # "RO-…" or "SO-…" string. Anything else is not an identifier.
            reparsed = parse_identifier(str(parsed)) if parsed is not None else None
            identifier, kind = (reparsed.value, reparsed.kind) if reparsed else (None, None)
            identifiers = reparsed.identifiers if reparsed else {}
        if fields is not None:
            fields['ocr_identifiers'] = identifiers
            fields['ocr_identifier_kind'] = kind if identifier else None
            save_page_fields(store, page_id, fields)
        # A page is a rental page (RO + W) or a sales page (SO + Shipment), never both.
        if mixed_families(identifiers):
            error = 'rental_and_sales_numbers_on_one_page'
        detected = None
        if document_driven and not error:
            from .document_data import observe_order, observe_rental_context
            from .page_review import normalized
            local = {'work_order': fields.get('order_number'), 'shipment': fields.get('order_number'),
                     'rental_order': fields.get('parent_order_number'), 'sales_order': fields.get('parent_order_number')}
            if fields.get('mixed_order_types'):
                error = 'rental_and_sales_numbers_on_one_page'
            elif any(local[k] and normalized(value, k) != normalized(local[k], k) for k, value in identifiers.items()):
                error = 'identifier_fields_disagree'
            if not error and identifier and fields.get('parent_order_number'):
                try:
                    observe_rental_context(store, page, page_id, fields, identifier, kind)
                except ValueError:
                    error = 'parent_order_conflict'
            # The parent order groups several work orders or shipments. A local
            # full-page read must not hide a number the provider could not read in its crop.
            if not error and kind in PARENT_OF.values():
                error = 'work_order_not_read' if kind == 'rental_order' else 'shipment_not_read'
            if not error and identifier:
                try:
                    detected = observe_order(store, page, page_id, fields, identifier, kind)
                except ValueError:
                    error = 'document_fields_incomplete_or_conflicting'
        with store.engine.begin() as connection:
            if document_driven:
                matches = [detected] if detected else []
            elif error or kind not in PARENT_OF:
                matches = []
            else:
                matches = connection.execute(select(db.orders.c.id).where(
                    db.orders.c.source_system == source_system,
                    db.orders.c.order_number == identifier)).scalars().all()
            if len(matches) == 1:
                upsert(connection, db.associations, ["order_id", "page_id", "method"],
                    {"order_id": matches[0], "page_id": page_id, "method": "azure_ocr"})
                status = "success"
            else:
                status = "no_match"
                error = error or ("unknown_order" if identifier else "identifier_not_found")
            connection.execute(db.attempts.update().where(db.attempts.c.id == attempt_id).values(
                status=status, identifier=identifier, error_code=error, finished_at=db.utcnow(),
                provider=CACHE_PROVIDER if cached else PROVIDER))
    except Exception as exc:
        http_status = getattr(exc, "status_code", None)
        status, error = "error", f"HTTP{http_status}" if isinstance(http_status, int) else type(exc).__name__
        with store.engine.begin() as connection:
            connection.execute(db.attempts.update().where(db.attempts.c.id == attempt_id).values(
                status=status, error_code=error, finished_at=db.utcnow()))
    return {"attempt_id": attempt_id, "status": status, "identifier": identifier, "error_code": error,
            "cached": cached}


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
