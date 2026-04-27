import os, sys
from dotenv import load_dotenv
load_dotenv(override=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.tools.s3_tool         import download_invoice
from agent.tools.textract_tool   import extract_invoice_text
from agent.tools.llm_tool        import structure_invoice
from agent.tools.validation_tool import validate_invoice
from agent.tools.dynamodb_tool   import (
    generate_invoice_id, save_invoice,
    check_duplicate, update_invoice_status
)
from agent.tools.sns_tool        import send_approval_email

def run_petty_cash_agent(bucket: str, key: str, submitter_email: str = '') -> dict:
    print(f"\n{'='*55}")
    print(f"  AL ISLAMI FOODS - PETTY CASH AGENT")
    print(f"{'='*55}")
    print(f"  Invoice   : s3://{bucket}/{key}")
    print(f"  Submitter : {submitter_email or 'not provided'}\n")

    # ── 1. Verify S3 ──────────────────────────────────────────────────────
    print("[1/6] Verifying invoice in S3...")
    try:
        download_invoice(bucket, key)
    except Exception as e:
        print(f"  ERROR: {e}")
        return {
            'status'    : 'error',
            'errors'    : [f"S3 download failed: {str(e)}"],
            'invoice'   : {},
            'dup_reason': '',
            'invoice_id': ''
        }

    # ── 2. Textract OCR ───────────────────────────────────────────────────
    print("\n[2/6] Extracting text with Amazon Textract...")
    try:
        extraction = extract_invoice_text(bucket, key)
        raw_text   = extraction['raw_text']
        if not raw_text.strip():
            return {
                'status'    : 'error',
                'errors'    : ['Textract returned no text — check the file is a valid invoice'],
                'invoice'   : {},
                'dup_reason': '',
                'invoice_id': ''
            }
    except Exception as e:
        print(f"  ERROR: {e}")
        return {
            'status'    : 'error',
            'errors'    : [f"Textract failed: {str(e)}"],
            'invoice'   : {},
            'dup_reason': '',
            'invoice_id': ''
        }

    # ── 3. LLM structuring ────────────────────────────────────────────────
    print("\n[3/6] Structuring data with Claude via Bedrock...")
    try:
        invoice = structure_invoice(raw_text)
    except Exception as e:
        print(f"  ERROR: {e}")
        return {
            'status'    : 'error',
            'errors'    : [f"LLM structuring failed: {str(e)}"],
            'invoice'   : {},
            'dup_reason': '',
            'invoice_id': ''
        }

    # Attach submitter email to invoice so it gets saved in DynamoDB
    invoice['submitter_email'] = submitter_email

    # ── 4. Validation ─────────────────────────────────────────────────────
    print("\n[4/6] Validating invoice fields...")
    try:
        result = validate_invoice(invoice)
    except Exception as e:
        print(f"  ERROR: {e}")
        return {
            'status'    : 'error',
            'errors'    : [f"Validation error: {str(e)}"],
            'invoice'   : invoice,
            'dup_reason': '',
            'invoice_id': ''
        }

    if not result['valid']:
        print(f"\n  REJECTED — missing critical fields:")
        for err in result['errors']:
            print(f"  - {err}")
        return {
            'status'    : 'rejected',
            'errors'    : result['errors'],
            'invoice'   : invoice,
            'dup_reason': '',
            'invoice_id': ''
        }

    invoice = result['invoice']

    # ── 5. Duplicate check (PENDING + APPROVED only, ignores REJECTED) ────
    print("\n[5/6] Checking for duplicates...")
    try:
        dup_result   = check_duplicate(invoice)
        is_duplicate = dup_result['is_duplicate']
        dup_reason   = dup_result.get('match_reason', '') if is_duplicate else ''
        if is_duplicate:
            print(f"  WARNING: {dup_reason}")
    except Exception as e:
        print(f"  Duplicate check error (continuing): {e}")
        is_duplicate = False
        dup_reason   = ''

    # ── 6. Save to DynamoDB + send approval email ─────────────────────────
    print("\n[6/6] Saving to DynamoDB and sending approval email...")
    try:
        invoice_id = generate_invoice_id()
        save_invoice(invoice, key, invoice_id)
        send_approval_email(invoice, key, invoice_id, is_duplicate)
    except Exception as e:
        print(f"  ERROR: {e}")
        return {
            'status'    : 'error',
            'errors'    : [f"Save/email failed: {str(e)}"],
            'invoice'   : invoice,
            'dup_reason': dup_reason,
            'invoice_id': ''
        }

    status = 'duplicate_pending_approval' if is_duplicate else 'pending_approval'

    print(f"\n{'='*55}")
    if is_duplicate:
        print("  DUPLICATE DETECTED — Email sent with warning.")
    else:
        print("  PIPELINE COMPLETE — Awaiting manager approval.")
    print(f"  Invoice ID : {invoice_id}")
    print(f"  Submitter  : {submitter_email or 'not provided'}")
    print(f"  Status     : {status}")
    print(f"{'='*55}\n")

    return {
        'status'    : status,
        'invoice_id': invoice_id,
        'invoice'   : invoice,
        'dup_reason': dup_reason,
        'errors'    : []
    }


if __name__ == '__main__':
    bucket          = os.getenv('S3_BUCKET_NAME')
    key             = sys.argv[1] if len(sys.argv) > 1 else 'test/sample_invoice.pdf'
    submitter_email = sys.argv[2] if len(sys.argv) > 2 else ''
    result = run_petty_cash_agent(bucket, key, submitter_email)
    print("Result:", result.get('status'))
    if result.get('errors'):
        for e in result['errors']:
            print(f"  - {e}")