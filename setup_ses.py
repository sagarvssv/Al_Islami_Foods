import boto3, os
from dotenv import load_dotenv
load_dotenv(override=True)

session = boto3.Session(
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_DEFAULT_REGION')
)

ses = session.client('ses')

email = os.getenv('APPROVAL_EMAIL')
try:
    ses.verify_email_identity(EmailAddress=email)
    print(f"Verification email sent to: {email}")
    print("Check inbox and click the verification link.")
    print("Then run: python agent/agent_core.py test/sample_invoice.pdf")
except Exception as e:
    print(f"SES error: {e}")