import boto3, os, json, re
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
    return boto3.Session(region_name=region)


SYSTEM_PROMPT = """You are an expert invoice data extraction AI for Al Islami Foods UAE.

You extract structured invoice data from OCR text. The invoice may be:
- In English
- In Arabic (عربي) — translate all fields to English
- Bilingual (Arabic + English)

For Arabic invoices: translate vendor names, descriptions and notes to English.
Always return amounts in their ORIGINAL currency — do NOT convert currencies.

Return ONLY valid JSON with these exact fields:
{
  "vendor_name": "string (translate to English if Arabic)",
  "invoice_number": "string",
  "invoice_date": "YYYY-MM-DD",
  "total_amount": number,
  "currency": "AED or USD or SAR or EUR or INR etc",
  "tax_amount": number,
  "category": "one of: Food & Beverage, Office Supplies, Transport, Utilities, Maintenance, IT & Technology, Marketing, HR & Recruitment, Legal & Professional, Travel, Other",
  "payment_method": "string",
  "line_items": [{"description": "string", "qty": number, "unit_price": number, "total": number}],
  "notes": "string",
  "original_language": "English or Arabic or Bilingual"
}

Category selection guide:
- Food & Beverage: restaurants, catering, groceries, food supplies
- Transport: fuel, vehicle, delivery, logistics, shipping
- Utilities: electricity, water, internet, phone, gas
- Office Supplies: stationery, printing, cleaning, office items
- Maintenance: repairs, renovation, facilities, equipment service
- IT & Technology: software, hardware, computers, tech services
- Marketing: advertising, promotions, events, media
- Travel: hotels, flights, accommodation, travel expenses
- HR & Recruitment: salaries, training, recruitment
- Legal & Professional: legal fees, accounting, consulting

If a field is not found, use null for numbers and empty string "" for strings.
Return ONLY the JSON object — no markdown, no explanation."""


def structure_invoice(raw_text: str) -> dict:
    """
    Use Claude via Bedrock to extract invoice data.
    Handles English and Arabic invoices.
    """
    client   = get_session().client('bedrock-runtime')
    model_id = os.getenv('BEDROCK_MODEL_ID', 'eu.anthropic.claude-sonnet-4-5-20250929-v1:0')

    prompt = f"""Extract all invoice data from the following OCR text.
If the invoice is in Arabic, translate all fields to English.

OCR TEXT:
{raw_text[:6000]}

Return ONLY a valid JSON object with the exact fields specified."""

    try:
        response = client.invoke_model(
            modelId     = model_id,
            contentType = 'application/json',
            accept      = 'application/json',
            body        = json.dumps({
                'anthropic_version': 'bedrock-2023-05-31',
                'max_tokens'       : 4096,
                'system'           : SYSTEM_PROMPT,
                'messages'         : [{'role': 'user', 'content': prompt}]
            })
        )

        body = json.loads(response['body'].read())
        text = body['content'][0]['text'].strip()

        # Strip markdown fences if present
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        text = text.strip()

        invoice = json.loads(text)

        # Sanitize numeric fields
        invoice['total_amount'] = _safe_float(invoice.get('total_amount', 0))
        invoice['tax_amount']   = _safe_float(invoice.get('tax_amount', 0))

        # Default currency
        if not invoice.get('currency'):
            invoice['currency'] = 'AED'

        # Default category
        if not invoice.get('category'):
            invoice['category'] = 'Other'

        lang = invoice.get('original_language', 'English')
        print(f"  LLM structured: vendor={invoice.get('vendor_name','?')}, "
              f"amount={invoice.get('total_amount',0)} {invoice.get('currency','?')}, "
              f"category={invoice.get('category','?')}, language={lang}")

        return invoice

    except json.JSONDecodeError as e:
        print(f"  LLM JSON parse error: {e}")
        print(f"  Raw text (first 300): {text[:300] if 'text' in dir() else 'N/A'}")
        raise Exception(f"LLM returned invalid JSON: {e}")

    except Exception as e:
        print(f"  LLM error: {e}")
        raise


def _safe_float(val) -> float:
    """Convert value to float safely."""
    if val is None:
        return 0.0
    try:
        return float(str(val).replace(',', '').replace(' ', ''))
    except (ValueError, TypeError):
        return 0.0