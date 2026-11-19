"""Exercise real storage/ETL transactions on SQLite and optional PostgreSQL."""
import csv
import json
import os

import pymupdf as fitz
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql

from ocr_workspace import etl, storage as db
from ocr_workspace.processing import process_batch, register_pdf
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


def order(parent, document, **extra):
    """One tracker row: "Order" is the parent (RO-/SO-), "Work order" the document created from it."""
    return {"Order": parent, "Work order": document, "Customer_name": "Demo", "Status": "OPEN", **extra}


def tracker(path, rows=None):
    rows = rows or [order("RO-0000001", "W-0000001", Customer_name="Demo Customer",
                          Today="2030-01-01", Deadline="2030-01-10", Expected_Pages="6")]
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
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
    assert [r["version"] for r in store.rows(select(db.versions).order_by(db.versions.c.version))] == [1, 2, 3, 4, 5, 6, 7]
    assert "SO" not in store.order_rows()[0] and store.order_rows()[0]["Order_ID"] == "W-0000001"
    assert "shipment_number" not in db.orders.c


def test_invalid_rows_are_quarantined_and_one_rental_order_groups_several_work_orders(store, tmp_path):
    good = order("RO-0000001", "W-0000001")
    bad = dict(good, **{"Work order": "bad"})
    sibling = dict(good, **{"Work order": "W-0000002"})
    repeated = dict(good)
    result = etl.ingest_tracker(store, tracker(tmp_path / "invalid.csv", [good, bad, sibling, repeated]))
    assert result["rows_loaded"] == 2
    assert result["rows_rejected"] == 2
    assert store.counts()["orders"] == 2
    assert store.counts()["rejected_rows"] == 2
    assert sorted(r["reason"] for r in store.rows(select(db.rejected))) == [
        '"Work order" must be a work order (W-…) or a shipment (Shipment …)',
        "Duplicate work order or shipment within this tracker"]
    assert store.rows(select(db.runs))[0]["status"] == "partial"
    rentals = store.rows(select(db.rental_orders))
    assert [r["rental_number"] for r in rentals] == ["RO-0000001"]
    links = store.rows(select(db.rental_tickets))
    assert len(links) == 2 and {link["rental_id"] for link in links} == {rentals[0]["id"]}
    assert {link["order_id"] for link in links} == {o["id"] for o in store.rows(select(db.orders))}


def test_tracker_links_work_orders_to_their_rental_order_and_shipments_to_their_sales_order(store, tmp_path):
    rows = [order("RO-0000002", "W-0000001", Address="102 Simulation Way"),
            order("SO-0000001", "Shipment 00001", Address="101 Simulation Way"),
            order("ro-0000004", "w-0000003"),
            order("so-0000003", "shipment no. 00002"),
            # One parent can have several documents.
            order("RO-0000002", "W-0000002", Address="102 Simulation Way"),
            order("SO-0000001", "Shipment 00003", Address="101 Simulation Way")]
    path = tracker(tmp_path / "orders.csv", rows)
    result = etl.ingest_tracker(store, path)
    assert (result["rows_loaded"], result["rows_rejected"]) == (6, 0)
    assert {r["Order_ID"]: r["Order_Type"] for r in store.order_rows()} == {
        "W-0000001": "RENTAL", "W-0000002": "RENTAL", "W-0000003": "RENTAL",
        "Shipment 00001": "SALE", "Shipment 00002": "SALE", "Shipment 00003": "SALE"}
    orders = {o["order_number"]: o["id"] for o in store.rows(select(db.orders))}
    stored = store.rows(select(db.rental_orders))
    # The parent tables hold rental orders and sales orders alike.
    assert {r["rental_number"]: r["address"] for r in stored} == {
        "RO-0000002": "102 Simulation Way", "SO-0000001": "101 Simulation Way", "RO-0000004": "", "SO-0000003": ""}
    rentals = {r["id"]: r["rental_number"] for r in stored}
    parents = {link["order_id"]: rentals[link["rental_id"]] for link in store.rows(select(db.rental_tickets))}
    assert parents == {orders["W-0000001"]: "RO-0000002", orders["W-0000002"]: "RO-0000002",
                       orders["W-0000003"]: "RO-0000004", orders["Shipment 00001"]: "SO-0000001",
                       orders["Shipment 00003"]: "SO-0000001", orders["Shipment 00002"]: "SO-0000003"}
    # Re-importing the same tracker duplicates neither the parent orders nor the links.
    etl.ingest_tracker(store, path)
    assert len(store.rows(select(db.rental_orders))) == 4
    assert len(store.rows(select(db.rental_tickets))) == 6
    assert store.counts()["orders"] == 6


