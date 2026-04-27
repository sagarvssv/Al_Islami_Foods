import boto3, os
from dotenv import load_dotenv
load_dotenv()

session = boto3.Session(
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_DEFAULT_REGION')
)

dynamodb = session.client('dynamodb')

try:
    dynamodb.create_table(
        TableName='al-islami-petty-cash',
        KeySchema=[
            {'AttributeName': 'invoice_id', 'KeyType': 'HASH'}
        ],
        AttributeDefinitions=[
            {'AttributeName': 'invoice_id', 'AttributeType': 'S'}
        ],
        BillingMode='PAY_PER_REQUEST'
    )
    print("DynamoDB table created: al-islami-petty-cash")
except dynamodb.exceptions.ResourceInUseException:
    print("DynamoDB table already exists: al-islami-petty-cash")

# Also create API Gateway + Lambda for approve/reject
# We'll use a simple Lambda URL instead
print("\nNext: run python infra/setup_lambda.py")