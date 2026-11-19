import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ocr_workspace import ocr


class _FakePoller:
    def __init__(self, text: str):
        self._text = text

    def result(self):
        line = SimpleNamespace(content=self._text)
        page = SimpleNamespace(lines=[line])
        return SimpleNamespace(pages=[page])


class _FakeClient:
    response_text = ""

    def __init__(self, *args, **kwargs):
        pass

    def begin_analyze_document(self, model_id, request):
        return _FakePoller(self.response_text)


@pytest.fixture(autouse=True)
def _ocr_env(monkeypatch):
    monkeypatch.setenv("AZURE_DOC_INTEL_ENDPOINT", "https://example.test")
    monkeypatch.setenv("AZURE_DOC_INTEL_KEY", "fake-key")
    monkeypatch.setattr(ocr, "DocumentIntelligenceClient", _FakeClient)


def test_extracts_shipment_number_from_labeled_field():
    _FakeClient.response_text = "Delivery Ticket Shipment No. 003501 Customer 22"
    result = ocr.extract_order_identity(b"unused", crop_header=False)
    assert result.value == "3501"


def test_extracts_work_order_number():
    _FakeClient.response_text = "Delivery Ticket Work Order No. W-108624"
    result = ocr.extract_order_identity(b"unused", crop_header=False)
    assert result.value == "W-108624"


def test_rejects_non_ticket_text():
    _FakeClient.response_text = "Random cover sheet with customer notes only"
    result = ocr.extract_order_identity(b"unused", crop_header=False)
    assert result is None


def test_header_noise_does_not_get_matched_as_order_number(monkeypatch):
    monkeypatch.setenv("OCR_HEADER_NOISE", "100 Example Street Example City 12345|Office: 555-0100 example.test")
    _FakeClient.response_text = (
        "Delivery Ticket 100 Example Street Example City 12345 "
        "Office: 555-0100 example.test"
    )
    result = ocr.extract_order_identity(b"unused", crop_header=False)
    assert result is None


def test_missing_credentials_raises(monkeypatch):
    monkeypatch.delenv("AZURE_DOC_INTEL_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_DOC_INTEL_KEY", raising=False)
    with pytest.raises(RuntimeError):
        ocr.extract_order_identity(b"unused", crop_header=False)


def test_single_response_keeps_order_ticket_and_shipment_in_separate_namespaces():
    result = ocr.parse_identifier('Rental Order No. RO-810001 Customer Order No. CO-123456 Ticket No. TK-992001 Shipment No. 904001')
    assert result.identifiers == {'rental_order': 'RO-810001', 'customer_order': 'CO-123456', 'work_order': 'TK-992001', 'shipment': '904001'}
    assert result.kind == 'rental_order'
    assert ocr.parse_identifier('Customer Order No. 904001').kind == 'customer_order'
    assert ocr.parse_identifier('Shipment No. 904001').kind == 'shipment'
    assert ocr.parse_identifier('Work Order No. 904001').kind == 'work_order'
    agreement = ocr.parse_identifier('Rental Agreement No. RA-701062 Work Order No. W-991062 Shipment No. 901062')
    assert agreement.kind == 'rental_order' and agreement.value == 'RO-701062'
    assert agreement.identifiers['rental_order'] == 'RO-701062'


@pytest.mark.parametrize("case", json.loads(
    (Path(__file__).parent / "fixtures/ocr_golden.json").read_text()),
    ids=lambda case: case["name"])
def test_golden_identifiers_keep_namespace_and_reject_noise(case):
    result = ocr.parse_identifier(case["text"])
    assert (result.kind if result else None) == case["kind"]
    assert (result.value if result else None) == case["value"]


def test_provider_client_is_reused_with_bounded_retries(monkeypatch):
    created = []

    class _CountingClient(_FakeClient):
        def __init__(self, *args, **kwargs):
            created.append(kwargs)

    monkeypatch.setattr(ocr, "DocumentIntelligenceClient", _CountingClient)
    _FakeClient.response_text = "Delivery Ticket Shipment No. 003501"
    for _ in range(3):
        assert ocr.extract_order_identity(b"unused", crop_header=False).value == "3501"
    assert len(created) == 1
    assert created[0]["retry_total"] == 4 and created[0]["read_timeout"] == 60


def test_sample_capture_is_opt_in_and_appends_reviewable_records(tmp_path, monkeypatch):
    target = tmp_path / "samples.jsonl"
    _FakeClient.response_text = "Delivery Ticket Shipment\nNo. 003501"
    ocr.extract_order_identity(b"unused", crop_header=False)
    assert not target.exists()
    monkeypatch.setenv("OCR_CAPTURE_PATH", str(target))
    ocr.extract_order_identity(b"unused", crop_header=False)
    assert json.loads(target.read_text()) == {
        "text": "Delivery Ticket Shipment No. 003501", "kind": "shipment", "value": "3501"}
