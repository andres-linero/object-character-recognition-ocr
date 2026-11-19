"""Consistent, filesystem-safe customer-facing ticket filenames."""
import re
import unicodedata


def ticket_filename(ticket):
    def clean(value, fallback, limit):
        value = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode()
        value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', ' ', value)
        value = re.sub(r'\s+', ' ', value).strip(' .')[:limit].rstrip(' .')
        return value or fallback

    customer = re.sub(r'^Demo\s+', '', ticket.get('customer') or '', flags=re.I)
    # Order (RO or SO) first, then the work order or shipment created from it.
    parts = [clean(customer, 'Customer-not-recorded', 48),
             clean(ticket.get('parent_order_number'), 'Order-not-recorded', 24)]
    parts.append(clean(ticket.get('order_number'), 'Work-order-not-recorded', 24))
    parts.append(clean(ticket.get('billing_address'), 'Address-not-recorded', 90))
    return '__'.join(parts) + '.pdf'
