import boto3, os, json, uuid, sys
from datetime import datetime, timezone
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


def save_to_memory(session_id: str, invoice_id: str, invoice: dict, status: str):
    """Save invoice result to AgentCore memory."""
    try:
        runtime   = get_session().client('bedrock-agentcore')
        memory_id = os.getenv('AGENTCORE_MEMORY_ID')

        memory_payload = [
            {
                'conversational': {
                    'role': 'ASSISTANT',
                    'content': {
                        'text': json.dumps({
                            'invoice_id'    : invoice_id,
                            'vendor_name'   : invoice.get('vendor_name'),
                            'invoice_number': invoice.get('invoice_number'),
                            'total_amount'  : invoice.get('total_amount'),
                            'currency'      : invoice.get('currency'),
                            'status'        : status,
                        }, default=str)
                    }
                }
            }
        ]

        runtime.create_event(
            memoryId       = memory_id,
            actorId        = 'al-islami-petty-cash-agent',
            sessionId      = session_id,
            eventTimestamp = datetime.now(timezone.utc).isoformat(),
            payload        = memory_payload
        )
        print(f"  [Memory] Saved: {invoice_id} -> {status}")
    except Exception as e:
        print(f"  [Memory] Could not save: {e}")


def get_memory_context(session_id: str) -> str:
    """Retrieve past invoice context from AgentCore memory."""
    try:
        runtime   = get_session().client('bedrock-agentcore')
        memory_id = os.getenv('AGENTCORE_MEMORY_ID')
        response  = runtime.list_memory_records(
            memoryId  = memory_id,
            namespace = 'al-islami-petty-cash'
        )
        records = response.get('memoryRecordSummaries', [])
        if records:
            return f"Previous invoices processed: {len(records)}"
        return "No previous invoices in memory."
    except Exception as e:
        print(f"  [Memory] Could not retrieve: {e}")
        return ""


def invoke_agentcore_runtime(bucket: str, key: str,
                             submitter_email: str = '',
                             session_id: str = '') -> dict:
    """
    Invoke AgentCore runtime instance with the invoice pipeline.
    Falls back to direct pipeline if runtime errors.
    """
    try:
        runtime_client = get_session().client('bedrock-agentcore')
    except Exception as e:
        print(f"  [AgentCore] bedrock-agentcore not available in this boto3 version: {e}")
        print(f"  [AgentCore] Falling back to direct pipeline...")
        raise Exception(f"bedrock-agentcore unavailable: {e}")
    runtime_arn    = os.getenv('AGENTCORE_RUNTIME_ARN')
    runtime_id     = os.getenv('AGENTCORE_RUNTIME_ID')

    if not session_id:
        session_id = str(uuid.uuid4())

    print(f"\n[AgentCore] Runtime  : {runtime_id}")
    print(f"[AgentCore] Session  : {session_id}")
    print(f"[AgentCore] Invoice  : s3://{bucket}/{key}")
    print(f"[AgentCore] Submitter: {submitter_email or 'not provided'}")

    memory_context = get_memory_context(session_id)

    agent_input = json.dumps({
        'task'           : 'process_petty_cash_invoice',
        'bucket'         : bucket,
        'key'            : key,
        'submitter_email': submitter_email,
        'memory_context' : memory_context,
        'session_id'     : session_id
    })

    try:
        response = runtime_client.invoke_agent_runtime(
            agentRuntimeArn  = runtime_arn,
            qualifier        = 'DEFAULT',
            payload          = agent_input,
            runtimeSessionId = session_id,
            contentType      = 'application/json',
            accept           = 'application/json'
        )
        print(f"[AgentCore] Runtime invoked successfully")

        output = ''
        if 'content' in response:
            content = response['content']
            if hasattr(content, 'read'):
                output = content.read().decode('utf-8')
            elif hasattr(content, '__iter__'):
                for chunk in content:
                    if isinstance(chunk, bytes):
                        output += chunk.decode('utf-8')
                    elif isinstance(chunk, dict) and 'chunk' in chunk:
                        output += chunk['chunk'].get('bytes', b'').decode('utf-8')
            else:
                output = str(content)

        print(f"[AgentCore] Raw output: {output[:200]}")

        try:
            result = json.loads(output)
            if result.get('invoice_id'):
                save_to_memory(
                    session_id,
                    result['invoice_id'],
                    result.get('invoice', {}),
                    result.get('status', 'unknown')
                )
            return result
        except Exception:
            print(f"[AgentCore] Non-JSON output — running pipeline with memory...")
            return run_pipeline_with_memory(bucket, key, submitter_email, session_id)

    except Exception as e:
        print(f"[AgentCore] Runtime invoke error: {e}")
        print(f"[AgentCore] Running pipeline with AgentCore memory...")
        return run_pipeline_with_memory(bucket, key, submitter_email, session_id)


