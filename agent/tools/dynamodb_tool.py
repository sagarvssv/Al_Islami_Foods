import boto3, os, uuid
from datetime import datetime
from dotenv import load_dotenv
load_dotenv(override=True)

TABLE = os.getenv('DYNAMODB_TABLE', 'al-islami-petty-cash')

def get_session():
    key    = os.getenv('AWS_ACCESS_KEY_ID', '').strip()
    secret = os.getenv('AWS_SECRET_ACCESS_KEY', '').strip()
    region = os.getenv('AWS_DEFAULT_REGION', 'eu-central-1')
    if key and secret and key.startswith('AK'):
        return boto3.Session(
            aws_access_key_id=key,
            aws_secret_access_key=secret,
            region_name=region
        )
    else:
        return boto3.Session(region_name=region)

def get_table():
    return get_session().resource('dynamodb').Table(TABLE)

def generate_invoice_id() -> str:
    return str(uuid.uuid4())[:8].upper()

def save_invoice(invoice: dict, s3_key: str, invoice_id: str):
    table = get_table()
    table.put_item(Item={
        'invoice_id'    : invoice_id,
        'vendor_name'   : invoice.get('vendor_name', ''),
        'invoice_number': invoice.get('invoice_number', '') or '',
        'invoice_date'  : invoice.get('invoice_date', '') or '',
        'total_amount'  : str(invoice.get('total_amount', 0)),
        'currency'      : invoice.get('currency', 'AED'),
        'category'      : invoice.get('category', 'Other'),
        'tax_amount'    : str(invoice.get('tax_amount', 0)),
        'line_items'    : str(invoice.get('line_items', [])),
        'payment_method': invoice.get('payment_method', '') or '',
        'notes'         : invoice.get('notes', '') or '',
        's3_key'        : s3_key,
        'status'        : 'PENDING',
        'created_at'    : datetime.utcnow().isoformat(),
        'updated_at'    : datetime.utcnow().isoformat(),
        'submitter_email': invoice.get('submitter_email', ''),
    })
    print(f"  Saved to DynamoDB: {invoice_id} | status=PENDING")

def check_duplicate(invoice: dict) -> dict:
    """
    Check duplicate against PENDING + APPROVED invoices only.
    REJECTED invoices are completely ignored.
    Match by:
      1. invoice_number exact match
      2. vendor_name + total_amount + invoice_date all three match
    """
    table = get_table()

    inv_number = (invoice.get('invoice_number') or '').strip()
    vendor     = (invoice.get('vendor_name') or '').strip().lower()
    amount     = str(invoice.get('total_amount', 0))
    inv_date   = (invoice.get('invoice_date') or '').strip()

    response = table.scan(
        FilterExpression='#st IN (:pending, :approved)',
        ExpressionAttributeNames ={'#st': 'status'},
        ExpressionAttributeValues={
            ':pending' : 'PENDING',
            ':approved': 'APPROVED'
        }
    )
    active_items = response.get('Items', [])
    print(f"  Checking against {len(active_items)} active records (PENDING + APPROVED)...")

    for item in active_items:
        existing_inv_num = (item.get('invoice_number') or '').strip()
        existing_vendor  = (item.get('vendor_name') or '').strip().lower()
        existing_amount  = str(item.get('total_amount', ''))
        existing_date    = (item.get('invoice_date') or '').strip()
        existing_status  = item.get('status', '')
        existing_id      = item.get('invoice_id', '')

        # Match 1 — invoice number
        if inv_number and existing_inv_num and inv_number == existing_inv_num:
            print(f"  DUPLICATE by invoice_number '{inv_number}' "
                  f"-> matches {existing_id} [{existing_status}]")
            return {
                'is_duplicate'  : True,
                'matched_id'    : existing_id,
                'matched_status': existing_status,
                'match_reason'  : (
                    f"Invoice number '{inv_number}' already exists "
                    f"as {existing_id} with status {existing_status}"
                )
            }

        # Match 2 — vendor + amount + date
        if (vendor and existing_vendor == vendor
                and existing_amount == amount
                and inv_date and existing_date == inv_date):
            print(f"  DUPLICATE by vendor+amount+date "
                  f"-> matches {existing_id} [{existing_status}]")
            return {
                'is_duplicate'  : True,
                'matched_id'    : existing_id,
                'matched_status': existing_status,
                'match_reason'  : (
                    f"Same vendor '{vendor}', amount {amount}, date {inv_date} "
                    f"already exists as {existing_id} with status {existing_status}"
                )
            }

    print(f"  No duplicate found — invoice is unique")
    return {
        'is_duplicate'  : False,
        'matched_id'    : None,
        'matched_status': None,
        'match_reason'  : None
    }

def update_invoice_status(invoice_id: str, status: str):
    table = get_table()
    table.update_item(
        Key={'invoice_id': invoice_id},
        UpdateExpression='SET #st = :status, updated_at = :ts',
        ExpressionAttributeNames ={'#st': 'status'},
        ExpressionAttributeValues={
            ':status': status.upper(),
            ':ts'    : datetime.utcnow().isoformat()
        }
    )
    print(f"  DynamoDB updated: {invoice_id} -> {status.upper()}")

def get_invoice(invoice_id: str) -> dict:
    table    = get_table()
    response = table.get_item(Key={'invoice_id': invoice_id})
    return response.get('Item', {})