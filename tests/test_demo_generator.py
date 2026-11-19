"""Check generated data contracts and recoverable output handling without Azure."""
import csv
import json
import re

import pymupdf as fitz
from openpyxl import load_workbook
import pandas as pd
import pytest

from ocr_workspace import ocr
from scripts import create_demo_data as demo


def test_seed_reproduces_business_records_and_complete_copy_sets():
    first = demo.build_tickets()
    assert first == demo.build_tickets()
    assert first != demo.build_tickets(seed=43)
    assert len(first) == 100
    assert len({t.order_id for t in first}) == 100
    assert {t.page_count for t in first} == {6, 9, 12}
    assert all(t.contact_email.endswith("@example.test") for t in first)
    assert all(t.customer.startswith("Demo ") for t in first)
    assert all(t.dispatcher.startswith("Dispatch Desk ") for t in first)


def test_every_fourth_record_is_a_shipment_under_a_sales_order_and_the_others_are_work_orders_under_a_rental_order():
    tickets = demo.build_tickets(count=8)
    assert [t.order_id for t in tickets] == [
        "W-0000001", "W-0000002", "W-0000003", "Shipment 00001",
        "W-0000004", "W-0000005", "W-0000006", "Shipment 00002"]
    # RO and SO numbers come from one shared count: 1, 2, 3, 4 with no number used twice.
    assert [t.parent_order_number for t in tickets] == [
        "RO-0000001", "RO-0000001", "RO-0000001", "SO-0000002",
        "RO-0000003", "RO-0000003", "RO-0000003", "SO-0000004"]
    assert [t.order_type for t in tickets] == ["RENTAL"] * 3 + ["SALE"] + ["RENTAL"] * 3 + ["SALE"]
    for group in (tickets[:4], tickets[4:]):
        assert len({(t.customer, t.address) for t in group}) == 1
    for ticket in tickets:
        sale = ticket.order_type == "SALE"
        assert ticket.document_types == (demo.SALES_DOCUMENT_TYPES if sale else demo.RENTAL_DOCUMENT_TYPES)
        row = ticket.tracker_row()
        assert tuple(row) == demo.TRACKER_COLUMNS
        assert row["Work order"] == ticket.order_id and row["Order_Type"] == ticket.order_type
        assert row["Order"] == ticket.parent_order_number
        assert "Order_ID" not in row and "Rental_Order" not in row
        assert not hasattr(ticket, "shipment") and not hasattr(ticket, "rental_order")
        assert not hasattr(ticket, "parent_rental_number")
    assert demo.TRACKER_COLUMNS[:2] == ("Order", "Work order")
    everything = demo.build_tickets()
    assert sum(t.order_type == "SALE" for t in everything) == 25
    rentals = {t.parent_order_number for t in everything if t.order_type == "RENTAL"}
    sales = {t.parent_order_number for t in everything if t.order_type == "SALE"}
    assert len(rentals) == len(sales) == 25
    assert all(re.fullmatch(r"RO-\d{7}", number) for number in rentals)
    assert all(re.fullmatch(r"SO-\d{7}", number) for number in sales)
    # One shared count: the digits of all parent orders are 1..50, each used once.
    assert sorted(int(number.split("-")[1]) for number in rentals | sales) == list(range(1, 51))
    assert all(re.fullmatch(r"W-\d{7}|Shipment \d{5}", t.order_id) for t in everything)
    assert [int(t.order_id.split("-")[1]) for t in everything if t.order_type == "RENTAL"] == list(range(1, 76))
    assert [int(t.order_id.split()[1]) for t in everything if t.order_type == "SALE"] == list(range(1, 26))


@pytest.mark.parametrize("position,order_id,parent", [
    (0, "W-0000001", "RO-0000001"), (3, "Shipment 00001", "SO-0000002")])
