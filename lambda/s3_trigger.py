# lambda/s3_trigger.py
import json, sys, os
sys.path.insert(0, '/opt/python')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.agent_core import run_petty_cash_agent

def handler(event, context):
    print(f"Lambda triggered with event: {json.dumps(event)}")
    results = []
    for record in event.get('Records', []):
        bucket = record['s3']['bucket']['name']
        key    = record['s3']['object']['key']
        # Only process PDF and image files
        if not any(key.lower().endswith(ext) for ext in ['.pdf','.png','.jpg','.jpeg']):
            print(f"Skipping non-invoice file: {key}")
            continue
        print(f"Processing: s3://{bucket}/{key}")
        result = run_petty_cash_agent(bucket, key)
        results.append(result)
        print(f"Result: {json.dumps(result, default=str)}")
    return {
        'statusCode': 200,
        'body': json.dumps(results, default=str)
    }