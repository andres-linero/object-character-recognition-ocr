"""Check generated data contracts and recoverable output handling without Azure."""
import csv
import json

import fitz
from openpyxl import load_workbook
import pytest

from scripts import create_demo_data as demo
import data_loader


def test_seed_reproduces_business_records_and_complete_copy_sets():
    first = demo.build_tickets()
    assert first == demo.build_tickets()
    assert first != demo.build_tickets(seed=43)
    assert len(first) == 100
    assert len({t.shipment for t in first}) == len({t.order_id for t in first}) == 100
    assert {t.page_count for t in first} == {6, 9, 12}
    assert all(t.contact_email.endswith("@example.test") for t in first)
    assert all(t.customer.startswith("Demo ") for t in first)
    assert all(t.dispatcher.startswith("Dispatch Desk ") for t in first)


def test_vector_papers_keep_matching_identifier_inside_every_ocr_crop(tmp_path):
    ticket = demo.build_tickets(count=1, min_pages=12, max_pages=12)[0]
    pdf_path = tmp_path / "packet.pdf"
    pages = demo.write_ticket_pdf(pdf_path, ticket, rasterize=False)
    assert [p["document_type"] for p in pages] == [kind for kind in demo.DOCUMENT_TYPES for _ in range(4)]
    assert [p["copy"] for p in pages] == list(demo.COPY_NAMES) * 3
    with fitz.open(pdf_path) as doc:
        assert len(doc) == 12
        for page, expected in zip(doc, pages):
            crop = fitz.Rect(page.rect.width / 2, 0, page.rect.width, page.rect.height / 4)
            header = page.get_text(clip=crop)
            assert f"Shipment No. {ticket.shipment}" in header
            assert ticket.order_id in header
            text = page.get_text()
            assert "SYNTHETIC DEMO" in text
            assert expected["document_type"] in text
            assert ticket.contact_email in text
            assert "NORTHSTAR DEMO EQUIPMENT" in text
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


def test_dataset_matches_manifest_csv_and_real_workbook_loader(tmp_path, monkeypatch):
    target = tmp_path / "dataset"
    result = demo.generate_dataset(target, count=5, seed=8, rasterize=False)
    assert json.loads((target / "manifest.json").read_text()) == result
    assert result["count"] == 5
    assert result["total_pages"] == sum(t["page_count"] for t in result["tickets"])
    assert sorted(p.name for p in target.iterdir()) == ["incoming_scans", "manifest.json", "orders.csv", "orders.xlsx"]
    csv_rows = list(csv.DictReader((target / "orders.csv").open()))
    assert len(csv_rows) == 5
    assert {r["SO"] for r in csv_rows} == {t["shipment"] for t in result["tickets"]}
    wb = load_workbook(target / "orders.xlsx", read_only=True)
    for sheet in wb:
        assert [c.value for c in next(sheet.iter_rows())] == list(demo.TRACKER_COLUMNS)
    wb.close()
    monkeypatch.setenv("EXCEL_PATH", str(target / "orders.xlsx"))
    monkeypatch.setattr(data_loader, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(data_loader, "EXCEL_CACHE_FILE", tmp_path / "cache" / "excel.pkl")
    loader = data_loader.DataLoader()
    assert len(loader.excel_df) == 5
    for record in result["tickets"]:
        row = loader.get_order_by_id(record["shipment"])
        assert row["Order_ID"] == record["order_id"]
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
