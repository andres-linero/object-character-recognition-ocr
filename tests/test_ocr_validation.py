"""Validate staging and honest page-level comparisons without any provider calls."""
import json

import pymupdf as fitz
import pytest
from scripts import create_demo_data as demo
from scripts import validate_ocr as validation


@pytest.fixture
def staged(tmp_path, monkeypatch):
    for number, start in [(2, 101), (3, 111)]:
        folder = tmp_path / f"demo_batches/batch_{number:02d}"
        manifest = demo.generate_dataset(folder, count=10, seed=number, start_index=start,
                                        min_pages=6, max_pages=6, rasterize=False)
        with fitz.open() as combined:
            for ticket in manifest["tickets"]:
                with fitz.open(folder / ticket["pdf"]) as packet:
                    combined.insert_pdf(packet)
            combined.save(tmp_path / f"demo_batches/batch_{number:02d}_60_pages.pdf")
    monkeypatch.setattr(validation, "ROOT", tmp_path)
    monkeypatch.setattr(validation, "INPUT", tmp_path / "demo_batches/ocr_validation/incoming_scans")
    monkeypatch.setattr(validation, "RUNTIME", tmp_path / "demo_runtime")
    monkeypatch.setattr(validation, "DATABASE", tmp_path / "demo_runtime/ocr_validation.sqlite")
    monkeypatch.setattr(validation, "REPORT", tmp_path / "demo_runtime/ocr_validation_report.json")
    monkeypatch.setattr(validation, "dotenv_values", lambda _: {
        "AZURE_DOC_INTEL_ENDPOINT": "https://example.test", "AZURE_DOC_INTEL_KEY": "test-only"})
    monkeypatch.setattr(validation.time, "sleep", lambda _: None)
    return tmp_path


def test_staging_is_repeatable_and_preserves_source_packets(staged):
    source = staged / "demo_batches/batch_02_60_pages.pdf"
    before = source.read_bytes()
    store, todo = validation.prepare()
    assert len(todo) == 120
    assert store.counts()["orders"] == 20
    assert store.counts()["document_pages"] == 120
    assert store.counts()["ocr_attempts"] == 0
    store.close()
    store, again = validation.prepare()
    assert {p["page_id"] for p in todo} == {p["page_id"] for p in again}
    assert store.counts()["documents"] == 2
    assert source.read_bytes() == before
    store.close()


def test_report_rejects_wrong_valid_order_as_mismatch(staged):
    store, todo = validation.prepare()
    assert todo[0]["order_number"] == "W-0000076" and "shipment" not in todo[0]
    result = validation.write_report(todo, {
        todo[0]["page_id"]: dict(status="success", identifier="W-0000077"),
        todo[1]["page_id"]: dict(status="error", identifier=None, error_code="HTTP401"),
        todo[2]["page_id"]: dict(status="success", identifier="W-0000076")})
    assert result["mismatch"] == result["error"] == result["passed"] == 1
    assert result["pending"] == 117
    assert result["expected_tickets"] == 20
    assert [page["expected"] for page in result["pages"][:3]] == ["W-0000076"] * 3
    # Both batches hold work orders and shipments; each page is expected under its own document number.
    assert {page["expected"][:2] for page in result["pages"]} == {"W-", "Sh"}
    assert "Shipment 00026" in {page["expected"] for page in result["pages"]}
    assert not any(page["expected"].startswith(("RO-", "SO-", "WO-")) for page in result["pages"])
    assert "test-only" not in validation.REPORT.read_text()
    store.close()


def test_failed_smoke_does_not_submit_remaining_pages(staged, monkeypatch):
    calls = []
    def denied(store, page, **kwargs):
        calls.append(page)
        return dict(status="error", identifier=None, error_code="HTTP401")
    monkeypatch.setattr(validation, "process_page", denied)
    monkeypatch.setattr("sys.argv", ["validate_ocr.py", "--limit", "120"])
    assert validation.main() == 1
    assert len(calls) == 1
    report = json.loads(validation.REPORT.read_text())
    assert report["error"] == 1 and report["pending"] == 119
