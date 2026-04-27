import os

files = {}

files['agent/__init__.py'] = ''
files['agent/tools/__init__.py'] = ''

files['agent/tools/s3_tool.py'] = '''import boto3, os
from dotenv import load_dotenv
load_dotenv()

def get_session():
    return boto3.Session(
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name=os.getenv('AWS_DEFAULT_REGION')
    )

def download_invoice(bucket: str, key: str) -> bytes:
    s3 = get_session().client('s3')
    response = s3.get_object(Bucket=bucket, Key=key)
    print(f"  Downloaded: s3://{bucket}/{key}")
    return response['Body'].read()
'''

files['agent/tools/textract_tool.py'] = '''import boto3, os
from dotenv import load_dotenv
load_dotenv()

def get_session():
    return boto3.Session(
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name=os.getenv('AWS_DEFAULT_REGION')
    )

def extract_invoice_text(bucket: str, key: str) -> dict:
    textract = get_session().client('textract')
    response = textract.analyze_document(
        Document={"S3Object": {"Bucket": bucket, "Name": key}},
        FeatureTypes=["FORMS", "TABLES"]
    )
    raw_lines = []
    for block in response["Blocks"]:
        if block["BlockType"] == "LINE":
            raw_lines.append(block["Text"])
    raw_text = "\\n".join(raw_lines)
    print(f"  Textract extracted {len(raw_lines)} lines, {len(raw_text)} characters")
    return {"raw_text": raw_text, "blocks": response["Blocks"]}
'''

files['agent/tools/llm_tool.py'] = '''import boto3, os, json
from dotenv import load_dotenv
load_dotenv()

def get_session():
    return boto3.Session(
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_DEFAULT_REGION")
    )

PROMPT = """You are a petty cash invoice parser for Al Islami Foods UAE.
Extract data from the OCR text below and return ONLY a valid JSON object.
No explanation, no markdown fences, just raw JSON.

Required JSON format:
{
  "vendor_name": "string",
  "invoice_number": "string or null",
  "invoice_date": "YYYY-MM-DD or null",
  "total_amount": number,
  "currency": "AED",
  "tax_amount": number or 0,
  "category": "one of: Food & Beverage | Transport | Stationery | Utilities | Other",
  "line_items": [
    {"description": "string", "qty": number, "unit_price": number, "total": number}
  ],
  "payment_method": "string or null",
  "notes": "string or null"
}

OCR TEXT:
"""

def structure_invoice(raw_text: str) -> dict:
    bedrock = get_session().client("bedrock-runtime")
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": PROMPT + raw_text}]
    })
    response = bedrock.invoke_model(
        modelId=os.getenv("BEDROCK_MODEL_ID"),
        body=body
    )
    result = json.loads(response["body"].read())
    text   = result["content"][0]["text"].strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    parsed = json.loads(text.strip())
    print(f"  LLM structured: vendor={parsed.get('vendor_name')}, amount={parsed.get('total_amount')} {parsed.get('currency')}")
    return parsed
'''

files['agent/tools/validation_tool.py'] = '''import os
from dotenv import load_dotenv
load_dotenv()

MAX_AMOUNT       = float(os.getenv("MAX_AMOUNT_AED", 5000))
VALID_CATEGORIES = ["Food & Beverage", "Transport", "Stationery", "Utilities", "Other"]

def validate_invoice(invoice: dict) -> dict:
    errors = []
    if not invoice.get("vendor_name"):
        errors.append("Missing vendor name")
    if not invoice.get("invoice_date"):
        errors.append("Missing invoice date")
    amount = invoice.get("total_amount", 0)
    if not isinstance(amount, (int, float)) or amount <= 0:
        errors.append(f"Invalid amount: {amount}")
    elif amount > MAX_AMOUNT:
        errors.append(f"Amount {amount} AED exceeds petty cash limit of {MAX_AMOUNT} AED")
    if invoice.get("category") not in VALID_CATEGORIES:
        errors.append(f"Invalid category: {invoice.get('category')}")
    if errors:
        print(f"  Validation FAILED: {errors}")
    else:
        print(f"  Validation PASSED: {invoice.get('vendor_name')} | {invoice.get('total_amount')} AED | {invoice.get('category')}")
    return {"valid": len(errors) == 0, "errors": errors, "invoice": invoice}
'''