def test_vector_papers_keep_matching_identifier_inside_every_ocr_crop(tmp_path, position, order_id, parent):
    ticket = demo.build_tickets(count=4, min_pages=12, max_pages=12)[position]
    assert (ticket.order_id, ticket.parent_order_number) == (order_id, parent)
    sale = ticket.order_type == "SALE"
    pdf_path = tmp_path / "packet.pdf"
    pages = demo.write_ticket_pdf(pdf_path, ticket, rasterize=False)
    expected_types = demo.SALES_DOCUMENT_TYPES if sale else demo.RENTAL_DOCUMENT_TYPES
    assert [p["document_type"] for p in pages] == [kind for kind in expected_types for _ in range(4)]
    assert [p["copy"] for p in pages] == list(demo.COPY_NAMES) * 3
    assert {p["expected_ocr_id"] for p in pages} == {ticket.order_id}
    with fitz.open(pdf_path) as doc:
        assert len(doc) == 12
        for page, expected in zip(doc, pages):
            crop = fitz.Rect(page.rect.width / 2, 0, page.rect.width, page.rect.height / 4)
            header = page.get_text(clip=crop)
            parsed = ocr.parse_identifier(header)
            assert not ocr.mixed_families(parsed.identifiers)
            if sale:
                assert "SALES ORDER" in header
                assert f"Sales Order No. {parent}" in header
                assert "Shipment No. 00001" in header
                # A sales page never carries a rental or work order number.
                assert "RO-" not in header and "W-" not in header
                assert (parsed.kind, parsed.value) == ("shipment", "Shipment 00001")
                assert parsed.identifiers == {"sales_order": parent, "shipment": "Shipment 00001"}
            else:
                assert "RENTAL ORDER" in header
                assert f"Rental Order No. {parent}" in header
                assert f"Work Order No. {ticket.order_id}" in header
                # A rental page never carries a sales order or shipment number.
                assert "SO-" not in header and "Shipment" not in header
                assert (parsed.kind, parsed.value) == ("work_order", ticket.order_id)
                assert parsed.identifiers == {"rental_order": parent, "work_order": ticket.order_id}
            assert "WO-" not in header
            text = page.get_text()
            assert "SYNTHETIC DEMO" in text
            assert expected["document_type"] in text
            assert ticket.contact_email in text
            assert "NORTHSTAR EQUIPMENT" in text
            if expected["document_type"] == "Delivery Acknowledgement":
                assert "NOT SIGNED - DEMO" in text
            assert not page.get_images()


def test_default_scan_pages_are_image_only(tmp_path):
    ticket = demo.build_tickets(count=1, min_pages=6, max_pages=6)[0]
    pdf_path = tmp_path / "scan.pdf"
    demo.write_ticket_pdf(pdf_path, ticket)
    with fitz.open(pdf_path) as doc:
        assert len(doc) == 6
        for page in doc:
            assert page.get_text() == ""
            assert len(page.get_images()) == 1
            image = page.get_images()[0]
            assert image[2:4] == (1020, 1320)


def test_dataset_matches_manifest_csv_and_workbook(tmp_path):
    target = tmp_path / "dataset"
    result = demo.generate_dataset(target, count=5, seed=8, rasterize=False)
    assert json.loads((target / "manifest.json").read_text()) == result
    assert result["count"] == 5
    assert result["total_pages"] == sum(t["page_count"] for t in result["tickets"])
    assert sorted(p.name for p in target.iterdir()) == ["incoming_scans", "manifest.json", "orders.csv", "orders.xlsx"]
    csv_rows = list(csv.DictReader((target / "orders.csv").open()))
    assert len(csv_rows) == 5
    assert list(csv_rows[0]) == list(demo.TRACKER_COLUMNS)
    assert list(csv_rows[0])[:2] == ["Order", "Work order"]
    assert not {"Order_ID", "Rental_Order", "SO"} & set(csv_rows[0])
    assert {r["Work order"] for r in csv_rows} == {t["order_id"] for t in result["tickets"]}
    assert [r["Work order"] for r in csv_rows] == ["W-0000001", "W-0000002", "W-0000003", "Shipment 00001", "W-0000004"]
    assert [r["Order"] for r in csv_rows] == ["RO-0000001", "RO-0000001", "RO-0000001", "SO-0000002", "RO-0000003"]
    assert [r["Order_Type"] for r in csv_rows] == ["RENTAL", "RENTAL", "RENTAL", "SALE", "RENTAL"]
    wb = load_workbook(target / "orders.xlsx", read_only=True)
    for sheet in wb:
        assert [c.value for c in next(sheet.iter_rows())] == list(demo.TRACKER_COLUMNS)
    wb.close()
    workbook_rows = {str(row["Work order"]): row for row in pd.concat(pd.read_excel(target / "orders.xlsx", sheet_name=None, dtype=str).values()).to_dict("records")}
    assert len(workbook_rows) == 5
    for record in result["tickets"]:
        row = workbook_rows[record["order_id"]]
        assert "shipment" not in record and "rental_order" not in record
        assert row["Order_Type"] == record["order_type"]
        assert "parent_rental_number" not in record
        assert row["Order"] == record["parent_order_number"]
        assert record["pdf"] == f"incoming_scans/demo_order_{record['order_id'].replace(' ', '_')}.pdf"
        assert " " not in record["pdf"]
        assert row["Customer_name"] == record["customer"]
        pdf_path = target / record["pdf"]
        with fitz.open(pdf_path) as doc:
            assert len(doc) == record["page_count"] == len(record["pages"])


