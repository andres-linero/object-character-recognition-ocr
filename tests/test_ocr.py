from types import SimpleNamespace

import pytest

import ocr


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
    result = ocr.extract_order_number(b"unused", crop_header=False)
    assert result == "3501"


def test_extracts_work_order_number():
    _FakeClient.response_text = "Delivery Ticket Work Order No. W-108624"
    result = ocr.extract_order_number(b"unused", crop_header=False)
    assert result == "W-108624"


def test_rejects_non_ticket_text():
    _FakeClient.response_text = "Random cover sheet with customer notes only"
    result = ocr.extract_order_number(b"unused", crop_header=False)
    assert result is None


def test_header_noise_does_not_get_matched_as_order_number(monkeypatch):
    monkeypatch.setenv("OCR_HEADER_NOISE", "100 Example Street Example City 12345|Office: 555-0100 example.test")
    _FakeClient.response_text = (
        "Delivery Ticket 100 Example Street Example City 12345 "
        "Office: 555-0100 example.test"
    )
    result = ocr.extract_order_number(b"unused", crop_header=False)
    assert result is None


def test_missing_credentials_raises(monkeypatch):
    monkeypatch.delenv("AZURE_DOC_INTEL_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_DOC_INTEL_KEY", raising=False)
    with pytest.raises(RuntimeError):
        ocr.extract_order_number(b"unused", crop_header=False)
