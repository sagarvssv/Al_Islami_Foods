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
    return boto3.Session(region_name=region)

def get_table():
    return get_session().resource('dynamodb').Table(TABLE)

def generate_invoice_id() -> str:
    return str(uuid.uuid4())[:8].upper()

def save_invoice(invoice: dict, s3_key: str, invoice_id: str):
    table = get_table()
    table.put_item(Item={
        'invoice_id'       : invoice_id,
        'vendor_name'      : invoice.get('vendor_name', ''),
        'invoice_number'   : invoice.get('invoice_number', '') or '',
        'invoice_date'     : invoice.get('invoice_date', '') or '',
        'total_amount'     : str(invoice.get('total_amount', 0)),
        'currency'         : invoice.get('currency', 'AED'),
        'category'         : invoice.get('category', 'Other'),
        'tax_amount'       : str(invoice.get('tax_amount', 0)),
        'line_items'       : str(invoice.get('line_items', [])),
        'payment_method'   : invoice.get('payment_method', '') or '',
        'notes'            : invoice.get('notes', '') or '',
        's3_key'           : s3_key,
        'submitter_email'  : invoice.get('submitter_email', ''),
        'status'           : 'PENDING',
        'final_status'     : 'PENDING',
        'approval_1_status': 'PENDING',
        'approval_1_email' : os.getenv('APPROVAL_EMAIL', ''),
        'approval_2_status': 'WAITING',
        'approval_2_email' : os.getenv('MANAGER2_EMAIL', ''),
        'created_at'       : datetime.utcnow().isoformat(),
        'updated_at'       : datetime.utcnow().isoformat(),
    })
    print(f"  Saved: {invoice_id} | mgr1={os.getenv('APPROVAL_EMAIL','')} | mgr2={os.getenv('MANAGER2_EMAIL','')}")

def check_duplicate(invoice: dict) -> dict:
    table      = get_table()
    inv_number = (invoice.get('invoice_number') or '').strip()
    vendor     = (invoice.get('vendor_name') or '').strip().lower()
    amount     = str(invoice.get('total_amount', 0))
    inv_date   = (invoice.get('invoice_date') or '').strip()

    r1 = table.scan(
        FilterExpression='#st IN (:p, :a, :am2, :fa, :al1)',
        ExpressionAttributeNames={'#st': 'status'},
        ExpressionAttributeValues={
            ':p'  : 'PENDING',
            ':a'  : 'APPROVED',
            ':am2': 'AWAITING_MANAGER2',
            ':fa' : 'FULLY_APPROVED',
            ':al1': 'APPROVED_L1'
        }
    )
    r2 = table.scan(
        FilterExpression='final_status = :fa',
        ExpressionAttributeValues={':fa': 'FULLY_APPROVED'}
    )
    merged = {i['invoice_id']: i for i in r1.get('Items', [])}
    for item in r2.get('Items', []):
        merged[item['invoice_id']] = item
    active_items = list(merged.values())
    print(f"  Checking against {len(active_items)} active records...")

    for item in active_items:
        ei  = (item.get('invoice_number') or '').strip()
        ev  = (item.get('vendor_name') or '').strip().lower()
        ea  = str(item.get('total_amount', ''))
        ed  = (item.get('invoice_date') or '').strip()
        es  = item.get('final_status') or item.get('status', '')
        eid = item.get('invoice_id', '')

        if inv_number and ei and inv_number == ei:
            print(f"  DUPLICATE invoice_number '{inv_number}' -> {eid} [{es}]")
            return {'is_duplicate': True, 'matched_id': eid, 'matched_status': es,
                    'match_reason': f"Invoice number '{inv_number}' exists as {eid} [{es}]"}

        if vendor and ev == vendor and ea == amount and inv_date and ed == inv_date:
            print(f"  DUPLICATE vendor+amount+date -> {eid} [{es}]")
            return {'is_duplicate': True, 'matched_id': eid, 'matched_status': es,
                    'match_reason': f"Same vendor/amount/date as {eid} [{es}]"}

    print('  No duplicate found')
    return {'is_duplicate': False, 'matched_id': None, 'matched_status': None, 'match_reason': None}

def update_invoice_status(invoice_id: str, status: str):
    get_table().update_item(
        Key={'invoice_id': invoice_id},
        UpdateExpression='SET #st = :status, updated_at = :ts',
        ExpressionAttributeNames={'#st': 'status'},
        ExpressionAttributeValues={':status': status.upper(), ':ts': datetime.utcnow().isoformat()}
    )
    print(f"  DynamoDB: {invoice_id} status -> {status.upper()}")

def update_approval_status(invoice_id: str, level: int, status: str):
    field = f'approval_{level}_status'
    get_table().update_item(
        Key={'invoice_id': invoice_id},
        UpdateExpression=f'SET {field} = :status, updated_at = :ts',
        ExpressionAttributeValues={':status': status.upper(), ':ts': datetime.utcnow().isoformat()}
    )
    print(f"  DynamoDB: {invoice_id} approval_{level} -> {status.upper()}")

def update_final_status(invoice_id: str, status: str):
    get_table().update_item(
        Key={'invoice_id': invoice_id},
        UpdateExpression='SET final_status = :fs, #st = :st, updated_at = :ts',
        ExpressionAttributeNames={'#st': 'status'},
        ExpressionAttributeValues={':fs': status.upper(), ':st': status.upper(),
                                   ':ts': datetime.utcnow().isoformat()}
    )
    print(f"  DynamoDB: {invoice_id} final_status -> {status.upper()}")

def get_invoice(invoice_id: str) -> dict:
    return get_session().resource('dynamodb').Table(TABLE)\
        .get_item(Key={'invoice_id': invoice_id}).get('Item', {})