files['agent/tools/sns_tool.py'] = '''import boto3, os
from dotenv import load_dotenv
load_dotenv()

def get_session():
    return boto3.Session(
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_DEFAULT_REGION")
    )

def send_approval_email(invoice: dict, s3_key: str):
    sns      = get_session().client("sns")
    vendor   = invoice.get("vendor_name", "Unknown")
    amount   = invoice.get("total_amount", 0)
    currency = invoice.get("currency", "AED")
    category = invoice.get("category", "Other")
    date     = invoice.get("invoice_date", "N/A")
    inv_num  = invoice.get("invoice_number", "N/A")
    tax      = invoice.get("tax_amount", 0)
    items    = invoice.get("line_items", [])

    subject = f"[Al Islami Foods] Petty Cash Approval - {vendor} - {amount} {currency}"

    line_items_text = ""
    for i, item in enumerate(items, 1):
        line_items_text += f"  {i}. {item.get('description','?')}  x{item.get('qty',1)}  @ {item.get('unit_price',0)}  = {item.get('total',0)} {currency}\\n"

    body = f"""
AL ISLAMI FOODS - PETTY CASH APPROVAL REQUEST
=============================================
  Vendor        : {vendor}
  Invoice No    : {inv_num}
  Invoice Date  : {date}
  Category      : {category}
  Amount        : {amount} {currency}
  Tax           : {tax} {currency}

LINE ITEMS:
{line_items_text if line_items_text else "  (none extracted)"}

INVOICE FILE:
  s3://{os.getenv("S3_BUCKET_NAME")}/{s3_key}

---------------------------------------------
Processed by Al Islami Foods Petty Cash AI
AWS AgentCore | Amazon Textract | Claude Haiku
---------------------------------------------
    """
    sns.publish(TopicArn=os.getenv("SNS_TOPIC_ARN"), Subject=subject, Message=body)
    print(f"  Approval email sent to: {os.getenv('APPROVAL_EMAIL')}")
'''

files['agent/agent_core.py'] = '''import os, sys
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.tools.s3_tool         import download_invoice
from agent.tools.textract_tool   import extract_invoice_text
from agent.tools.llm_tool        import structure_invoice
from agent.tools.validation_tool import validate_invoice
from agent.tools.sns_tool        import send_approval_email

def run_petty_cash_agent(bucket: str, key: str) -> dict:
    print(f"\\n{'='*55}")
    print(f"  AL ISLAMI FOODS - PETTY CASH AGENT")
    print(f"{'='*55}")
    print(f"  Invoice : s3://{bucket}/{key}\\n")

    print("[1/5] Verifying invoice in S3...")
    download_invoice(bucket, key)

    print("\\n[2/5] Extracting text with Amazon Textract...")
    extraction = extract_invoice_text(bucket, key)
    raw_text   = extraction["raw_text"]

    print("\\n[3/5] Structuring data with Claude via Bedrock...")
    invoice = structure_invoice(raw_text)

    print("\\n[4/5] Validating against Al Islami Foods policy...")
    result = validate_invoice(invoice)

    if not result["valid"]:
        print(f"\\n{'='*55}")
        print("  REJECTED - Invoice failed validation:")
        for err in result["errors"]:
            print(f"  - {err}")
        print(f"{'='*55}\\n")
        return {"status": "rejected", "errors": result["errors"], "invoice": invoice}

    print("\\n[5/5] Sending approval email via Amazon SNS...")
    send_approval_email(invoice, key)

    print(f"\\n{'='*55}")
    print("  PIPELINE COMPLETE - Awaiting manager approval.")
    print(f"{'='*55}\\n")
    return {"status": "pending_approval", "invoice": invoice}

if __name__ == "__main__":
    bucket = os.getenv("S3_BUCKET_NAME")
    key    = sys.argv[1] if len(sys.argv) > 1 else "test/sample_invoice.pdf"
    run_petty_cash_agent(bucket, key)
'''

# Write all files
for path, content in files.items():
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  Created: {path}")

print("\nAll agent files created successfully!")
print("Now run: python agent/agent_core.py test/sample_invoice.pdf")