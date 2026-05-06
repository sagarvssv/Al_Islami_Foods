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

Extract structured invoice data from OCR text. The invoice may be in English, Arabic, or both.
Always return amounts in their ORIGINAL currency — do NOT convert currencies.

CRITICAL CATEGORY RULE — read carefully before classifying:

The category field MUST follow these rules in PRIORITY ORDER:

RULE 1 — TRANSPORT (highest priority for fuel/petrol):
Set category = "Transport" if ANY of these appear ANYWHERE in the text:
- Words: petrol, fuel, diesel, gasoline, filling station, fuel station, service station, pump
- Words: litre, ltr, lts, gallons, litres (quantity of fuel)
- Company names: IndianOil, Indian Oil, IOCL, HPCL, BPCL, Hindustan Petroleum, Bharat Petroleum
- Company names: ADNOC, ENOC, EPPCO, BP, Shell, Caltex, Total, Mobil, ExxonMobil
- Company names: HP Petrol, HP Gas, IOC, Petron, Sinopec
- Any "STN", "Station", "Filling" near a fuel company name
- Vehicle expenses: car repair, tyre, oil change, vehicle service, auto service, garage

RULE 2 — FOOD & BEVERAGE:
Set category = "Food & Beverage" if invoice is from:
- Restaurants, cafes, dhabas, hotels serving food, canteens, food courts
- Supermarkets: Lulu, Carrefour, Spinneys, Union Coop, Geant, Nesto
- Catering, food supply companies, groceries, beverages

RULE 3 — UTILITIES:
- Electricity boards (DEWA, ADDC, SEWA, BESCOM, MSEB), water, gas pipeline
- Telecom (Etisalat/e&, du, STC, Airtel, Vodafone, Jio, BSNL)

RULE 4 — OFFICE SUPPLIES:
- Stationery, paper, pens, printer ink, toner, printing, photocopying

RULE 5 — MAINTENANCE:
- Building/equipment repairs, AC service, plumbing, electrical work, pest control

RULE 6 — IT & TECHNOLOGY:
- Software, hardware, computers, cloud services, IT support

RULE 7 — MARKETING:
- Advertising, branding, events, exhibitions, promotions

RULE 8 — TRAVEL:
- Hotels, flight tickets, airport transfers (NOT fuel)

RULE 9 — HR & RECRUITMENT:
- Staff costs, training, recruitment fees

RULE 10 — LEGAL & PROFESSIONAL:
- Legal fees, accounting, consulting, government fees

RULE 11 — OTHER:
Use "Other" ONLY if absolutely none of the above rules match.
NEVER use "Other" for fuel/petrol invoices — those are always "Transport".

Return ONLY valid JSON:
{
  "vendor_name": "string",
  "invoice_number": "string",
  "invoice_date": "YYYY-MM-DD",
  "total_amount": number,
  "currency": "AED or SAR or INR or USD etc",
  "tax_amount": number,
  "category": "Transport or Food & Beverage or Utilities or Office Supplies or Maintenance or IT & Technology or Marketing or Travel or HR & Recruitment or Legal & Professional or Other",
  "payment_method": "string",
  "line_items": [{"description": "string", "qty": number, "unit_price": number, "total": number}],
  "notes": "string",
  "original_language": "English or Arabic or Bilingual"
}

Return ONLY the JSON object — no markdown, no explanation."""


def translate_arabic_to_english(text: str) -> str:
    """
    Use Amazon Translate to convert Arabic text to English.
    Called as fallback when Claude fails to extract from Arabic OCR.
    """
    try:
        translate = get_session().client('translate', region_name='eu-central-1')
        # Split into chunks if too long (Translate limit: 10000 bytes)
        chunks = [text[i:i+5000] for i in range(0, len(text), 5000)]
        translated_parts = []
        for chunk in chunks:
            if not chunk.strip():
                continue
            response = translate.translate_text(
                Text=chunk,
                SourceLanguageCode='ar',
                TargetLanguageCode='en'
            )
            translated_parts.append(response['TranslatedText'])
        result = '\n'.join(translated_parts)
        print(f"  [Translate] Arabic → English: {len(text)} → {len(result)} chars")
        return result
    except Exception as e:
        print(f"  [Translate] Amazon Translate failed: {e}")
        return text  # Return original if translate fails


def detect_arabic(text: str) -> bool:
    """Check if text contains significant Arabic content."""
    arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    total_chars  = len([c for c in text if c.strip()])
    return total_chars > 0 and (arabic_chars / max(total_chars, 1)) > 0.1


def is_extraction_poor(invoice: dict) -> bool:
    """Check if Claude's extraction is poor — missing key fields."""
    vendor  = (invoice.get('vendor_name') or '').strip()
    amount  = float(str(invoice.get('total_amount') or 0).replace(',', ''))
    inv_num = (invoice.get('invoice_number') or '').strip()
    vendor_bad = not vendor or vendor.lower() in ['unknown', 'unknown vendor', 'n/a', '']
    return vendor_bad and amount <= 0 and not inv_num


