"""
Shared OCR utility — Azure AI Document Intelligence (prebuilt-read).
Only the top-right corner of each image is sent to Azure (privacy crop).
The crop is intended to capture the order number fields (RO, SO, W, Shipment).
Verify the crop against your document layout before using private documents.
"""
import json
import os
import re
import logging
from io import BytesIO
from dataclasses import dataclass, field
from typing import Literal
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)

DocumentIntelligenceClient = None
AnalyzeDocumentRequest = None
AzureKeyCredential = None


def _get_azure_ocr_types():
    """Import Azure OCR classes only when an OCR call is actually made."""
    global DocumentIntelligenceClient, AnalyzeDocumentRequest, AzureKeyCredential
    if DocumentIntelligenceClient is None:
        from azure.ai.documentintelligence import DocumentIntelligenceClient as _Client
        DocumentIntelligenceClient = _Client
    if AnalyzeDocumentRequest is None:
        from azure.ai.documentintelligence.models import AnalyzeDocumentRequest as _Request
        AnalyzeDocumentRequest = _Request
    if AzureKeyCredential is None:
        from azure.core.credentials import AzureKeyCredential as _Credential
        AzureKeyCredential = _Credential
    return DocumentIntelligenceClient, AnalyzeDocumentRequest, AzureKeyCredential

# PRIVACY BOUNDARY — DO NOT WIDEN.
# Crop to top-right corner: captures only the order number fields (RO, SO, W, Shipment)
# that need to reach Azure Document Intelligence. Customer names,
# addresses, signatures, pricing, and line items stay on-premise.
# If OCR misreads identifiers, fix it in the text/regex logic below — never
# by enlarging this window.
HEADER_CROP_HEIGHT = 0.25   # top 25% of page
HEADER_CROP_WIDTH = 0.50    # right 50% of page


def _crop_header(image_bytes: bytes, height_ratio: float = HEADER_CROP_HEIGHT, width_ratio: float = HEADER_CROP_WIDTH) -> bytes:
    """
    Crop to the top-right corner where order numbers live.
    Privacy: only the number fields are sent to Azure — no addresses,
    no signatures, no customer details, no company info.
    """
    img = Image.open(BytesIO(image_bytes))
    w, h = img.size
    crop_box = (int(w * (1 - width_ratio)), 0, w, int(h * height_ratio))
    cropped = img.crop(crop_box)
    buf = BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue()


@dataclass(frozen=True)
class ParsedIdentifier:
    kind: Literal["work_order", "shipment", "rental_order", "sales_order"]
    value: str
    identifiers: dict = field(default_factory=dict, compare=False)


# Bump whenever identifier parsing changes: cached provider results parsed by
# an older version are ignored, so a regex fix is never hidden by the cache.
PARSER_VERSION = 3

# Bounded provider retries. azure-core retries 408/429/5xx and transport
# failures with exponential backoff and honours Retry-After; the explicit
# timeouts stop one stalled page from hanging the intake worker.
CLIENT_OPTIONS = {
    "retry_total": 4,
    "retry_backoff_factor": 1.0,
    "retry_backoff_max": 30,
    "connection_timeout": 10,
    "read_timeout": 60,
}

_client = None
_client_config = None


def _get_client(endpoint: str, key: str):
    """Reuse one provider client (and its connection pool) across pages."""
    global _client, _client_config
    client_cls, _, credential_cls = _get_azure_ocr_types()
    config = (client_cls, endpoint, key)
    if _client is None or _client_config != config:
        _client = client_cls(endpoint=endpoint, credential=credential_cls(key), **CLIENT_OPTIONS)
        _client_config = config
    return _client


def _capture_sample(raw_text: str, parsed: Optional["ParsedIdentifier"]) -> None:
    """Opt-in local capture of header text for promoting cases into the golden corpus."""
    target = os.getenv("OCR_CAPTURE_PATH", "").strip()
    if not target:
        return
    record = {"text": re.sub(r"\s+", " ", raw_text).strip(),
              "kind": parsed.kind if parsed else None, "value": parsed.value if parsed else None}
    try:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError:
        logger.warning("OCR sample capture failed; continuing without it")


