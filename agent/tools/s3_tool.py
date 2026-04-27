import boto3, os
from dotenv import load_dotenv
load_dotenv()

def get_session():
    key    = os.getenv('AWS_ACCESS_KEY_ID', '').strip()
    secret = os.getenv('AWS_SECRET_ACCESS_KEY', '').strip()
    region = os.getenv('AWS_DEFAULT_REGION', 'eu-central-1')
    # Only use explicit credentials if both are real values
    # Lambda IAM role keys start with ASIA, local keys start with AKIA
    if key and secret and key.startswith('AK'):
        return boto3.Session(
            aws_access_key_id=key,
            aws_secret_access_key=secret,
            region_name=region
        )
    else:
        # Lambda — use IAM role automatically
        return boto3.Session(region_name=region)


def download_invoice(bucket: str, key: str) -> bytes:
    s3 = get_session().client('s3')
    response = s3.get_object(Bucket=bucket, Key=key)
    print(f"  Downloaded: s3://{bucket}/{key}")
    return response['Body'].read()
