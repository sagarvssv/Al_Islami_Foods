# infra/deploy.py
import boto3, os, sys
from dotenv import load_dotenv, set_key

load_dotenv()

ENV_FILE = os.path.join(os.path.dirname(__file__), '..', '.env')

session = boto3.Session(
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_DEFAULT_REGION')
)

BUCKET_NAME    = 'al-islami-petty-cash-invoices'
SNS_TOPIC_NAME = 'al-islami-petty-cash-approval'
APPROVAL_EMAIL = os.getenv('APPROVAL_EMAIL', 'finance.manager@alislami.com')
REGION         = os.getenv('AWS_DEFAULT_REGION', 'us-east-1')

# ─── 1. Create S3 Bucket ───────────────────────────────────────────────────
print("\n[1/3] Creating S3 bucket...")
s3 = session.client('s3')
try:
    if REGION == 'us-east-1':
        s3.create_bucket(Bucket=BUCKET_NAME)
    else:
        s3.create_bucket(
            Bucket=BUCKET_NAME,
            CreateBucketConfiguration={'LocationConstraint': REGION}
        )

    # Block all public access (security best practice)
    s3.put_public_access_block(
        Bucket=BUCKET_NAME,
        PublicAccessBlockConfiguration={
            'BlockPublicAcls': True,
            'IgnorePublicAcls': True,
            'BlockPublicPolicy': True,
            'RestrictPublicBuckets': True
        }
    )
    print(f"  S3 bucket created : {BUCKET_NAME}")
    set_key(ENV_FILE, 'S3_BUCKET_NAME', BUCKET_NAME)

except s3.exceptions.BucketAlreadyOwnedByYou:
    print(f"  S3 bucket already exists (owned by you): {BUCKET_NAME}")
    set_key(ENV_FILE, 'S3_BUCKET_NAME', BUCKET_NAME)
except Exception as e:
    print(f"  ERROR creating S3 bucket: {e}")
    sys.exit(1)

# ─── 2. Create SNS Topic ───────────────────────────────────────────────────
print("\n[2/3] Creating SNS topic...")
sns = session.client('sns')
try:
    response   = sns.create_topic(Name=SNS_TOPIC_NAME)
    topic_arn  = response['TopicArn']
    print(f"  SNS topic created : {topic_arn}")

    # Subscribe approval email
    sns.subscribe(
        TopicArn=topic_arn,
        Protocol='email',
        Endpoint=APPROVAL_EMAIL
    )
    print(f"  Subscribed email  : {APPROVAL_EMAIL}")
    print(f"  *** CHECK INBOX — click confirmation link before testing! ***")

    # Write real ARN back to .env
    set_key(ENV_FILE, 'SNS_TOPIC_ARN', topic_arn)

except Exception as e:
    print(f"  ERROR creating SNS topic: {e}")
    sys.exit(1)

# ─── 3. Verify Bedrock Access ──────────────────────────────────────────────
print("\n[3/3] Checking Bedrock model access...")
bedrock = session.client('bedrock')
try:
    models = bedrock.list_foundation_models(byProvider='Anthropic')
    accessible = []
    for m in models['modelSummaries']:
        mid = m['modelId']
        accessible.append(mid)
        print(f"  {mid}")

    # Pick best available model
    # Pick best available model
    preferred = [
        'anthropic.claude-haiku-4-5-20251001-v1:0',
        'anthropic.claude-sonnet-4-5-20250929-v1:0',
        'anthropic.claude-sonnet-4-6',
        'anthropic.claude-3-haiku-20240307-v1:0',
    ]
    chosen = None
    for p in preferred:
        if p in accessible:
            chosen = p
            break

    if chosen:
        print(f"\n  Selected model: {chosen}")
        set_key(ENV_FILE, 'BEDROCK_MODEL_ID', chosen)
    else:
        print("\n  WARNING: No preferred Claude model found.")
        print("  Go to AWS Console -> Bedrock -> Model Access -> Enable a Claude model.")

except Exception as e:
    print(f"  ERROR checking Bedrock: {e}")
    print("  Make sure Bedrock is available in your region and IAM has AmazonBedrockFullAccess")

# ─── Summary ──────────────────────────────────────────────────────────────
print("\n" + "="*55)
print("DONE — .env has been updated with real values.")
print("="*55)
print(f"  S3 Bucket   : {BUCKET_NAME}")
print(f"  SNS Topic   : {topic_arn}")
print(f"  Region      : {REGION}")
print("\nNext steps:")
print("  1. Confirm SNS subscription email in inbox")
print("  2. Enable Bedrock model access in AWS Console if needed")
print("  3. Run: python agent/agent_core.py")