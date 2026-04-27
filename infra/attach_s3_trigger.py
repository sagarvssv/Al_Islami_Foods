import boto3, os, time
from dotenv import load_dotenv, set_key
load_dotenv(override=True)

session = boto3.Session(
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_DEFAULT_REGION')
)

lam    = session.client('lambda')
s3     = session.client('s3')
BUCKET = os.getenv('S3_BUCKET_NAME')
FNAME  = 'al-islami-petty-cash-agent'

# Get exact Lambda ARN
fn     = lam.get_function(FunctionName=FNAME)
fn_arn = fn['Configuration']['FunctionArn']
print(f"Lambda ARN: {fn_arn}")

# Add S3 permission to invoke Lambda
print("Adding S3 invoke permission...")
try:
    lam.add_permission(
        FunctionName=FNAME,
        StatementId='s3-invoke-trigger',
        Action='lambda:InvokeFunction',
        Principal='s3.amazonaws.com',
        SourceArn=f"arn:aws:s3:::{BUCKET}",
        SourceAccount=os.getenv('AWS_ACCOUNT_ID', '501991669369')
    )
    print("  Permission added.")
except lam.exceptions.ResourceConflictException:
    print("  Permission already exists.")

# Wait for permission to propagate
print("Waiting 10 seconds for permission to propagate...")
time.sleep(10)

# Attach S3 trigger
print("Attaching S3 event trigger...")
s3.put_bucket_notification_configuration(
    Bucket=BUCKET,
    NotificationConfiguration={
        'LambdaFunctionConfigurations': [{
            'LambdaFunctionArn': fn_arn,
            'Events': ['s3:ObjectCreated:*'],
            'Filter': {'Key': {'FilterRules': [
                {'Name': 'suffix', 'Value': '.pdf'}
            ]}}
        }]
    }
)

set_key('.env', 'LAMBDA_FUNCTION_ARN', fn_arn)

print(f"\n{'='*55}")
print(f"S3 TRIGGER ATTACHED SUCCESSFULLY")
print(f"  Bucket   : {BUCKET}")
print(f"  Trigger  : Any .pdf upload → Lambda")
print(f"  Function : {FNAME}")
print(f"{'='*55}")
print(f"\nTest: upload any PDF to S3 and check CloudWatch logs")
print(f"  python upload_test.py")