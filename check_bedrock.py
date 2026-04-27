import boto3, os
from dotenv import load_dotenv
load_dotenv()

session = boto3.Session(
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_DEFAULT_REGION')
)

bedrock = session.client('bedrock')
models = bedrock.list_foundation_models(byProvider='Anthropic')

print('\nAvailable Anthropic models in your account:\n')
for m in models['modelSummaries']:
    model_id   = m['modelId']
    model_name = m['modelName']
    status     = m.get('modelLifecycle', {}).get('status', 'unknown')
    print(f"  {model_id}  |  {model_name}  |  Status: {status}")