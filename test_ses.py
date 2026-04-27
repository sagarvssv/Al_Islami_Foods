# save as test_ses.py
import boto3, os
from dotenv import load_dotenv
load_dotenv(override=True)

session = boto3.Session(
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_DEFAULT_REGION')
)
ses = session.client('ses')
ses.send_email(
    Source=os.getenv('APPROVAL_EMAIL'),
    Destination={'ToAddresses': [os.getenv('APPROVAL_EMAIL')]},
    Message={
        'Subject': {'Data': 'SES Test - Al Islami Foods'},
        'Body'   : {'Text': {'Data': 'SES is working correctly.'}}
    }
)
print("SES test email sent successfully!")