import re
from datetime import datetime


def validate_invoice(invoice: dict) -> dict:
    """
    Validate extracted invoice data.
    Lenient validation — only hard-fail if absolutely no useful data extracted.
    Arabic/handwritten invoices may have partial data which is still valid.
    """
    errors  = []
    cleaned = dict(invoice)

    # ── Vendor name ────────────────────────────────────────────────────────
    vendor = (invoice.get('vendor_name') or '').strip()
    if not vendor or vendor.lower() in ['unknown', 'n/a', 'none', '']:
        cleaned['vendor_name'] = 'Unknown Vendor'
        print("  WARNING: Vendor name missing — using 'Unknown Vendor'")

    # ── Amount ─────────────────────────────────────────────────────────────
    try:
        amount = float(str(invoice.get('total_amount') or 0).replace(',',''))
        if amount <= 0:
            items = invoice.get('line_items', [])
            if isinstance(items, list) and items:
                calc = sum(float(str(i.get('total',0)).replace(',','')) for i in items if i.get('total'))
                if calc > 0:
                    cleaned['total_amount'] = calc
                    print(f"  Amount recovered from line items: {calc}")
                else:
                    cleaned['total_amount'] = 0
                    print("  WARNING: Amount is 0 — proceeding anyway")
            else:
                cleaned['total_amount'] = 0
                print("  WARNING: Amount missing — proceeding anyway")
        else:
            cleaned['total_amount'] = amount
    except (ValueError, TypeError):
        cleaned['total_amount'] = 0
        print("  WARNING: Could not parse amount — setting to 0")

    # ── Currency ───────────────────────────────────────────────────────────
    currency = (invoice.get('currency') or 'AED').strip().upper()
    valid_currencies = ['AED','USD','EUR','GBP','SAR','INR','QAR','KWD','BHD','OMR',
                        'PKR','EGP','JOD','CNY','JPY','LBP','TRY','MAD','LYD']
    cleaned['currency'] = currency if currency in valid_currencies else 'AED'

    # ── Invoice date ───────────────────────────────────────────────────────
    date_str = (invoice.get('invoice_date') or '').strip()
    if date_str:
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
            cleaned['invoice_date'] = date_str
        except ValueError:
            cleaned['invoice_date'] = ''
            print(f"  WARNING: Invalid date format '{date_str}' — cleared")
    else:
        cleaned['invoice_date'] = ''

    # ── Category — enforce 5 specific categories ───────────────────────────
    valid_cats = ['Food & Beverages', 'Stationery', 'Petrol', 'Electronics', 'Others']
    if invoice.get('category') not in valid_cats:
        cleaned['category'] = 'Others'

    # ── Only hard-fail if absolutely nothing extracted ─────────────────────
    has_vendor  = cleaned.get('vendor_name','') not in ['','Unknown Vendor']
    has_amount  = float(cleaned.get('total_amount', 0)) > 0
    has_inv_num = bool((cleaned.get('invoice_number') or '').strip())
    has_date    = bool((cleaned.get('invoice_date') or '').strip())

    if not has_vendor and not has_amount and not has_inv_num and not has_date:
        errors.append('Invoice appears blank — no vendor, amount, number or date could be extracted. Please upload a clearer image.')

    if errors:
        print(f"  VALIDATION FAILED: {errors}")
        return {'valid': False, 'errors': errors, 'invoice': cleaned}

    print(f"  Validation PASSED: {cleaned.get('vendor_name','?')} | "
          f"{cleaned.get('total_amount',0)} {cleaned.get('currency','AED')} | "
          f"{cleaned.get('category','Others')}")
    return {'valid': True, 'errors': [], 'invoice': cleaned}