def test_tracker_keeps_printed_digits_including_leading_zeros(store, tmp_path):
    rows = [order("RO-0000002", "W-0000001"), order("RO-0002", "W-0001"),
            order("SO-0000001", "Shipment 00001"), order("SO-00001", "Shipment 001")]
    result = etl.ingest_tracker(store, tracker(tmp_path / "orders.csv", rows))
    assert (result["rows_loaded"], result["rows_rejected"]) == (4, 0)
    assert {o["order_number"] for o in store.rows(select(db.orders))} == {
        "W-0000001", "W-0001", "Shipment 00001", "Shipment 001"}
    assert {r["rental_number"] for r in store.rows(select(db.rental_orders))} == {
        "RO-0000002", "RO-0002", "SO-0000001", "SO-00001"}


WORK_ORDER_REASON = '"Work order" must be a work order (W-…) or a shipment (Shipment …)'
ORDER_REASON = '"Order" must be RO-… for a work order and SO-… for a shipment'


@pytest.mark.parametrize("row,reason", [
    ({"Order": "", "Work order": "W-0000001"}, ORDER_REASON),
    ({"Order": "SO-0000001", "Work order": "W-0000001"}, ORDER_REASON),
    ({"Order": "", "Work order": "Shipment 00001"}, ORDER_REASON),
    ({"Order": "RO-0000002", "Work order": "Shipment 00001"}, ORDER_REASON),
    ({"Order": "RO-0000002 SO-0000001", "Work order": "W-0000001"}, ORDER_REASON),
    ({"Order": "W-0000002", "Work order": "W-0000001"}, ORDER_REASON),
    ({"Order": "0000002", "Work order": "W-0000001"}, ORDER_REASON),
    ({"Order": "RO-0000002", "Work order": "W-0000001 Shipment 00001"}, WORK_ORDER_REASON),
    ({"Order": "RO-0000002", "Work order": "WO-990001"}, WORK_ORDER_REASON),
    ({"Order": "RO-0000002", "Work order": "OD-1234"}, WORK_ORDER_REASON),
    ({"Order": "RO-0000002", "Work order": "TK-992001"}, WORK_ORDER_REASON),
    ({"Order": "RO-0000002", "Work order": "0000001"}, WORK_ORDER_REASON),
    ({"Order": "", "Work order": "RO-0000002"}, WORK_ORDER_REASON),
    ({"Order": "", "Work order": "SO-904001"}, WORK_ORDER_REASON),
    ({"Order": "SO-0000001", "Work order": "SO-0000001"}, WORK_ORDER_REASON),
    ({"Order": "SO-0000001", "Work order": "00001"}, WORK_ORDER_REASON),
    ({"Order": "SO-0000001", "Work order": ""}, WORK_ORDER_REASON),
    ({"Order_ID": "W-0000001", "Rental_Order": "RO-0000002"}, WORK_ORDER_REASON),
    ({"Order_ID": "WO-990001", "Rental_Order": "RO-810001"}, WORK_ORDER_REASON),
    ({"Order_ID": "SO-904001", "Rental_Order": ""}, WORK_ORDER_REASON),
    ({"Work order": "W-0000001", "Rental_Order": "RO-0000002"}, ORDER_REASON),
], ids=["work_order_without_an_order", "work_order_under_a_sales_order", "shipment_without_an_order",
        "shipment_under_a_rental_order", "work_order_under_both_parents", "work_order_as_the_parent",
        "parent_without_a_prefix", "work_order_and_shipment_in_one_row", "retired_wo_prefix", "retired_od_prefix",
        "retired_tk_prefix", "work_order_without_a_prefix", "rental_order_as_the_document",
        "standalone_sales_order", "sales_order_as_its_own_document", "bare_shipment_number", "order_without_a_document",
        "old_column_names", "old_column_names_and_old_prefixes", "old_columns_standalone_sale",
        "old_rental_order_column_beside_the_new_work_order"])
