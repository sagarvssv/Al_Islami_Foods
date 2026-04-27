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


def extract_invoice_text(bucket: str, key: str) -> dict:
    textract = get_session().client('textract')
    response = textract.analyze_document(
        Document={"S3Object": {"Bucket": bucket, "Name": key}},
        FeatureTypes=["FORMS", "TABLES"]
    )
    raw_lines = []
    for block in response["Blocks"]:
        if block["BlockType"] == "LINE":
            raw_lines.append(block["Text"])
    raw_text = "\n".join(raw_lines)
    print(f"  Textract extracted {len(raw_lines)} lines, {len(raw_text)} characters")
    return {"raw_text": raw_text, "blocks": response["Blocks"]}
