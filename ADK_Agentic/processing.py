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


def process_page(store, page_id, source_system="tracker", extractor=None):
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
            rect = source.rect
            crop = fitz.Rect(rect.width / 2, 0, rect.width, rect.height / 4)
            image = source.get_pixmap(dpi=200, clip=crop).tobytes("png")
        parsed = extractor(image, crop_header=False)
        if isinstance(parsed, ParsedIdentifier):
            identifier, kind = parsed.value, parsed.kind
        else:
            # Compatibility callbacks return W- work orders or numeric shipments.
            identifier = str(parsed).strip() if parsed is not None else None
            kind = "work_order" if identifier and identifier.upper().startswith("W-") else "shipment"
        column = db.orders.c.order_number if kind == "work_order" else db.orders.c.shipment_number
        with store.engine.begin() as connection:
            matches = [] if not identifier else connection.execute(select(db.orders.c.id).where(
                db.orders.c.source_system == source_system,
                column == identifier)).scalars().all()
            if len(matches) == 1:
                upsert(connection, db.associations, ["order_id", "page_id", "method"],
                    {"order_id": matches[0], "page_id": page_id, "method": "azure_ocr"})
                status = "success"
            else:
                status = "no_match"
                error = "unknown_or_ambiguous_order" if identifier else "identifier_not_found"
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
    ready = [p["id"] for p in candidates if p["id"] not in history or
             (retry_errors and history[p["id"]] == "error")][:limit]
    return [process_page(store, page, source_system, extractor) for page in ready]