def test_tracker_rejects_rows_outside_the_order_and_work_order_model(store, tmp_path, row, reason):
    result = etl.ingest_tracker(store, tracker(tmp_path / "orders.csv", [dict(row, Customer_name="Demo", Status="OPEN")]))
    assert (result["rows_loaded"], result["rows_rejected"]) == (0, 1)
    assert store.counts()["orders"] == 0
    assert store.rows(select(db.rental_orders)) == [] and store.rows(select(db.rental_tickets)) == []
    assert store.rows(select(db.rejected))[0]["reason"] == reason


def test_legacy_so_and_shipment_columns_cannot_stand_in_for_the_order_columns(store, tmp_path):
    legacy = [{"Work order": "W-0000001", "SO": "RO-0000002", "Customer_name": "Demo", "Status": "OPEN"},
              {"Order": "SO-0000001", "Shipment": "Shipment 00001", "Customer_name": "Demo", "Status": "OPEN"}]
    result = etl.ingest_tracker(store, tracker(tmp_path / "legacy.csv", legacy))
    assert (result["rows_loaded"], result["rows_rejected"]) == (0, 2)
    assert store.counts()["orders"] == 0
    assert store.rows(select(db.rental_orders)) == []


def test_generated_tracker_uses_the_order_and_work_order_columns_and_loads_completely(store, tmp_path):
    dataset = tmp_path / "dataset"
    manifest = demo.generate_dataset(dataset, count=8, min_pages=6, max_pages=6, rasterize=False)
    with (dataset / "orders.csv").open(newline="") as handle:
        assert csv.DictReader(handle).fieldnames[:2] == ["Order", "Work order"]
    for name in ("orders.csv", "orders.xlsx"):
        result = etl.ingest_tracker(store, dataset / name, "demo", synthetic=True)
        assert (result["rows_loaded"], result["rows_rejected"]) == (8, 0)
    stored = {r["id"]: r for r in store.rows(select(db.rental_orders))}
    assert sorted(r["rental_number"] for r in stored.values()) == ["RO-0000001", "RO-0000003", "SO-0000002", "SO-0000004"]
    assert all(r["address"].endswith("Simulation Way, Demo City, ZZ 00000") for r in stored.values())
    orders = {o["id"]: o for o in store.rows(select(db.orders))}
    links = {orders[link["order_id"]]["order_number"]: stored[link["rental_id"]]["rental_number"]
             for link in store.rows(select(db.rental_tickets))}
    assert links == {t["order_id"]: t["parent_order_number"] for t in manifest["tickets"]}
    assert {o["order_number"]: o["order_type"] for o in orders.values()} == {
        t["order_id"]: t["order_type"] for t in manifest["tickets"]}


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
        doc.new_page().insert_text((340, 60), "Work Order No. W-0000001")
        doc.save(pdf)
    register_pdf(store, pdf)
    def broken(*args, **kwargs):
        raise RuntimeError("provider unavailable")
    assert process_batch(store, extractor=broken)[0]["status"] == "error"
    assert process_batch(store, extractor=broken) == []
    result = process_batch(store, retry_errors=True, extractor=lambda *a, **k: "W-0000001")
    assert result[0]["status"] == "success" and result[0]["identifier"] == "W-0000001"
    assert process_batch(store, retry_errors=True, extractor=broken) == []
    assert store.counts()["ocr_attempts"] == 2
    assert store.rows(select(db.associations))[0]["method"] == "azure_ocr"


