import boto3, os
from dotenv import load_dotenv
load_dotenv()

session = boto3.Session(
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_DEFAULT_REGION')
)

bedrock = session.client('bedrock')

print("Available inference profiles:\n")
response = bedrock.list_inference_profiles()
for p in response['inferenceProfileSummaries']:
    print(f"  ID   : {p['inferenceProfileId']}")
    print(f"  Name : {p['inferenceProfileName']}")
    print(f"  ARN  : {p['inferenceProfileArn']}")
    print()