"""Extract, validate, stage and transactionally load tracker/document data."""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re

import fitz
import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

try:
    from . import storage as db
except ImportError:
    import storage as db


def checksum(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def upsert(connection, table, keys, values):
    insert = pg_insert if connection.dialect.name == "postgresql" else sqlite_insert
    statement = insert(table).values(**values)
    updates = {key: getattr(statement.excluded, key) for key in values if key not in keys and key != "id"}
    if updates:
        statement = statement.on_conflict_do_update(index_elements=keys, set_=updates)
    else:
        statement = statement.on_conflict_do_nothing(index_elements=keys)
    value = connection.scalar(statement.returning(table.c.id))
    if value is None:
        query = select(table.c.id)
        for key in keys:
            query = query.where(table.c[key] == values[key])
        value = connection.scalar(query)
    return value


def text(value):
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def parse_date(value, name):
    if not text(value):
        return None
    try:
        return pd.to_datetime(value, errors="raise").date()
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{name} must be a valid date") from exc


def transform(row):
    order = re.sub(r"\.0$", "", text(row.get("Order_ID")))
    shipment = re.sub(r"\.0$", "", text(row.get("SO"))).lstrip("0")
    customer = text(row.get("Customer_name", row.get("Customer")))
    if not re.fullmatch(r"(?:W-)?\d{4,12}", order, re.IGNORECASE):
        raise ValueError("Order_ID must be a numeric identifier, optionally prefixed W-")
    if not re.fullmatch(r"\d{4,8}", shipment):
        raise ValueError("SO must contain 4 to 8 digits after normalization")
    if not customer:
        raise ValueError("Customer_name is required")
    statuses = {"OPEN": "OPEN", "COMPLETE": "COMPLETE", "COMPLETED": "COMPLETE", "CLOSED": "COMPLETE"}
    status = statuses.get(text(row.get("Status")).upper())
    if status is None:
        raise ValueError("Status must be OPEN, COMPLETE, COMPLETED or CLOSED")
    count = text(row.get("Expected_Pages"))
    if count and not re.fullmatch(r"[1-9]\d*(?:\.0)?", count):
        raise ValueError("Expected_Pages must be a positive integer")
    # Legacy trackers lack a customer ID. Prefer Customer_ID when provided.
    customer_key = text(row.get("Customer_ID")) or "legacy-name:" + hashlib.sha256(customer.casefold().encode()).hexdigest()
    if len(customer_key) > 100:
        raise ValueError("Customer_ID is too long")
    return {"order_number": order.upper(), "shipment_number": shipment,
            "customer_name": customer, "customer_key": customer_key,
            "ship_to": text(row.get("Ship_to")), "status": status,
            "order_date": parse_date(row.get("Today"), "Today"),
            "deadline": parse_date(row.get("Deadline"), "Deadline"),
            "requested_by": text(row.get("Requested by")),
            "order_type": text(row.get("Order_Type")) or "RENTAL",
            "expected_pages": int(float(count)) if count else None}


def _records(path):
    if path.suffix.lower() == ".csv":
        sheets = {"CSV": pd.read_csv(path, dtype=object)}
    elif path.suffix.lower() == ".xlsx":
        sheets = pd.read_excel(path, sheet_name=None, dtype=object)
    else:
        raise ValueError("Tracker must be .xlsx or .csv")
    for sheet, frame in sheets.items():
        if frame.empty:
            continue
        for number, raw in enumerate(frame.to_dict("records"), 2):
            yield sheet, number, raw


def ingest_tracker(store, path, source_system="tracker", synthetic=False):
    """Partial load: valid rows commit; rejected rows retain provenance/reasons.

    Any unexpected file/database error rolls the entire load transaction back.
    A separate failed run record survives that rollback.
    """
    path = Path(path).resolve()
    if not source_system or len(source_system) > 80:
        raise ValueError("source_system must contain 1 to 80 characters")
    run_id = db.uid()
    with store.engine.begin() as connection:
        connection.execute(db.runs.insert().values(id=run_id, kind="tracker", started_at=db.utcnow(), status="running"))
    loaded = failed = seen = 0
    try:
        signature = checksum(path)
        with store.engine.begin() as connection:
            source = upsert(connection, db.sources, ["sha256"],
                            {"sha256": signature, "name": path.name, "kind": "tracker", "synthetic": synthetic})
            encountered = set()
            for sheet, number, row in _records(path):
                seen += 1
                raw_id = db.uid()
                payload = {str(k): text(v) for k, v in row.items()}
                connection.execute(db.raw_rows.insert().values(id=raw_id, run_id=run_id, source_id=source,
                    sheet=sheet, row_number=number, payload=payload))
                try:
                    values = transform(row)
                    pair = values["order_number"]
                    if pair in encountered:
                        raise ValueError("Duplicate Order_ID within this tracker")
                    encountered.add(pair)
                    name = values.pop("customer_name")
                    customer_key = values.pop("customer_key")
                    with connection.begin_nested():
                        customer_id = upsert(connection, db.customers, ["source_system", "external_key"],
                            {"source_system": source_system, "external_key": customer_key, "name": name})
                        upsert(connection, db.orders, ["source_system", "order_number"],
                            dict(values, customer_id=customer_id, source_system=source_system,
                                 source_id=source, source_sheet=sheet))
                    loaded += 1
                except (ValueError, IntegrityError) as exc:
                    failed += 1
                    reason = str(exc) if isinstance(exc, ValueError) else "Conflicting shipment or relational constraint"
                    connection.execute(db.rejected.insert().values(raw_row_id=raw_id, reason=reason))
            connection.execute(db.runs.update().where(db.runs.c.id == run_id).values(
                finished_at=db.utcnow(), status="partial" if failed else "success",
                rows_seen=seen, rows_loaded=loaded, rows_rejected=failed))
    except Exception as exc:
        with store.engine.begin() as connection:
            connection.execute(db.runs.update().where(db.runs.c.id == run_id).values(
                status="failed", finished_at=db.utcnow(), error_code=type(exc).__name__))
        raise
    return {"run_id": run_id, "rows_seen": seen, "rows_loaded": loaded, "rows_rejected": failed}


def register_manifest(store, path, source_system="demo"):
    """Register synthetic expected associations, never represent them as OCR attempts."""
    path = Path(path).resolve()
    manifest = json.loads(path.read_text())
    if manifest.get("generator") != "ocr-synthetic-demo-v1" or manifest.get("synthetic") is not True:
        raise ValueError("Only generator-owned synthetic manifests are supported")
    count = 0
    with store.engine.begin() as connection:
        for ticket in manifest["tickets"]:
            pdf = (path.parent / ticket["pdf"]).resolve()
            if not pdf.is_relative_to(path.parent):
                raise ValueError("Manifest PDF path leaves its dataset")
            with fitz.open(pdf) as document:
                actual_pages = len(document)
            mappings = ticket["pages"]
            if actual_pages != ticket["page_count"] or len(mappings) != actual_pages:
                raise ValueError("Manifest page count disagrees with PDF")
            if {p["page"] for p in mappings} != set(range(1, actual_pages + 1)):
                raise ValueError("Manifest must enumerate each page exactly once")
            order_id = connection.scalar(select(db.orders.c.id).where(
                db.orders.c.source_system == source_system,
                db.orders.c.order_number == ticket["order_id"],
                db.orders.c.shipment_number == ticket["shipment"]))
            if order_id is None:
                raise ValueError("Import the matching tracker before its manifest")
            document_id = upsert(connection, db.documents, ["sha256"],
                {"sha256": checksum(pdf), "path": str(pdf), "page_count": actual_pages, "synthetic": True})
            for mapping in mappings:
                if mapping["expected_ocr_id"] != ticket["shipment"]:
                    raise ValueError("Manifest page identifier disagrees with its ticket")
                page_id = upsert(connection, db.pages, ["document_id", "page_number"],
                    {"document_id": document_id, "page_number": mapping["page"]})
                upsert(connection, db.associations, ["order_id", "page_id", "method"],
                    {"order_id": order_id, "page_id": page_id, "method": "synthetic_manifest"})
                count += 1
    return count
