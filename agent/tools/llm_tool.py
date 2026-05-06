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


SYSTEM_PROMPT = """You are an expert invoice data extraction and classification AI for Al Islami Foods UAE.

Extract all invoice fields AND classify the category by analyzing the FULL invoice content.

CATEGORY CLASSIFICATION — analyze vendor name, items, descriptions, and context:

Think step by step:
1. Read the vendor name and all line items carefully
2. Ask: what does this business sell or what service do they provide?
3. Pick the single best matching category below

CATEGORY DEFINITIONS:

"Transport"
- Fuel/petrol/diesel/gasoline stations (any brand: IndianOil, IOCL, HPCL, BPCL, ADNOC, ENOC, EPPCO, Shell, BP, Caltex, Total, Rajashree Petroleum, Sai Balaji Petroleum, Gupta Service Station, any STN/Station/Filling/Petroleum/Petrol in name)
- If vendor name contains: Petroleum, Petrol, Filling, Station, Fuel, Oil (as a fuel company)
- If line items mention: litres, ltr, diesel, petrol, fuel
- Vehicle service, tyre, car wash, garage, auto repairs
- Taxi, rideshare, courier, freight, logistics, delivery charges

"Food & Beverage"
- Restaurants, dhabas, cafes, bakeries, food courts, canteens
- Supermarkets and grocery stores
- Catering, food supply, beverages

"Utilities"
- Electricity, water, gas supply companies
- Internet service providers, telephone, mobile bills

"Office Supplies"
- Stationery, paper, pens, printing, photocopying, binding

"Maintenance"
- Building repairs, plumbing, AC service, electrical work
- Equipment maintenance, pest control, cleaning services

"IT & Technology"
- Software, hardware, computers, IT services, cloud

"Marketing"
- Advertising, events, promotions, branding

"Travel"
- Hotels, accommodation, airline tickets (not fuel)

"HR & Recruitment"
- Staff salaries, recruitment, training

"Legal & Professional"
- Legal, accounting, consulting, government fees

"Other"
- Only if truly none of the above fit

IMPORTANT: Petroleum companies, filling stations, fuel vendors = ALWAYS "Transport"
Examples: "Rajashree Petroleum" = Transport, "SAI BALAJI PETROLEUM" = Transport,
"IndianOil" = Transport, "GUPTA SERVICE STN" = Transport

Return ONLY valid JSON — no markdown, no explanation:
{
  "vendor_name": "string",
  "invoice_number": "string",
  "invoice_date": "YYYY-MM-DD",
  "total_amount": number,
  "currency": "AED or SAR or INR or USD etc",
  "tax_amount": number,
  "category": "one category string from the list above",
  "payment_method": "string",
  "line_items": [{"description": "string", "qty": number, "unit_price": number, "total": number}],
  "notes": "string",
  "original_language": "English or Arabic or Bilingual"
}"""


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

Study the vendor name, all text, and item descriptions carefully before assigning category.
For petroleum/petrol/fuel/filling station vendors → category MUST be "Transport".

OCR TEXT:
{raw_text[:8000]}

Return ONLY a valid JSON object with all fields including the correct category."""

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


def _fix_category(invoice: dict) -> dict:
    """
    Safety net: override category based on vendor name and keywords.
    Called after Claude returns to catch obvious misclassifications.
    """
    vendor   = (invoice.get('vendor_name') or '').lower()
    notes    = (invoice.get('notes') or '').lower()
    items    = str(invoice.get('line_items') or '').lower()
    combined = vendor + ' ' + notes + ' ' + items

    transport_keywords = [
        'petroleum', 'petrol', 'diesel', 'fuel', 'filling', 'service stn',
        'service station', 'fuel station', 'filling station', 'gas station',
        'indianoil', 'indian oil', 'iocl', 'hpcl', 'bpcl', 'essar petrol',
        'rajashree', 'sai balaji', 'gupta service', 'hp petrol',
        'adnoc', 'enoc', 'eppco', 'emarat', 'shell', 'caltex', 'bp petrol',
        'litre', 'ltr', 'motor spirit', 'ms fuel', 'lubricant',
        'reliance petro', 'nayara', 'mangalore refinery',
    ]
    if any(kw in combined for kw in transport_keywords):
        if invoice.get('category') != 'Transport':
            print(f"  [CATEGORY FIX] '{invoice.get('category')}' → 'Transport' "
                  f"(keyword match in vendor/notes)")
            invoice['category'] = 'Transport'
        return invoice

    food_keywords = [
        'restaurant', 'cafe', 'dhaba', 'canteen', 'catering', 'bakery',
        'lulu hypermarket', 'carrefour', 'spinneys', 'union coop', 'nesto',
        'choithrams', 'geant', 'grocery', 'supermarket',
    ]
    if any(kw in combined for kw in food_keywords):
        if invoice.get('category') not in ['Food & Beverage']:
            print(f"  [CATEGORY FIX] '{invoice.get('category')}' → 'Food & Beverage'")
            invoice['category'] = 'Food & Beverage'
        return invoice

    utility_keywords = [
        'dewa', 'addc', 'sewa', 'electricity', 'water board', 'etisalat',
        ' du ', 'airtel', 'vodafone', 'jio', 'bsnl', 'telecom',
    ]
    if any(kw in combined for kw in utility_keywords):
        if invoice.get('category') != 'Utilities':
            print(f"  [CATEGORY FIX] '{invoice.get('category')}' → 'Utilities'")
            invoice['category'] = 'Utilities'

    return invoice


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

        # Safety net: override wrong categories
        invoice = _fix_category(invoice)

        lang = invoice.get('original_language', 'English')
        print(f"  Claude extracted: vendor={invoice.get('vendor_name','?')}, "
              f"amount={invoice.get('total_amount',0)} {invoice.get('currency','?')}, "
              f"category={invoice.get('category','?')}, lang={lang}")

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