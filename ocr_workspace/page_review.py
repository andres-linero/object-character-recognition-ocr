"""Compare independent document fields before a human links a source image.

Rental orders (RO-) and sales orders (SO-) are parent orders numbered from one
shared count. A rental order creates work orders (W-); a sales order creates
shipments ("Shipment 00001"). ``order_number`` is the page's own document (its
work order or shipment) and ``parent_order_number`` is the RO- or SO- above it.
"""
import re


def order_type(order_number):
    """Return RENTAL for a work order (W-), SALE for a shipment, otherwise None."""
    text = str(order_number or '').strip().upper()
    return 'RENTAL' if text.startswith('W-') else 'SALE' if text.startswith('SHIPMENT') else None


def parent_type(parent_order_number):
    """Return RENTAL for an RO-, SALE for an SO-, otherwise None."""
    return {'RO-': 'RENTAL', 'SO-': 'SALE'}.get(str(parent_order_number or '').strip().upper()[:3])


def normalized(value, key):
    text = str(value or '').strip().casefold()
    if key == 'customer':
        text = re.sub(r'^demo\s+', '', text)
    return re.sub(r'[^\w]', '', text)


def compare_page(ticket, fields, printed_page):
    definitions = [
        ('customer', 'Customer', ticket.get('customer'), fields.get('customer')),
        ('address', 'Address', ticket.get('billing_address'), fields.get('address')),
        ('parent_order_number', 'Order', ticket.get('parent_order_number'), fields.get('parent_order_number')),
        ('order_number', 'Work order', ticket.get('order_number'), fields.get('order_number')),
        ('page_number', 'Printed page', printed_page, fields.get('page_number')),
        ('expected_pages', 'Page total', ticket.get('expected_pages'), fields.get('expected_pages')),
    ]
    checks = []
    provider = fields.get('ocr_identifiers') or {}
    provider_values = {'parent_order_number': provider.get('rental_order') or provider.get('sales_order'),
                       'order_number': provider.get('work_order') or provider.get('shipment')}
    for key, label, expected, found in definitions:
        status = 'not_read' if found is None or found == '' else 'no_target' if expected is None or expected == '' else (
            'match' if normalized(expected, key) == normalized(found, key) else 'different')
        ocr_found = provider_values.get(key)
        checks.append(dict(key=key, label=label, expected=expected, found=found, status=status,
                           blocking=status == 'different', ocr_found=ocr_found,
                           ocr_differs=bool(ocr_found and expected and normalized(ocr_found, key) != normalized(expected, key))))
    conflicts = [c for c in checks if c['blocking']]
    # A page that prints rental numbers together with sales numbers never belongs anywhere.
    if fields.get('mixed_order_types'):
        conflicts.append(dict(label='Rental and sales numbers on one page'))
    identified = any(c['status'] == 'match' and c['key'] not in {'page_number', 'expected_pages'} for c in checks)
    labels = [c['label'] + ' OCR' for c in checks if c['ocr_differs']]
    return dict(checks=checks, blocked=bool(conflicts), conflicts=[c['label'] for c in conflicts],
                needs_acknowledgment=bool(labels) or not identified,
                differences=labels, identified=identified)
