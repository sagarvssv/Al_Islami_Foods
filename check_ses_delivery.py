import boto3, os
from dotenv import load_dotenv
load_dotenv(override=True)

session = boto3.Session(
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_DEFAULT_REGION')
)
ses = session.client('ses')

stats = ses.get_send_statistics()
points = stats['SendDataPoints']

if points:
    # Sort by timestamp
    points.sort(key=lambda x: x['Timestamp'])
    latest = points[-1]
    print(f"Latest SES sending stats:")
    print(f"  Timestamp  : {latest['Timestamp']}")
    print(f"  DeliveryAttempts : {latest['DeliveryAttempts']}")
    print(f"  Bounces          : {latest['Bounces']}")
    print(f"  Complaints       : {latest['Complaints']}")
    print(f"  Rejects          : {latest['Rejects']}")
else:
    print("No sending stats yet.")