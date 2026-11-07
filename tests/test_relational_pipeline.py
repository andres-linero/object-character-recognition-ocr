"""Exercise real storage/ETL transactions on SQLite and optional PostgreSQL."""
import csv
import json
import os

import fitz
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql

from ADK_Agentic import etl, storage as db
from ADK_Agentic.processing import process_batch, register_pdf
from scripts import create_demo_data as demo


@pytest.fixture(params=["sqlite", "postgresql"])
def store(request, tmp_path):
    if request.param == "postgresql":
        url = os.getenv("TEST_DATABASE_URL")
        if not url:
            pytest.skip("Set TEST_DATABASE_URL for a disposable PostgreSQL database")
        result = db.Store(url)
        # Only use an explicitly designated disposable test database.
        result.migrate()
        with result.engine.begin() as connection:
            for table in reversed(db.metadata.sorted_tables):
                if table is not db.versions:
                    connection.execute(table.delete())
    else:
        result = db.Store(db.sqlite_url(tmp_path / "test.sqlite"))
        result.migrate()
    yield result
    result.close()


def tracker(path, rows=None):
    rows = rows or [dict(Order_ID="W-900001", SO="800001", Customer_name="Demo Customer", Status="OPEN",
                        Today="2030-01-01", Deadline="2030-01-10", Expected_Pages="6")]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_repeat_loads_upsert_and_keep_provenance(store, tmp_path):
    path = tracker(tmp_path / "orders.csv")
    first = etl.ingest_tracker(store, path)
    second = etl.ingest_tracker(store, path)
    assert first["rows_loaded"] == second["rows_loaded"] == 1
    assert store.counts()["orders"] == store.counts()["customers"] == 1
    assert store.counts()["ingestion_runs"] == 2
    assert len(store.rows(select(db.raw_rows))) == 2
    row = list(csv.DictReader(path.open()))[0]
    row["Status"] = "COMPLETE"
    tracker(path, [row])
    etl.ingest_tracker(store, path)
    assert store.order_rows()[0]["Status"] == "COMPLETE"
    assert store.counts()["orders"] == 1
    store.migrate()  # migration version remains stable on repeated startup
    assert len(store.rows(select(db.versions))) == 1


def test_invalid_rows_are_quarantined_and_duplicate_shipments_do_not_corrupt(store, tmp_path):
    good = dict(Order_ID="W-900001", SO="800001", Customer_name="Demo", Status="OPEN")
    bad = dict(good, Order_ID="bad")
    duplicate = dict(good, Order_ID="W-900002")
    result = etl.ingest_tracker(store, tracker(tmp_path / "invalid.csv", [good, bad, duplicate]))
    assert result["rows_loaded"] == 1
    assert result["rows_rejected"] == 2
    assert store.counts()["orders"] == 1
    assert store.counts()["rejected_rows"] == 2
    assert store.rows(select(db.runs))[0]["status"] == "partial"


def test_unexpected_failure_rolls_back_business_and_staging_but_retains_failed_run(store, tmp_path, monkeypatch):
    path = tracker(tmp_path / "broken.csv")
    original = etl._records
    def interrupted(path):
        yield next(original(path))
        raise RuntimeError("simulated interrupted source")
    monkeypatch.setattr(etl, "_records", interrupted)
    with pytest.raises(RuntimeError):
        etl.ingest_tracker(store, path)
    assert store.counts()["orders"] == store.counts()["customers"] == 0
    assert not store.rows(select(db.raw_rows))
    assert store.rows(select(db.runs))[0]["status"] == "failed"


def test_constraints_reject_orphan_pages(store):
    with pytest.raises(IntegrityError), store.engine.begin() as connection:
        connection.execute(db.pages.insert().values(document_id="missing", page_number=1))


def test_manifest_registration_is_idempotent_and_separate_from_ocr(store, tmp_path):
    dataset = tmp_path / "dataset"
    demo.generate_dataset(dataset, count=1, min_pages=6, max_pages=6, rasterize=False)
    etl.ingest_tracker(store, dataset / "orders.xlsx", "demo", synthetic=True)
    assert etl.register_manifest(store, dataset / "manifest.json") == 6
    assert etl.register_manifest(store, dataset / "manifest.json") == 6
    counts = store.counts()
    assert counts["orders"] == counts["documents"] == 1
    assert counts["document_pages"] == counts["order_document_pages"] == 6
    assert counts["ocr_attempts"] == 0
    data = json.loads((dataset / "manifest.json").read_text())
    data["tickets"][0]["pdf"] = "../outside.pdf"
    (dataset / "manifest.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="leaves its dataset"):
        etl.register_manifest(store, dataset / "manifest.json")
    assert store.counts()["document_pages"] == 6


def test_ocr_errors_are_retryable_without_redoing_successful_pages(store, tmp_path):
    etl.ingest_tracker(store, tracker(tmp_path / "orders.csv"))
    pdf = tmp_path / "ticket.pdf"
    with fitz.open() as doc:
        doc.new_page().insert_text((340, 60), "Shipment No. 800001")
        doc.save(pdf)
    register_pdf(store, pdf)
    def broken(*args, **kwargs):
        raise RuntimeError("provider unavailable")
    assert process_batch(store, extractor=broken)[0]["status"] == "error"
    assert process_batch(store, extractor=broken) == []
    result = process_batch(store, retry_errors=True, extractor=lambda *a, **k: "800001")
    assert result[0]["status"] == "success"
    assert process_batch(store, retry_errors=True, extractor=broken) == []
    assert store.counts()["ocr_attempts"] == 2
    assert store.rows(select(db.associations))[0]["method"] == "azure_ocr"


def test_postgres_ddl_has_explicit_schema_and_constraints():
    ddl = str(CreateTable(db.orders).compile(dialect=postgresql.dialect()))
    assert "core.orders" in ddl and "FOREIGN KEY" in ddl and "UNIQUE" in ddl
    assert "CHECK" in ddl


def test_ocr_keeps_overlapping_shipment_and_work_order_namespaces_separate(store, tmp_path):
    from ADK_Agentic.ocr import ParsedIdentifier
    from ADK_Agentic.processing import process_page
    rows = [dict(Order_ID="W-900001", SO="800001", Customer_name="Demo", Status="OPEN"),
            dict(Order_ID="800001", SO="800002", Customer_name="Demo", Status="OPEN")]
    etl.ingest_tracker(store, tracker(tmp_path / "orders.csv", rows))
    pdf = tmp_path / "overlap.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.new_page()
        doc.save(pdf)
    register_pdf(store, pdf)
    pages = store.rows(select(db.pages).order_by(db.pages.c.page_number))
    assert process_page(store, pages[0]["id"], extractor=lambda *a, **k: "800001")["status"] == "success"
    assert process_page(store, pages[1]["id"], extractor=lambda *a, **k: ParsedIdentifier("work_order", "800001"))["status"] == "success"
    orders = {row["order_number"]: row["id"] for row in store.rows(select(db.orders))}
    associations = store.rows(select(db.associations))
    assert {(a["page_id"], a["order_id"]) for a in associations} == {
        (pages[0]["id"], orders["W-900001"]), (pages[1]["id"], orders["800001"])}
