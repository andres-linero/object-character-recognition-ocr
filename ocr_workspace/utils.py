"""
Filename and typed-identifier utilities for document processing.
"""

import re
from pathlib import Path


def pdf_name(record: dict) -> str:
    """Build PDF name: [Shipment] Order_ID + Order_Type.SO + Customer_name + Ship_to."""
    def _clean(value) -> str:
        """str() with whitespace strip and pandas-friendly empty handling."""
        if value is None:
            return ''
        s = str(value).strip()
        return '' if s.lower() in ('nan', 'nat') else s

    def _clean_so(value) -> str:
        """SO is mostly numeric in Excel but can occasionally hold a W- style
        Order_ID. Strip a trailing '.0' from numeric values, leave anything
        else as-is. Never raise on bad input."""
        s = _clean(value)
        if not s:
            return ''
        if s.endswith('.0') and s[:-2].lstrip('-').isdigit():
            return s[:-2]
        return s

    def _filename_part(value):
        return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip().rstrip(". ")

    order_id = _clean(record.get('Order_ID'))
    order_type = _clean(record.get('Order_Type'))
    so = _clean_so(record.get('SO'))
    customer = _clean(record.get('Customer_name'))
    ship_to = _clean(record.get('Ship_to'))

    if order_type == "SO":
        order_id = f"Shipment {order_id}"

    return "_".join(_filename_part(part) for part in [order_id, f"{order_type}.{so}", customer, ship_to] if part)


def normalize_order_token(value: str) -> str | None:
    """Keep work-order and shipment namespaces distinct while normalizing zeros."""
    match = re.fullmatch(r"(W-)?(\d+)", str(value).strip(), re.IGNORECASE)
    if not match:
        return None
    digits = match.group(2).lstrip("0") or "0"
    return ("W-" if match.group(1) else "") + digits


def find_compiled_pdfs(folder: Path, identifier: str) -> list[Path]:
    """Match a complete leading filename token, never a substring or another namespace."""
    token = normalize_order_token(identifier)
    folder = Path(folder)
    if token is None or not folder.is_dir():
        return []
    result = []
    for path in folder.iterdir():
        if path.suffix.lower() != ".pdf" or not path.is_file():
            continue
        if path.resolve().parent != folder.resolve():
            continue
        prefix = path.stem.split("_", 1)[0]
        prefix = re.sub(r"^Shipment\s+", "", prefix, flags=re.IGNORECASE)
        if normalize_order_token(prefix) == token:
            result.append(path)
    return sorted(result, key=lambda p: p.name.casefold())