def test_existing_outputs_are_preserved_unless_explicitly_owned_and_overwritten(tmp_path):
    target = tmp_path / "dataset"
    demo.generate_dataset(target, count=2, rasterize=False)
    previous = (target / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        demo.generate_dataset(target, count=1, rasterize=False)
    assert (target / "manifest.json").read_bytes() == previous
    demo.generate_dataset(target, count=1, rasterize=False, overwrite=True)
    assert len(list((target / "incoming_scans").glob("*.pdf"))) == 1
    (target / "keep.txt").write_text("unrelated file")
    with pytest.raises(ValueError, match="unexpected files"):
        demo.generate_dataset(target, count=1, rasterize=False, overwrite=True)
    assert (target / "keep.txt").read_text() == "unrelated file"


@pytest.mark.parametrize("count,minimum,maximum", [(0, 6, 12), (1001, 6, 12), (1, 12, 6), (1, 7, 8), (1, 2, 12), (1, 6, 13)])
def test_invalid_inputs_fail_before_writing(tmp_path, count, minimum, maximum):
    target = tmp_path / "dataset"
    with pytest.raises(ValueError):
        demo.generate_dataset(target, count=count, min_pages=minimum, max_pages=maximum)
    assert not target.exists()


def test_overwrite_does_not_delete_non_generator_directory(tmp_path):
    target = tmp_path / "real-scans"
    target.mkdir()
    (target / "important.pdf").write_bytes(b"untouched")
    with pytest.raises(ValueError, match="generator-owned"):
        demo.generate_dataset(target, count=1, overwrite=True)
    assert (target / "important.pdf").read_bytes() == b"untouched"


def test_additional_batches_use_nonoverlapping_identifiers(tmp_path):
    initial = demo.build_tickets(count=100)
    second = demo.build_tickets(count=10, start_index=101, min_pages=6, max_pages=6)
    third = demo.build_tickets(count=10, start_index=111, min_pages=6, max_pages=6)
    assert len({t.order_id for t in initial + second + third}) == 120
    # Parent numbers continue the one shared RO/SO count: no number is reused across batches or families.
    parents = {t.parent_order_number for t in initial + second + third}
    assert len({number.split("-")[1] for number in parents}) == len(parents) == 60
    assert sum(t.page_count for t in second) == sum(t.page_count for t in third) == 60
    output = tmp_path / "batch"
    result = demo.generate_dataset(output, count=1, start_index=101, rasterize=False)
    assert result["start_index"] == 101
    assert result["tickets"][0]["order_id"] == "W-0000076"
    assert result["tickets"][0]["parent_order_number"] == "RO-0000051"
    with pytest.raises(ValueError, match="index range"):
        demo.generate_dataset(tmp_path / "invalid", start_index=0)
    assert not (tmp_path / "invalid").exists()
