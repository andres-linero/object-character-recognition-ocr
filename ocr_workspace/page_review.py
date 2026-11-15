"""Compare independent document fields before a human links a source image."""
import re


def canonical_rental_number(value):
    value = str(value or '').strip().upper()
    return re.sub(r'^RA-', 'RO-', value) or None


def rental_number(fields):
    return canonical_rental_number(fields.get('parent_rental_number') or fields.get('rental_order'))


def unify_rental_fields(fields):
    fields = dict(fields)
    printed = fields.get('rental_number_printed') or fields.get('parent_rental_number') or fields.get('rental_order')
    numbers = {canonical_rental_number(v) for v in [fields.get('parent_rental_number'), fields.get('rental_order')] if v}
    number = rental_number(fields)
    fields.update(parent_rental_number=number, rental_order=number, rental_number_printed=printed,
                  rental_number_conflict=fields.get('rental_number_conflict', False) or len(numbers) > 1)
    return fields


def normalized(value, key):
    if key in {'parent_rental_number', 'rental_order'}:
        value = canonical_rental_number(value)
    text = str(value or '').strip().casefold()
    if key == 'customer':
        text = re.sub(r'^demo\s+', '', text)
    if key == 'shipment' and text.isdigit():
        return text.lstrip('0') or '0'
    return re.sub(r'[^\w]', '', text)


def compare_page(ticket, fields, printed_page):
    definitions = [
        ('customer', 'Customer', ticket.get('customer'), fields.get('customer'), True),
        ('address', 'Address', ticket.get('billing_address'), fields.get('address'), True),
        ('customer_order_number', 'Customer order #', ticket.get('customer_order_number'), fields.get('customer_order_number'), True),
        ('parent_rental_number', 'Rental order (RO)', rental_number(ticket), rental_number(fields), True),
        ('work_order', 'Order number (OD)' if (ticket.get('work_order') or '').startswith('OD-') else 'Ticket / work order', ticket.get('work_order'), fields.get('work_order'), True),
        ('shipment', 'Shipment / SO', ticket.get('shipment'), fields.get('shipment'), False),
        ('page_number', 'Printed page', printed_page, fields.get('page_number'), True),
        ('expected_pages', 'Page total', ticket.get('expected_pages'), fields.get('expected_pages'), True),
    ]
    checks = []
    provider = fields.get('ocr_identifiers') or {}
    namespaces = {'work_order': 'work_order', 'shipment': 'shipment', 'parent_rental_number': 'rental_order', 'customer_order_number': 'customer_order'}
    for key, label, expected, found, blocking in definitions:
        if key == 'customer_order_number' and (ticket.get('work_order') or '').startswith('OD-'):
            continue
        status = 'not_read' if found is None or found == '' else 'no_target' if expected is None or expected == '' else (
            'match' if normalized(expected, key) == normalized(found, key) else 'different')
        ocr_found = provider.get(namespaces.get(key))
        checks.append(dict(key=key, label=label, expected=expected, found=found, status=status,
                           blocking=blocking and status == 'different', ocr_found=ocr_found,
                           ocr_differs=bool(ocr_found and expected and normalized(ocr_found, key) != normalized(expected, key))))
    conflicts = [c for c in checks if c['blocking']]
    if unify_rental_fields(fields)['rental_number_conflict']:
        conflicts.append(dict(label='Conflicting rental numbers on image'))
    differences = [c for c in checks if c['status'] == 'different' and not c['blocking']]
    identified = any(c['status'] == 'match' and c['key'] not in {'page_number', 'expected_pages', 'shipment'} for c in checks)
    labels = [c['label'] for c in differences] + [c['label'] + ' OCR' for c in checks if c['ocr_differs']]
    return dict(checks=checks, blocked=bool(conflicts), conflicts=[c['label'] for c in conflicts],
                needs_acknowledgment=bool(labels) or not identified,
                differences=labels, identified=identified)
