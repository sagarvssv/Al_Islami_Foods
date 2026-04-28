# agent/agent_core.py
# Now delegates to AgentCore runtime with memory
from agent.agentcore_runtime import run_petty_cash_agent

if __name__ == '__main__':
    import os, sys
    from dotenv import load_dotenv
    load_dotenv(override=True)
    bucket          = os.getenv('S3_BUCKET_NAME')
    key             = sys.argv[1] if len(sys.argv) > 1 else 'test/sample_invoice.pdf'
    submitter_email = sys.argv[2] if len(sys.argv) > 2 else ''
    result = run_petty_cash_agent(bucket, key, submitter_email)
    print("Status:", result.get('status'))
    print("Invoice ID:", result.get('invoice_id'))
    print("Runtime ID:", result.get('runtime_id'))
    print("Memory ID :", result.get('memory_id'))