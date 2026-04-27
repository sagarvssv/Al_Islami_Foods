import os
from dotenv import load_dotenv
load_dotenv()

VALID_CATEGORIES = [
    'Food & Beverage', 'Transport',
    'Stationery', 'Utilities', 'Other'
]

def validate_invoice(invoice: dict) -> dict:
    errors = []

    # Only hard-fail on truly missing critical fields
    if not invoice.get('vendor_name'):
        errors.append("Missing vendor name")

    # Amount can be 0 or any value - always send to email
    # Currency must be detected correctly
    if not invoice.get('currency'):
        invoice['currency'] = 'AED'

    # Fix category if not valid
    if invoice.get('category') not in VALID_CATEGORIES:
        invoice['category'] = 'Other'

    # Always passes - amount limits removed per requirement
    if errors:
        print(f"  Validation FAILED: {errors}")
    else:
        amount   = invoice.get('total_amount', 0)
        currency = invoice.get('currency', 'AED')
        vendor   = invoice.get('vendor_name', 'Unknown')
        print(f"  Validation PASSED: {vendor} | {amount} {currency} | {invoice.get('category')}")

    return {
        'valid'  : len(errors) == 0,
        'errors' : errors,
        'invoice': invoice
    }