def test_identical_header_crops_reuse_the_cached_provider_result(store, tmp_path, monkeypatch):
    from ocr_workspace import ocr
    etl.ingest_tracker(store, tracker(tmp_path / "orders.csv"))
    def scan(name, pages):
        with fitz.open() as doc:
            for _ in range(pages):
                doc.new_page().insert_text((340, 60), "Work Order No. W-0000001")
            doc.save(tmp_path / name)
        return register_pdf(store, tmp_path / name)
    calls = []
    def provider(image, crop_header=True):
        calls.append(image)
        if len(calls) == 1:
            raise RuntimeError("provider unavailable")
        return ocr.ParsedIdentifier("work_order", "W-0000001", {"work_order": "W-0000001"})
    monkeypatch.setattr(ocr, "extract_order_identity", provider)
    scan("first.pdf", 1)
    # A failed read is never cached; the retry is the first billable success.
    assert process_batch(store)[0]["status"] == "error"
    assert process_batch(store, retry_errors=True)[0]["cached"] is False
    # The same pages re-scanned with one appended: no new provider calls.
    scan("appended.pdf", 2)
    results = process_batch(store)
    assert [r["status"] for r in results] == ["success", "success"]
    assert all(r["cached"] for r in results) and len(calls) == 2
    providers = [r["provider"] for r in store.rows(select(db.attempts).order_by(db.attempts.c.started_at))]
    assert providers.count("ocr_result_cache") == 2
    # A parser change invalidates stored results instead of hiding the fix.
    monkeypatch.setattr(ocr, "PARSER_VERSION", ocr.PARSER_VERSION + 1)
    scan("after_parser_change.pdf", 3)
    assert [r["cached"] for r in process_batch(store)] == [False, True, True]


def blank_scan(store, path, pages=1):
    with fitz.open() as doc:
        for _ in range(pages):
            doc.new_page()
        doc.save(path)
    register_pdf(store, path)
    return store.rows(select(db.pages).order_by(db.pages.c.page_number))


def test_tracker_matching_uses_the_work_order_when_the_header_also_prints_its_rental_order(store, tmp_path):
    from ocr_workspace import ocr
    etl.ingest_tracker(store, tracker(tmp_path / "orders.csv"))
    blank_scan(store, tmp_path / "ticket.pdf")
    header = "RENTAL ORDER Delivery Ticket Rental Order No. RO-0000001 Work Order No. W-0000001"
    assert ocr.parse_identifier(header).kind == "work_order"
    result = process_batch(store, extractor=lambda *a, **k: ocr.parse_identifier(header))[0]
    assert (result["status"], result["identifier"], result["error_code"]) == ("success", "W-0000001", None)


def test_printed_shipment_number_matches_its_shipment_and_never_a_sales_order(store, tmp_path):
    from ocr_workspace import ocr
    rows = [order("SO-0000002", "Shipment 00001"), order("SO-0904001", "Shipment 00002")]
    etl.ingest_tracker(store, tracker(tmp_path / "orders.csv", rows))
    pages = blank_scan(store, tmp_path / "ticket.pdf", pages=3)
    headers = ["SALES ORDER Delivery Ticket Sales Order No. SO-0000002 Shipment No. 00001",
               "Delivery Ticket Shipment No. 00002",
               # The digits of a sales order printed as a shipment number are a different, unknown shipment.
               "Delivery Ticket Shipment No. 0904001"]
    results = process_batch(store, extractor=lambda image, **k: ocr.parse_identifier(headers.pop(0)))
    assert [(r["status"], r["identifier"], r["error_code"]) for r in results] == [
        ("success", "Shipment 00001", None), ("success", "Shipment 00002", None),
        ("no_match", "Shipment 0904001", "unknown_order")]
    orders = {o["id"]: o["order_number"] for o in store.rows(select(db.orders))}
    assert {(a["page_id"], orders[a["order_id"]]) for a in store.rows(select(db.associations))} == {
        (pages[0]["id"], "Shipment 00001"), (pages[1]["id"], "Shipment 00002")}


