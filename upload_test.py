import boto3, os, sys
from dotenv import load_dotenv
load_dotenv()

session = boto3.Session(
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_DEFAULT_REGION')
)
s3        = session.client('s3')
local_pdf = sys.argv[1] if len(sys.argv) > 1 else 'sample_invoice.pdf'
s3_key    = f"test/{os.path.basename(local_pdf)}"

s3.upload_file(local_pdf, os.getenv('S3_BUCKET_NAME'), s3_key)
print(f"Uploaded: {local_pdf} → s3://{os.getenv('S3_BUCKET_NAME')}/{s3_key}")
print(f"\nNow run:")
print(f"  python agent/agent_core.py {s3_key}")