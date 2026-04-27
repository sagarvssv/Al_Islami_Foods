import boto3, os, json
from dotenv import load_dotenv
load_dotenv(override=True)

session = boto3.Session(
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_DEFAULT_REGION')
)

print("Checking all resources...\n")

# S3
s3 = session.client('s3')
s3.head_bucket(Bucket=os.getenv('S3_BUCKET_NAME'))
print(f"  S3 bucket   : OK  ({os.getenv('S3_BUCKET_NAME')})")

# SNS
sns  = session.client('sns')
attrs   = sns.get_topic_attributes(TopicArn=os.getenv('SNS_TOPIC_ARN'))
subs    = attrs['Attributes'].get('SubscriptionsConfirmed', '0')
pending = attrs['Attributes'].get('SubscriptionsPending', '0')
print(f"  SNS topic   : OK  (confirmed={subs}, pending={pending})")

# Bedrock — always reads from .env
model_id = os.getenv('BEDROCK_MODEL_ID')
print(f"  Using model : {model_id}")
bedrock = session.client('bedrock-runtime')
body = json.dumps({
    "anthropic_version": "bedrock-2023-05-31",
    "max_tokens": 20,
    "messages": [{"role": "user", "content": "say: ready"}]
})
resp   = bedrock.invoke_model(modelId=model_id, body=body)
result = json.loads(resp['body'].read())
print(f"  Bedrock LLM : OK  ({result['content'][0]['text'].strip()})")

print("\nAll systems ready. Proceed.")