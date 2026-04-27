import boto3, os, json
from dotenv import load_dotenv
load_dotenv(override=True)

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

PROMPT = """You are a petty cash invoice parser for Al Islami Foods UAE.
Extract data from the OCR text below and return ONLY a valid JSON object.
No explanation, no markdown fences, just raw JSON.

IMPORTANT CURRENCY RULES:
- If you see $ or USD symbol, set currency to USD - do NOT convert or change the amount
- If you see AED or no symbol in UAE context, set currency to AED
- If you see EUR set currency to EUR
- If you see GBP set currency to GBP
- NEVER auto-convert amounts. Keep the exact number shown on the invoice.
- If amount is 0 or missing, set total_amount to 0

Required JSON format:
{
  "vendor_name": "string",
  "invoice_number": "string or null",
  "invoice_date": "YYYY-MM-DD or null",
  "total_amount": number,
  "currency": "exact currency from invoice: AED or USD or EUR or GBP or other",
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
    bedrock = get_session().client('bedrock-runtime')
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": PROMPT + raw_text}]
    })
    response = bedrock.invoke_model(
        modelId=os.getenv('BEDROCK_MODEL_ID'),
        body=body
    )
    result = json.loads(response['body'].read())
    text   = result['content'][0]['text'].strip()
    if text.startswith('```'):
        text = text.split('```')[1]
        if text.startswith('json'):
            text = text[4:]
    parsed = json.loads(text.strip())
    print(f"  LLM structured: vendor={parsed.get('vendor_name')}, "
          f"amount={parsed.get('total_amount')} {parsed.get('currency')}")
    return parsed