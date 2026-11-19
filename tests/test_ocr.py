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


def test_shipment_label_is_read_as_a_shipment_never_as_a_sales_order():
    _FakeClient.response_text = "Delivery Ticket Shipment No. 904001 Customer 22"
    result = ocr.extract_order_identity(b"unused", crop_header=False)
    assert (result.kind, result.value) == ("shipment", "Shipment 904001")
    assert result.identifiers == {"shipment": "Shipment 904001"}


def test_work_order_is_the_page_identity_and_keeps_its_rental_order():
    _FakeClient.response_text = "Rental Order No. RO-0000002 Work Order No. W-0000001"
    result = ocr.extract_order_identity(b"unused", crop_header=False)
    assert (result.kind, result.value) == ("work_order", "W-0000001")
    assert result.identifiers == {"rental_order": "RO-0000002", "work_order": "W-0000001"}


def test_shipment_is_the_page_identity_and_keeps_its_sales_order():
    _FakeClient.response_text = "Sales Order No. SO-0000001 Shipment No. 00001"
    result = ocr.extract_order_identity(b"unused", crop_header=False)
    assert (result.kind, result.value) == ("shipment", "Shipment 00001")
    assert result.identifiers == {"sales_order": "SO-0000001", "shipment": "Shipment 00001"}


def test_text_without_an_order_number_is_rejected():
    _FakeClient.response_text = "Random cover sheet with customer notes only"
    assert ocr.extract_order_identity(b"unused", crop_header=False) is None


def test_header_noise_does_not_get_matched_as_order_number(monkeypatch):
    monkeypatch.setenv("OCR_HEADER_NOISE", "Shipment No. 555010|Office: 555-0100 example.test")
    _FakeClient.response_text = "Delivery Ticket Shipment No. 555010 Office: 555-0100 example.test"
    assert ocr.extract_order_identity(b"unused", crop_header=False) is None


def test_missing_credentials_raises(monkeypatch):
    monkeypatch.delenv("AZURE_DOC_INTEL_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_DOC_INTEL_KEY", raising=False)
    with pytest.raises(RuntimeError):
        ocr.extract_order_identity(b"unused", crop_header=False)


def test_four_namespaces_exist_and_each_keeps_its_own_number():
    assert set(ocr._IDENTIFIER_PATTERNS) == {'rental_order', 'sales_order', 'work_order', 'shipment'}
    assert ocr.PARENT_OF == {'work_order': 'rental_order', 'shipment': 'sales_order'}
    assert ocr.PARSER_VERSION == 3
    rental = ocr.parse_identifier('Rental Order No. RO-0000002 Work Order No. W-0000001')
    assert (rental.kind, rental.value) == ('work_order', 'W-0000001')
    assert rental.identifiers == {'rental_order': 'RO-0000002', 'work_order': 'W-0000001'}
    sale = ocr.parse_identifier('Sales Order No. SO-0000001 Shipment No. 00001')
    assert (sale.kind, sale.value) == ('shipment', 'Shipment 00001')
    assert sale.identifiers == {'sales_order': 'SO-0000001', 'shipment': 'Shipment 00001'}
    # Only the parent was readable: reported as the parent, never as its document.
    assert ocr.parse_identifier('Rental Order No. RO-0000002').kind == 'rental_order'
    assert ocr.parse_identifier('Sales Order No. SO-0000001').kind == 'sales_order'
    # The same digits in different namespaces stay different identifiers.
    same = ocr.parse_document_identifiers('RO-0000001 W-0000001')
    assert same == {'rental_order': 'RO-0000001', 'work_order': 'W-0000001'}
    assert ocr.parse_document_identifiers('nothing printed here') == {}


def test_primary_identifier_prefers_the_document_over_its_parent():
    text = 'Shipment No. 00001 SO-0000001 W-0000001 RO-0000002'
    assert ocr.parse_identifier(text).kind == 'work_order'
    assert ocr.parse_identifier('Shipment No. 00001 SO-0000001 RO-0000002').kind == 'shipment'
    assert ocr.parse_identifier('SO-0000001 RO-0000002').kind == 'rental_order'
    assert ocr.parse_identifier('SO-0000001').kind == 'sales_order'


@pytest.mark.parametrize("kind,digits,expected", [
    ("rental_order", "0000002", "RO-0000002"), ("sales_order", "0000001", "SO-0000001"),
    ("work_order", "0000001", "W-0000001"), ("shipment", "00001", "Shipment 00001"),
    ("shipment", "904001", "Shipment 904001")])
def test_canonical_identifier_keeps_printed_digits_and_leading_zeros(kind, digits, expected):
    assert ocr.canonical_identifier(kind, digits) == expected


@pytest.mark.parametrize("identifiers,mixed", [
    ({"rental_order": "RO-0000002", "work_order": "W-0000001"}, False),
    ({"sales_order": "SO-0000001", "shipment": "Shipment 00001"}, False),
    ({"rental_order": "RO-0000002"}, False),
    ({"shipment": "Shipment 00001"}, False),
    ({}, False),
    ({"rental_order": "RO-0000002", "shipment": "Shipment 00001"}, True),
    ({"sales_order": "SO-0000001", "work_order": "W-0000001"}, True),
    ({"rental_order": "RO-0000002", "sales_order": "SO-0000001"}, True),
    ({"work_order": "W-0000001", "shipment": "Shipment 00001"}, True),
])
def test_mixed_families_flags_rental_numbers_printed_with_sales_numbers(identifiers, mixed):
    assert ocr.mixed_families(identifiers) is mixed


@pytest.mark.parametrize("case", json.loads(
    (Path(__file__).parent / "fixtures/ocr_golden.json").read_text()),
    ids=lambda case: case["name"])
def test_golden_identifiers_keep_namespace_and_reject_noise(case, monkeypatch):
    monkeypatch.delenv("OCR_HEADER_NOISE", raising=False)
    result = ocr.parse_identifier(case["text"])
    assert (result.kind if result else None) == case["kind"]
    assert (result.value if result else None) == case["value"]
    identifiers = ocr.parse_document_identifiers(case["text"])
    assert identifiers == case["identifiers"]
    assert (result.identifiers if result else {}) == case["identifiers"]
    assert ocr.mixed_families(identifiers) is case["mixed"]


def test_golden_corpus_covers_every_kind_both_families_and_the_retired_forms():
    cases = json.loads((Path(__file__).parent / "fixtures/ocr_golden.json").read_text())
    assert {case["kind"] for case in cases} == {"work_order", "shipment", "rental_order", "sales_order", None}
    assert any(case["mixed"] for case in cases)
    assert len({case["name"] for case in cases}) == len(cases)
    # No expectation may reintroduce the retired WO- prefix or a sales order derived from a shipment label.
    for case in cases:
        assert not str(case["value"] or "").startswith("WO-")
        assert not any(str(value).startswith("WO-") for value in case["identifiers"].values())
        if "SO-" not in case["text"].upper():
            assert "sales_order" not in case["identifiers"]


def test_provider_client_is_reused_with_bounded_retries(monkeypatch):
    created = []

    class _CountingClient(_FakeClient):
        def __init__(self, *args, **kwargs):
            created.append(kwargs)

    monkeypatch.setattr(ocr, "DocumentIntelligenceClient", _CountingClient)
    _FakeClient.response_text = "Delivery Ticket Shipment No. 003501"
    for _ in range(3):
        assert ocr.extract_order_identity(b"unused", crop_header=False).value == "Shipment 003501"
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
        "text": "Delivery Ticket Shipment No. 003501", "kind": "shipment", "value": "Shipment 003501"}
