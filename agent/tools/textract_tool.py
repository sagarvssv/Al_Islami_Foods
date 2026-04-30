import boto3, os, tempfile
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


def extract_invoice_text(bucket: str, key: str) -> dict:
    """
    Extract text from invoice using Amazon Textract.
    Supports both English and Arabic invoices automatically.
    Arabic text is detected and included in the raw output for Claude to translate.
    """
    client = get_session().client('textract')

    print(f"  Textract extracting: s3://{bucket}/{key}")

    # Use detect_document_text for standard invoices
    # Textract automatically handles Arabic (RTL) text
    try:
        response = client.detect_document_text(
            Document={
                'S3Object': {
                    'Bucket': bucket,
                    'Name'  : key
                }
            }
        )
    except Exception as e:
        print(f"  Textract detect_document_text failed: {e}")
        raise

    # Extract all text lines
    lines = []
    for block in response.get('Blocks', []):
        if block['BlockType'] == 'LINE':
            text = block.get('Text', '').strip()
            if text:
                lines.append(text)

    raw_text = '\n'.join(lines)

    # Detect if document contains Arabic text
    arabic_chars = sum(1 for c in raw_text if '\u0600' <= c <= '\u06FF')
    total_chars  = len([c for c in raw_text if c.strip()])
    is_arabic    = total_chars > 0 and (arabic_chars / total_chars) > 0.15

    if is_arabic:
        print(f"  Arabic invoice detected ({arabic_chars} Arabic chars) — Claude will translate")
        # Prepend hint for Claude to handle Arabic
        raw_text = (
            "[ARABIC INVOICE - Please extract and translate all fields to English]\n"
            "[هذه فاتورة عربية - يرجى استخراج جميع الحقول وترجمتها إلى الإنجليزية]\n\n"
            + raw_text
        )
    else:
        print(f"  English/mixed invoice detected")

    print(f"  Textract extracted {len(lines)} lines, {len(raw_text)} characters")

    return {
        'raw_text' : raw_text,
        'lines'    : lines,
        'is_arabic': is_arabic,
        'page_count': 1
    }