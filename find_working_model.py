import boto3, os, json
from dotenv import load_dotenv
load_dotenv()

session = boto3.Session(
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_DEFAULT_REGION')
)
bedrock = session.client('bedrock-runtime')

# All active EU models from your profiles list
models = [
    'eu.anthropic.claude-sonnet-4-5-20250929-v1:0',
    'eu.anthropic.claude-sonnet-4-20250514-v1:0',
    'eu.anthropic.claude-opus-4-5-20251101-v1:0',
    'eu.anthropic.claude-haiku-4-5-20251001-v1:0',
    'eu.anthropic.claude-3-7-sonnet-20250219-v1:0',
]

body = json.dumps({
    "anthropic_version": "bedrock-2023-05-31",
    "max_tokens": 10,
    "messages": [{"role": "user", "content": "say: ready"}]
})

print("Testing each model...\n")
working = None
for model_id in models:
    try:
        resp   = bedrock.invoke_model(modelId=model_id, body=body)
        result = json.loads(resp['body'].read())
        text   = result['content'][0]['text'].strip()
        print(f"  WORKS : {model_id}  -> '{text}'")
        if not working:
            working = model_id
    except Exception as e:
        short = str(e)[:80]
        print(f"  FAIL  : {model_id}")
        print(f"          {short}")

if working:
    print(f"\nBest model: {working}")
    from dotenv import set_key
    set_key('.env', 'BEDROCK_MODEL_ID', working)
    print(f"Updated .env with working model.")
else:
    print("\nNo working model found.")
    print("Go to AWS Console -> Bedrock -> Model Access and enable a Claude model.")