def extract_order_identity(
    image_bytes: bytes,
    crop_header: bool = True,
    crop_ratio: float = HEADER_CROP_HEIGHT,
) -> Optional[ParsedIdentifier]:
    """
    Send image to Azure Document Intelligence (prebuilt-read) and extract
    the RO, SO, W or Shipment number via regex.
    When crop_header=True (default), only the top portion of the image is sent.
    Use crop_ratio to control how much (0.25 default for both PDFs and phone photos).
    Returns the matched string or None.
    """
    endpoint = os.getenv("AZURE_DOC_INTEL_ENDPOINT")
    key = os.getenv("AZURE_DOC_INTEL_KEY")
    if not endpoint or not key:
        raise RuntimeError("AZURE_DOC_INTEL_ENDPOINT and AZURE_DOC_INTEL_KEY must be set.")

    if crop_header:
        image_bytes = _crop_header(image_bytes, height_ratio=crop_ratio)
        logger.debug("Cropped image to top %d%% for privacy", int(crop_ratio * 100))

    _, request_cls, _ = _get_azure_ocr_types()
    client = _get_client(endpoint, key)
    poller = client.begin_analyze_document(
        "prebuilt-read",
        request_cls(bytes_source=image_bytes),
    )
    result = poller.result()

    raw_text = " ".join(
        line.content
        for page in (result.pages or [])
        for line in (page.lines or [])
    )

    parsed = parse_identifier(raw_text)
    _capture_sample(raw_text, parsed)
    return parsed


# The only identifiers in the system.
#   RO-0000002      rental order   \  parent orders; both draw their number
#   SO-0000001      sales order    /  from one shared count
#   W-0000001       work order, created from a rental order (three pages)
#   Shipment 00001  shipment, created from a sales order (one page)
# A page prints its parent and its own document: RO + W, or SO + Shipment.
_IDENTIFIER_PATTERNS = {
    "rental_order": r"\b(RO)-(\d{4,12})\b",
    "sales_order": r"\b(SO)-(\d{4,12})\b",
    "work_order": r"\b(W)-(\d{4,12})\b",
    "shipment": r"\b(Shipment)\s*(?:No\.?|Number|Nbr|#)?\s*[.:#]?\s*(\d{3,12})(?!\d)",
}
PARENT_OF = {"work_order": "rental_order", "shipment": "sales_order"}


def canonical_identifier(kind: str, digits: str) -> str:
    """Printed digits are kept as printed, including leading zeros."""
    if kind == "shipment":
        return f"Shipment {digits}"
    return {"rental_order": "RO", "sales_order": "SO", "work_order": "W"}[kind] + f"-{digits}"


def parse_document_identifiers(raw_text: str) -> dict:
    """Read every RO, SO, W and Shipment number in one provider response, each in its own namespace."""
    text = re.sub(r"\s+", " ", raw_text).strip()
    # Optional exact header strings, separated by |; configure for your own forms.
    for noise in os.getenv("OCR_HEADER_NOISE", "").split("|"):
        if noise.strip():
            text = text.replace(noise.strip(), "")
    values = {}
    for kind, pattern in _IDENTIFIER_PATTERNS.items():
        match = re.search(pattern, text, re.I)
        if match:
            values[kind] = canonical_identifier(kind, match.group(2))
    return values


def mixed_families(identifiers: dict) -> bool:
    """True when a page prints rental numbers (RO, W) together with sales numbers (SO, Shipment)."""
    rental = identifiers.get("rental_order") or identifiers.get("work_order")
    sale = identifiers.get("sales_order") or identifiers.get("shipment")
    return bool(rental and sale)


def parse_identifier(raw_text: str) -> Optional[ParsedIdentifier]:
    """Parse provider text without cloud calls.

    The primary identifier is the page's own document: its work order or its
    shipment. A page showing only its parent order still reports that parent.
    """
    identifiers = parse_document_identifiers(raw_text)
    for kind in ("work_order", "shipment", "rental_order", "sales_order"):
        if kind in identifiers:
            return ParsedIdentifier(kind, identifiers[kind], identifiers)
    # Do not retain OCR content in application logs. Header crops can contain
    # order metadata even though full tickets are never sent to OCR.
    logger.warning("OCR: no RO, SO, W or Shipment number found in the header")
    return None
