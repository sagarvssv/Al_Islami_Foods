import boto3, os
from dotenv import load_dotenv
load_dotenv(override=True)

session = boto3.Session(
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_DEFAULT_REGION')
)

table = session.resource('dynamodb').Table(
    os.getenv('DYNAMODB_TABLE', 'al-islami-petty-cash')
)

response = table.scan()
items    = sorted(
    response.get('Items', []),
    key=lambda x: x.get('created_at', '')
)

print(f"\nAL ISLAMI FOODS — PETTY CASH RECORDS")
print(f"{'='*75}")
print(f"{'ID':<12} {'VENDOR':<15} {'INV#':<8} {'AMOUNT':<12} {'STATUS':<10} {'CREATED':<20}")
print(f"{'='*75}")

for item in items:
    inv_id  = item.get('invoice_id', '')[:10]
    vendor  = item.get('vendor_name', '')[:14]
    inv_num = item.get('invoice_number', '')[:7]
    amount  = f"{item.get('total_amount','0')} {item.get('currency','AED')}"[:11]
    status  = item.get('status', '')[:9]
    created = item.get('created_at', '')[:19].replace('T',' ')
    print(f"{inv_id:<12} {vendor:<15} {inv_num:<8} {amount:<12} {status:<10} {created:<20}")

print(f"{'='*75}")
print(f"Total: {len(items)} records")

# Summary
from collections import Counter
statuses = Counter(item.get('status','') for item in items)
print(f"\nSummary:")
for status, count in statuses.items():
    print(f"  {status:<12} : {count}")