def test_tracker_mode_reports_the_new_error_codes(store, tmp_path):
    from ocr_workspace import ocr
    from ocr_workspace.processing import process_page
    etl.ingest_tracker(store, tracker(tmp_path / "orders.csv", [
        order("RO-0000001", "W-0000001"), order("SO-0000002", "Shipment 00001")]))
    pages = blank_scan(store, tmp_path / "scan.pdf", pages=8)
    responses = [
        (None, "identifier_not_found"),
        ("WO-990001", "identifier_not_found"),  # The retired prefix is not an identifier.
        ("W-0000999", "unknown_order"),
        ("Shipment 00999", "unknown_order"),
        ("Shipment 0000001", "unknown_order"),  # Same digits as the work order, but a different document.
        (ocr.parse_identifier("Rental Order No. RO-0000001 Work Order No. W-0000001 Sales Order No. SO-0000002"),
         "rental_and_sales_numbers_on_one_page"),
        (ocr.parse_identifier("Rental Order No. RO-0000001 Shipment No. 00001"), "rental_and_sales_numbers_on_one_page"),
        (ocr.parse_identifier("Sales Order No. SO-0000002 Work Order No. W-0000001"), "rental_and_sales_numbers_on_one_page"),
    ]
    for page, (response, code) in zip(pages, responses):
        result = process_page(store, page["id"], extractor=lambda *a, **k: response)
        assert (result["status"], result["error_code"]) == ("no_match", code), response
    # A parent order is never the page's own document: reading only it cannot match a work order or shipment.
    for parent in ("RO-0000001", "SO-0000002"):
        only_parent = process_page(store, pages[0]["id"], extractor=lambda *a, **k: parent)
        assert (only_parent["status"], only_parent["identifier"]) == ("no_match", parent)
    assert store.rows(select(db.associations)) == []


def test_postgres_ddl_has_explicit_schema_and_constraints():
    ddl = str(CreateTable(db.orders).compile(dialect=postgresql.dialect()))
    assert "core.orders" in ddl and "FOREIGN KEY" in ddl and "UNIQUE" in ddl
    assert "CHECK" in ddl


@pytest.mark.parametrize("response", ["0000001", "OD-0000001", "WO-0000001", "TK-0000001"])
def test_injected_value_without_a_w_shipment_ro_or_so_form_is_not_an_identifier(store, tmp_path, response):
    from ocr_workspace.processing import process_page
    rows = [order("RO-0000001", "W-0000001"), order("SO-0000002", "Shipment 0000001")]
    etl.ingest_tracker(store, tracker(tmp_path / "orders.csv", rows))
    page = blank_scan(store, tmp_path / "scan.pdf")[0]
    result = process_page(store, page["id"], extractor=lambda *a, **k: response)
    assert result["status"] == "no_match"
    assert store.rows(select(db.associations)) == []
    assert (result["identifier"], result["error_code"]) == (None, "identifier_not_found")


def test_work_order_and_shipment_with_the_same_digits_stay_separate_orders(store, tmp_path):
    from ocr_workspace.ocr import ParsedIdentifier
    from ocr_workspace.processing import process_page
    rows = [order("RO-0000001", "W-0000001"), order("SO-0000002", "Shipment 0000001")]
    etl.ingest_tracker(store, tracker(tmp_path / "orders.csv", rows))
    pages = blank_scan(store, tmp_path / "overlap.pdf", pages=2)
    assert process_page(store, pages[0]["id"], extractor=lambda *a, **k: "Shipment 0000001")["status"] == "success"
    assert process_page(store, pages[1]["id"], extractor=lambda *a, **k: ParsedIdentifier("work_order", "W-0000001"))["status"] == "success"
    orders = {row["order_number"]: row["id"] for row in store.rows(select(db.orders))}
    associations = store.rows(select(db.associations))
    assert {(a["page_id"], a["order_id"]) for a in associations} == {
        (pages[0]["id"], orders["Shipment 0000001"]), (pages[1]["id"], orders["W-0000001"])}


