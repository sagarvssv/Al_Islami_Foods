import boto3, os, json
from dotenv import load_dotenv
load_dotenv(override=True)

session = boto3.Session(
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_DEFAULT_REGION')
)

iam        = session.client('iam')
ROLE_NAME  = 'al-islami-petty-cash-lambda-role'

trust = json.dumps({
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "lambda.amazonaws.com"},
        "Action": "sts:AssumeRole"
    }]
})

try:
    role = iam.create_role(
        RoleName=ROLE_NAME,
        AssumeRolePolicyDocument=trust,
        Description='Al Islami Petty Cash Lambda Role'
    )
    role_arn = role['Role']['Arn']
    print(f"Role created: {role_arn}")
except iam.exceptions.EntityAlreadyExistsException:
    role_arn = iam.get_role(RoleName=ROLE_NAME)['Role']['Arn']
    print(f"Role exists: {role_arn}")

# Attach required policies
policies = [
    'arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess',
    'arn:aws:iam::aws:policy/AmazonTextractFullAccess',
    'arn:aws:iam::aws:policy/AmazonSNSFullAccess',
    'arn:aws:iam::aws:policy/AmazonBedrockFullAccess',
    'arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess',
    'arn:aws:iam::aws:policy/AmazonSESFullAccess',
    'arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole',
]
for p in policies:
    iam.attach_role_policy(RoleName=ROLE_NAME, PolicyArn=p)
    print(f"  Attached: {p.split('/')[-1]}")

from dotenv import set_key
set_key('.env', 'LAMBDA_ROLE_ARN', role_arn)
print(f"\nRole ARN saved to .env: {role_arn}")
print("Next: python infra/deploy_lambda.py")