"""
Shared utilities used across the ExampleCo pipeline.
"""


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

    order_id = _clean(record.get('Order_ID'))
    order_type = _clean(record.get('Order_Type'))
    so = _clean_so(record.get('SO'))
    customer = _clean(record.get('Customer_name'))
    ship_to = _clean(record.get('Ship_to'))

    if order_type == "SO":
        order_id = f"Shipment {order_id}"

    return "_".join(filter(None, [order_id, f"{order_type}.{so}", customer, ship_to]))
