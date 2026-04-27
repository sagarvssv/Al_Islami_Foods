import os, sys
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.tools.s3_tool         import download_invoice
from agent.tools.textract_tool   import extract_invoice_text
from agent.tools.llm_tool        import structure_invoice
from agent.tools.validation_tool import validate_invoice
from agent.tools.sns_tool        import send_approval_email

def run_petty_cash_agent(bucket: str, key: str) -> dict:
    print(f"\n{'='*55}")
    print(f"  AL ISLAMI FOODS — PETTY CASH AGENT")
    print(f"{'='*55}")
    print(f"  Invoice : s3://{bucket}/{key}\n")

    # 1 — Verify S3
    print("[1/5] Verifying invoice in S3...")
    download_invoice(bucket, key)

    # 2 — Textract
    print("\n[2/5] Extracting text with Amazon Textract...")
    extraction = extract_invoice_text(bucket, key)
    raw_text   = extraction['raw_text']

    # 3 — LLM
    print("\n[3/5] Structuring data with Claude via Bedrock...")
    invoice = structure_invoice(raw_text)

    # 4 — Validate
    print("\n[4/5] Validating against Al Islami Foods policy...")
    result = validate_invoice(invoice)

    if not result['valid']:
        print(f"\n{'='*55}")
        print("  REJECTED — Invoice failed validation:")
        for err in result['errors']:
            print(f"  - {err}")
        print(f"{'='*55}\n")
        return {'status': 'rejected', 'errors': result['errors'], 'invoice': invoice}

    # 5 — SNS
    print("\n[5/5] Sending approval email via Amazon SNS...")
    send_approval_email(invoice, key)

    print(f"\n{'='*55}")
    print("  PIPELINE COMPLETE — Awaiting manager approval.")
    print(f"{'='*55}\n")
    return {'status': 'pending_approval', 'invoice': invoice}


if __name__ == '__main__':
    bucket = os.getenv('S3_BUCKET_NAME')
    key    = sys.argv[1] if len(sys.argv) > 1 else 'test/sample_invoice.pdf'
    run_petty_cash_agent(bucket, key)