def call_claude(raw_text: str, is_arabic: bool = False) -> dict:
    """Call Claude Bedrock to extract invoice data."""
    client   = get_session().client('bedrock-runtime')
    model_id = os.getenv('BEDROCK_MODEL_ID', 'eu.anthropic.claude-sonnet-4-5-20250929-v1:0')

    lang_hint = ""
    if is_arabic:
        lang_hint = "\nNote: This text may contain Arabic content. Extract all fields and translate to English.\n"

    prompt = f"""Extract all invoice data from the following OCR text.{lang_hint}

OCR TEXT:
{raw_text[:6000]}

Return ONLY a valid JSON object."""

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
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    return json.loads(text.strip())


def structure_invoice(raw_text: str) -> dict:
    """
    Use Claude via Bedrock to extract invoice data.
    For Arabic invoices with poor extraction, falls back to Amazon Translate.

    Flow:
    1. Detect if Arabic
    2. Try Claude directly (handles Arabic natively)
    3. If extraction poor AND Arabic → use Amazon Translate → retry Claude
    4. Return best result
    """
    is_arabic = detect_arabic(raw_text)

    if is_arabic:
        print(f"  Arabic content detected — Claude will extract directly")
    
    # ── Step 1: Try Claude directly ─────────────────────────────────────
    try:
        invoice = call_claude(raw_text, is_arabic=is_arabic)
        invoice['total_amount'] = _safe_float(invoice.get('total_amount', 0))
        invoice['tax_amount']   = _safe_float(invoice.get('tax_amount', 0))
        if not invoice.get('currency'):
            invoice['currency'] = 'AED'
        if not invoice.get('category'):
            invoice['category'] = 'Other'

        lang = invoice.get('original_language', 'English')
        print(f"  Claude extracted: vendor={invoice.get('vendor_name','?')}, "
              f"amount={invoice.get('total_amount',0)} {invoice.get('currency','?')}, "
              f"lang={lang}")

        # ── Step 2: If Arabic and extraction poor → use Amazon Translate ─
        if is_arabic and is_extraction_poor(invoice):
            print(f"  Poor extraction detected — trying Amazon Translate fallback...")
            try:
                translated_text = translate_arabic_to_english(raw_text)
                print(f"  Retrying Claude with translated text...")
                invoice2 = call_claude(translated_text, is_arabic=False)
                invoice2['total_amount'] = _safe_float(invoice2.get('total_amount', 0))
                invoice2['tax_amount']   = _safe_float(invoice2.get('tax_amount', 0))
                if not invoice2.get('currency'):
                    invoice2['currency'] = 'AED'
                if not invoice2.get('category'):
                    invoice2['category'] = 'Other'
                invoice2['original_language']   = 'Arabic (translated)'
                invoice2['translation_used']    = True

                print(f"  Translate+Claude: vendor={invoice2.get('vendor_name','?')}, "
                      f"amount={invoice2.get('total_amount',0)} {invoice2.get('currency','?')}")

                # Use translated result if it's better
                if not is_extraction_poor(invoice2):
                    print(f"  Using Amazon Translate result (better extraction)")
                    return invoice2
                else:
                    print(f"  Translate didn't improve — using original Claude result")
            except Exception as te:
                print(f"  Translate fallback error: {te} — using original Claude result")

        return invoice

    except json.JSONDecodeError as e:
        print(f"  Claude JSON parse error: {e}")
        raise Exception(f"Claude returned invalid JSON: {e}")
    except Exception as e:
        print(f"  Claude error: {e}")
        raise


def _safe_float(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(str(val).replace(',', '').replace(' ', ''))
    except (ValueError, TypeError):
        return 0.0