def test_schema_version_6_database_drops_the_shipment_column_and_keeps_its_rows(tmp_path):
    store = db.Store(db.sqlite_url(tmp_path / "legacy.sqlite"))
    try:
        store.migrate()
        rows = [order("RO-0000001", "W-0000001", Expected_Pages="6"),
                order("SO-0000002", "Shipment 00001", Expected_Pages="3")]
        etl.ingest_tracker(store, tracker(tmp_path / "orders.csv", rows))
        blank_scan(store, tmp_path / "scan.pdf")
        process_batch(store, extractor=lambda *a, **k: "W-0000001")
        # Rebuild the version 6 shape: old order prefixes, a sale with no parent order, and a separate shipment number.
        with store.engine.begin() as connection:
            sale = connection.scalar(select(db.orders.c.id).where(db.orders.c.order_number == "Shipment 00001"))
            parent = connection.scalar(select(db.rental_tickets.c.rental_id).where(db.rental_tickets.c.order_id == sale))
            connection.execute(db.rental_tickets.delete().where(db.rental_tickets.c.order_id == sale))
            connection.execute(db.rental_orders.delete().where(db.rental_orders.c.id == parent))
            connection.execute(db.orders.update().where(db.orders.c.id == sale).values(order_number="SO-904001"))
            connection.execute(db.orders.update().where(db.orders.c.order_number == "W-0000001").values(order_number="WO-900001"))
            connection.execute(db.rental_orders.update().values(rental_number="RO-800001"))
            connection.exec_driver_sql("ALTER TABLE orders ADD COLUMN shipment_number VARCHAR(80)")
            connection.exec_driver_sql("UPDATE orders SET shipment_number = substr(order_number, 4)")
            connection.execute(db.versions.delete().where(db.versions.c.version == 7))
        with store.engine.connect() as connection:
            assert "shipment_number" in [r[1] for r in connection.exec_driver_sql("PRAGMA table_info(orders)")]
            assert connection.scalar(select(func.max(db.versions.c.version))) == 6

        def contents():
            return {table.name: store.rows(select(table).order_by(*table.primary_key.columns))
                    for table in db.metadata.sorted_tables if table is not db.versions}

        snapshot = contents()
        assert len(snapshot["orders"]) == 2 and len(snapshot["order_document_pages"]) == 1
        assert len(snapshot["rental_orders"]) == len(snapshot["rental_order_tickets"]) == 1
        store.migrate()
        store.migrate()  # Applying the migration twice changes nothing.
        with store.engine.connect() as connection:
            columns = [r[1] for r in connection.exec_driver_sql("PRAGMA table_info(orders)")]
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert "shipment_number" not in columns
        assert columns == [column.name for column in db.orders.columns]
        assert [r["version"] for r in store.rows(select(db.versions).order_by(db.versions.c.version))] == [1, 2, 3, 4, 5, 6, 7]
        assert contents() == snapshot
        # The upgraded database keeps working: the unique order number still holds and new rows load.
        assert [r["Order_ID"] for r in store.order_rows()] == ["SO-904001", "WO-900001"]
        with pytest.raises(IntegrityError), store.engine.begin() as connection:
            connection.execute(db.orders.insert().values(**dict(snapshot["orders"][0], id=db.uid())))
        more = [order("RO-0000001", "W-0000001", Expected_Pages="6"), order("SO-0000002", "Shipment 00001", Expected_Pages="1")]
        assert etl.ingest_tracker(store, tracker(tmp_path / "more.csv", more))["rows_loaded"] == 2
        assert store.counts()["orders"] == 4
        assert sorted(r["rental_number"] for r in store.rows(select(db.rental_orders))) == [
            "RO-0000001", "RO-800001", "SO-0000002"]
    finally:
        store.close()


def test_database_newer_than_this_application_is_refused(tmp_path):
    store = db.Store(db.sqlite_url(tmp_path / "future.sqlite"))
    try:
        store.migrate()
        with store.engine.begin() as connection:
            connection.execute(db.versions.insert().values(version=8, applied_at=db.utcnow()))
        with pytest.raises(ValueError, match="newer than this application"):
            store.migrate()
    finally:
        store.close()
