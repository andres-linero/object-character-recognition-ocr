"""
Shared OCR utility — Azure AI Document Intelligence (prebuilt-read).
Only the top-right corner of each image is sent to Azure (privacy crop).
The crop is intended to capture order/shipment number fields.
Verify the crop against your document layout before using private documents.
"""
import os
import re
import logging
from io import BytesIO
from dataclasses import dataclass
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
# Crop to top-right corner: captures only the Work Order No. / Shipment No.
# field that needs to reach Azure Document Intelligence. Customer names,
# addresses, signatures, pricing, and line items stay on-premise.
# If OCR misreads shipments, fix it in the text/regex logic below — never
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
    kind: Literal["shipment", "work_order"]
    value: str


def extract_order_number(image_bytes: bytes, crop_header: bool = True,
                         crop_ratio: float = HEADER_CROP_HEIGHT) -> Optional[str]:
    """Compatibility wrapper for the legacy scan index."""
    result = extract_order_identity(image_bytes, crop_header, crop_ratio)
    return result.value if result else None


def extract_order_identity(
    image_bytes: bytes,
    crop_header: bool = True,
    crop_ratio: float = HEADER_CROP_HEIGHT,
) -> Optional[ParsedIdentifier]:
    """
    Send image to Azure Document Intelligence (prebuilt-read) and extract
    the work order ID or SO number via regex.
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

    client_cls, request_cls, credential_cls = _get_azure_ocr_types()
    client = client_cls(endpoint=endpoint, credential=credential_cls(key))
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

    return parse_identifier(raw_text)


def parse_identifier(raw_text: str) -> Optional[ParsedIdentifier]:
    """Parse provider text without cloud calls, retaining its identifier namespace."""
    # Aggressive normalization: collapse ALL whitespace (newlines, tabs,
    # double spaces) into single spaces. Azure often splits "Shipment" and
    # "No." across lines and the naive space-join leaves inconsistent gaps.
    all_text = re.sub(r"\s+", " ", raw_text).strip()
    logger.debug("OCR returned %d characters", len(all_text))

    # Optional exact header strings, separated by |; configure for your own forms.
    for noise in os.getenv("OCR_HEADER_NOISE", "").split("|"):
        if noise.strip():
            all_text = all_text.replace(noise.strip(), "")

    # Validate this looks like a ticket. Keywords are checked as single tokens
    # (not multi-word phrases) so Azure line-splitting doesn't break the match.
    text_lower = all_text.lower()
    ticket_keywords = [
        "delivery ticket", "elivery ticket",
        "shipment confirmation", "shipment",
        "sale no", "shipment no", "order no",
        "work order",
    ]
    is_ticket = any(kw in text_lower for kw in ticket_keywords)

    if not is_ticket:
        logger.warning("OCR: page rejected — no ticket keyword found")
        return None

    # Build a broad label-alternatives group so variants like "Shipment No",
    # "Shipment Number", "Shipment #", "Sale No.", "Ship No", "SO#", "SO:"
    # all match. The trailing \s*[.:#]?\s* absorbs any punctuation/spacing
    # between label and number.
    LABEL_ALTS = (
        r"Shipment\s*(?:No|Number|#|Nbr)\s*\.?"   # Shipment No / Number / #
        r"|Ship\s*(?:No|Number|#|Nbr)\s*\.?"      # Ship No / # (abbreviated)
        r"|Sale\s*(?:No|Number|#|Nbr)\s*\.?"      # Sale No / Number / #
        r"|SO\s*[#:]?"                             # SO#  /  SO:
        r"|S/O\s*[#:]?"                            # S/O legacy format
    )

    # 1. Shipment/Sale number from labeled fields (highest priority for SO documents)
    #    Must check BEFORE W- pattern since shipment docs may have unrelated W- refs.
    #    \d{4,8} — real shipment numbers are at least 4 digits. The old
    #    \d{3,8} let 3-digit page fragments like "837" win over the
    #    actual 5-digit shipment number on the same page.
    label_match = re.search(
        rf"\b(?:{LABEL_ALTS})\s*[.:#]?\s*0*(\d{{4,8}})(?!\d)",
        all_text, re.IGNORECASE
    )
    if label_match:
        return ParsedIdentifier("shipment", label_match.group(1))

    # 2. Work Order ID pattern: W-XXXXXX
    match = re.search(r'\bW-\d+\b', all_text, re.IGNORECASE)
    if match:
        return ParsedIdentifier("work_order", match.group(0).upper())

    # 3. Order No. as fallback (separate from shipment to avoid false matches)
    order_match = re.search(
        r'(?:Order\s*(?:No|Number|#)\s*\.?|Work\s*Order\s*(?:No|Number|#)\s*\.?)\s*[.:#]?\s*0*(\d{4,8})',
        all_text, re.IGNORECASE
    )
    if order_match:
        return ParsedIdentifier("work_order", order_match.group(1))

    # 4. Shipment Confirmation with number before or after title
    #    OCR sometimes reads the number out of order (e.g. "Confirmation 003452 Shipment No")
    confirm_match = re.search(
        r'(?:Shipment|hipment|Sale)\s*Confirmation\s+0*(\d{4,8})',
        all_text, re.IGNORECASE
    )
    if confirm_match:
        return ParsedIdentifier("shipment", confirm_match.group(1))

    # 5. Last-resort fallback for shipment documents where Azure couldn't
    #    pair the label with the number. Only triggers if the doc clearly
    #    says "SHIPMENT" — we take the FIRST standalone 4-7 digit number
    #    that is not a configured excluded number or a
    #    4-digit year (2020-2099). The year filter fixed a real bug where
    #    "2026" on a printed date label was being returned as the order ID.
    #    Lookbehind/ahead also exclude LETTERS so customer codes like
    #    "C000837" don't have their digit tail captured as a shipment.
    #    Leading zeros are preserved then stripped like the labeled path.
    allow_unlabeled = os.getenv("OCR_ALLOW_UNLABELED_FALLBACK", "").lower() in {"1", "true", "yes"}
    if allow_unlabeled and ("shipment" in text_lower or "sale no" in text_lower):
        for match in re.finditer(r'(?<![A-Za-z0-9])0*(\d{4,7})(?![A-Za-z0-9])', all_text):
            candidate = match.group(1)
            # Exclude form-specific postal codes or telephone fragments.
            excluded = os.getenv("OCR_EXCLUDED_NUMBERS", "").split(",")
            if candidate in {value.strip() for value in excluded}:
                continue
            # Skip 4-digit year-like numbers — printed dates on the form
            # leak through this fallback otherwise.
            if len(candidate) == 4 and 2020 <= int(candidate) <= 2099:
                continue
            return ParsedIdentifier("shipment", candidate)

    # Do not retain OCR content in application logs. Header crops can contain
    # order metadata even though full tickets are never sent to OCR.
    logger.warning("OCR: ticket detected but no order number extracted")
    return None