def run_pipeline_with_memory(bucket: str, key: str,
                              submitter_email: str = '',
                              session_id: str = '') -> dict:
    """
    Run the full invoice pipeline and store result in AgentCore memory.
    Called directly or as fallback from invoke_agentcore_runtime.
    """
    print(f"\n{'='*55}")
    print(f"  AL ISLAMI FOODS - AGENTCORE PIPELINE")
    print(f"{'='*55}")
    print(f"  Runtime  : {os.getenv('AGENTCORE_RUNTIME_ID')}")
    print(f"  Memory   : {os.getenv('AGENTCORE_MEMORY_ID')}")
    print(f"  Session  : {session_id}")
    print(f"  Invoice  : s3://{bucket}/{key}\n")

    # 1 — S3
    print("[1/6] Verifying invoice in S3...")
    try:
        download_invoice(bucket, key)
    except Exception as e:
        return {'status':'error','errors':[str(e)],'invoice':{},'dup_reason':'','invoice_id':''}

    # 2 — Textract
    print("\n[2/6] Extracting text with Amazon Textract...")
    try:
        extraction = extract_invoice_text(bucket, key)
        raw_text   = extraction['raw_text']
        if not raw_text.strip():
            return {'status':'error','errors':['Textract returned no text'],'invoice':{},'dup_reason':'','invoice_id':''}
    except Exception as e:
        return {'status':'error','errors':[f"Textract: {e}"],'invoice':{},'dup_reason':'','invoice_id':''}

    # 3 — LLM
    print("\n[3/6] Structuring with Claude via Bedrock...")
    try:
        invoice = structure_invoice(raw_text)
        invoice['submitter_email'] = submitter_email
    except Exception as e:
        return {'status':'error','errors':[f"LLM: {e}"],'invoice':{},'dup_reason':'','invoice_id':''}

    # 4 — Validate
    print("\n[4/6] Validating invoice fields...")
    try:
        result  = validate_invoice(invoice)
        invoice = result['invoice']
        invoice['submitter_email'] = submitter_email
    except Exception as e:
        return {'status':'error','errors':[f"Validation: {e}"],'invoice':invoice,'dup_reason':'','invoice_id':''}

    if not result['valid']:
        return {'status':'rejected','errors':result['errors'],'invoice':invoice,'dup_reason':'','invoice_id':''}

    # 5 — Duplicate check
    print("\n[5/6] Checking for duplicates...")
    try:
        dup_result   = check_duplicate(invoice)
        is_duplicate = dup_result['is_duplicate']
        dup_reason   = dup_result.get('match_reason', '') if is_duplicate else ''
        if is_duplicate:
            print(f"  WARNING: {dup_reason}")
    except Exception as e:
        print(f"  Duplicate check error: {e}")
        is_duplicate = False
        dup_reason   = ''

    # 6 — Save + email
    print("\n[6/6] Saving to DynamoDB and sending approval email...")
    try:
        invoice_id = generate_invoice_id()
        save_invoice(invoice, key, invoice_id)
        send_approval_email(invoice, key, invoice_id, is_duplicate)
    except Exception as e:
        return {'status':'error','errors':[f"Save/email: {e}"],'invoice':invoice,'dup_reason':dup_reason,'invoice_id':''}

    status = 'duplicate_pending_approval' if is_duplicate else 'pending_approval'

    # Save result to AgentCore memory
    save_to_memory(session_id, invoice_id, invoice, status)

    print(f"\n{'='*55}")
    print(f"  AGENTCORE PIPELINE COMPLETE")
    print(f"  Invoice ID : {invoice_id}")
    print(f"  Status     : {status}")
    print(f"  Memory     : saved to {os.getenv('AGENTCORE_MEMORY_ID')}")
    print(f"{'='*55}\n")

    return {
        'status'    : status,
        'invoice_id': invoice_id,
        'invoice'   : invoice,
        'dup_reason': dup_reason,
        'errors'    : [],
        'session_id': session_id,
        'runtime_id': os.getenv('AGENTCORE_RUNTIME_ID'),
        'memory_id' : os.getenv('AGENTCORE_MEMORY_ID')
    }


def run_petty_cash_agent(bucket: str, key: str, submitter_email: str = '') -> dict:
    """Main entry point — backward compatible with agent_core.py."""
    session_id = str(uuid.uuid4())
    return invoke_agentcore_runtime(bucket, key, submitter_email, session_id)


if __name__ == '__main__':
    bucket          = os.getenv('S3_BUCKET_NAME')
    key             = sys.argv[1] if len(sys.argv) > 1 else 'test/sample_invoice.pdf'
    submitter_email = sys.argv[2] if len(sys.argv) > 2 else ''
    result = run_petty_cash_agent(bucket, key, submitter_email)
    print("\nFinal result:")
    print(json.dumps({
        'status'    : result.get('status'),
        'invoice_id': result.get('invoice_id'),
        'runtime_id': result.get('runtime_id'),
        'memory_id' : result.get('memory_id'),
        'session_id': result.get('session_id'),
    }, indent=2))