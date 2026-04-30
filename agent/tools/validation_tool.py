import os

code = """import re
from datetime import datetime


def validate_invoice(invoice: dict) -> dict:
    \"\"\"
    Validate extracted invoice data.
    Lenient validation — only hard-fail if absolutely no useful data extracted.
    Arabic/handwritten invoices may have partial data which is still valid.
    \"\"\"
    errors  = []
    cleaned = dict(invoice)

    # ── Vendor name ────────────────────────────────────────────────────────
    vendor = (invoice.get('vendor_name') or '').strip()
    if not vendor or vendor.lower() in ['unknown', 'n/a', 'none', '']:
        # Don't reject — use placeholder, warn instead
        cleaned['vendor_name'] = 'Unknown Vendor'
        print("  WARNING: Vendor name missing — using 'Unknown Vendor'")
    
    # ── Amount ─────────────────────────────────────────────────────────────
    try:
        amount = float(str(invoice.get('total_amount') or 0).replace(',',''))
        if amount <= 0:
            # Try to find amount from line items
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
    if currency not in valid_currencies:
        cleaned['currency'] = 'AED'
    else:
        cleaned['currency'] = currency

    # ── Invoice date ───────────────────────────────────────────────────────
    date_str = (invoice.get('invoice_date') or '').strip()
    if date_str:
        try:
            # Validate date format
            datetime.strptime(date_str, '%Y-%m-%d')
            cleaned['invoice_date'] = date_str
        except ValueError:
            cleaned['invoice_date'] = ''
            print(f"  WARNING: Invalid date format '{date_str}' — cleared")
    else:
        cleaned['invoice_date'] = ''

    # ── Category ───────────────────────────────────────────────────────────
    valid_cats = [
        'Food & Beverage','Office Supplies','Transport','Utilities',
        'Maintenance','IT & Technology','Marketing','HR & Recruitment',
        'Legal & Professional','Travel','Other'
    ]
    if invoice.get('category') not in valid_cats:
        cleaned['category'] = 'Other'

    # ── Only hard-fail if we have absolutely nothing useful ────────────────
    # An invoice needs at least SOMETHING identifiable
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
          f"{cleaned.get('category','Other')}")
    return {'valid': True, 'errors': [], 'invoice': cleaned}
"""

os.makedirs('agent/tools', exist_ok=True)
with open('agent/tools/validation_tool.py', 'w', encoding='utf-8') as f:
    f.write(code)
print("Written: agent/tools/validation_tool.py")

import subprocess
r = subprocess.run(['python', '-m', 'py_compile', 'agent/tools/validation_tool.py'],
                   capture_output=True, text=True)
print("Syntax:", "OK" if r.returncode == 0 else r.stderr)