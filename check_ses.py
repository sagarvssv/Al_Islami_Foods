import boto3, os
from dotenv import load_dotenv
load_dotenv(override=True)

session = boto3.Session(
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_DEFAULT_REGION')
)
ses = session.client('ses')

# Check verification status
identities = ses.list_identities(IdentityType='EmailAddress')
print("Registered SES identities:")
for identity in identities['Identities']:
    attrs = ses.get_identity_verification_attributes(
        Identities=[identity]
    )
    status = attrs['VerificationAttributes'].get(
        identity, {}
    ).get('VerificationStatus', 'Unknown')
    print(f"  {identity} — {status}")

# Check sending quota
quota = ses.get_send_quota()
print(f"\nSES Sending quota:")
print(f"  Max per day  : {quota['Max24HourSend']}")
print(f"  Sent today   : {quota['SentLast24Hours']}")
print(f"  Max per sec  : {quota['MaxSendRate']}")

# Check if in sandbox
print(f"\nSES Sandbox status:")
try:
    result = ses.get_account_sending_enabled()
    print(f"  Sending enabled: {result['Enabled']}")
except Exception as e:
    print(f"  {e}")