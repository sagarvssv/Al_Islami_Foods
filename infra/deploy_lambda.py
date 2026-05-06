import boto3, os, zipfile, shutil, time
from dotenv import load_dotenv, set_key
load_dotenv(override=True)

session = boto3.Session(
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_DEFAULT_REGION')
)

FUNCTION_NAME = 'al-islami-petty-cash-agent'
ROLE_ARN      = os.getenv('LAMBDA_ROLE_ARN')

# ─── 1. Build zip ─────────────────────────────────────────────────────────
print("[1/3] Building deployment package...")
if os.path.exists('lambda_package'):
    shutil.rmtree('lambda_package')
os.makedirs('lambda_package')

shutil.copytree('agent',  'lambda_package/agent')
shutil.copytree('lambda', 'lambda_package/lambda')

os.system('pip install boto3 python-dotenv -t lambda_package/ -q')

zip_path = 'lambda_deploy.zip'
with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk('lambda_package'):
        dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__', '.venv', 'venv']]
        for file in files:
            if file in ['.env', '.env.local', '.gitignore']:
                continue
            if file.endswith('.pyc'):
                continue
            filepath = os.path.join(root, file)
            arcname  = os.path.relpath(filepath, 'lambda_package')
            zf.write(filepath, arcname)

size_mb = os.path.getsize(zip_path) / 1024 / 1024
print(f"  Package size: {size_mb:.1f} MB")

# ─── 2. Deploy Lambda ──────────────────────────────────────────────────────
print("\n[2/3] Deploying Lambda function...")
lam = session.client('lambda')

env_vars = {
    'S3_BUCKET_NAME'  : os.getenv('S3_BUCKET_NAME'),
    'SNS_TOPIC_ARN'   : os.getenv('SNS_TOPIC_ARN'),
    'BEDROCK_MODEL_ID': os.getenv('BEDROCK_MODEL_ID'),
    'APPROVAL_EMAIL'  : os.getenv('APPROVAL_EMAIL'),
    'DYNAMODB_TABLE'  : os.getenv('DYNAMODB_TABLE', 'al-islami-petty-cash'),
    'APPROVAL_API_URL': os.getenv('APPROVAL_API_URL', 'http://localhost:8000'),
    'MAX_AMOUNT_AED'  : os.getenv('MAX_AMOUNT_AED', '5000'),
    'AWS_ACCOUNT_ID'  : os.getenv('AWS_ACCOUNT_ID', '501991669369'),
}

with open(zip_path, 'rb') as f:
    zip_bytes = f.read()

def wait_for_lambda_ready(lam, function_name, max_attempts=30):
    """Wait until Lambda is not in an updating state."""
    for i in range(max_attempts):
        fn    = lam.get_function_configuration(FunctionName=function_name)
        state = fn.get('LastUpdateStatus', 'Successful')
        print(f"  Lambda state: {state} ({i+1}/{max_attempts})")
        if state in ['Successful', 'Failed']:
            return True
        time.sleep(5)
    return False

try:
    response = lam.create_function(
        FunctionName=FUNCTION_NAME,
        Runtime='python3.11',
        Role=ROLE_ARN,
        Handler='lambda.s3_trigger.handler',
        Code={'ZipFile': zip_bytes},
        Timeout=180,
        MemorySize=512,
        Environment={'Variables': env_vars}
    )
    fn_arn = response['FunctionArn']
    print(f"  Lambda created: {fn_arn}")

except lam.exceptions.ResourceConflictException:
    print("  Lambda exists — waiting for it to be ready...")
    wait_for_lambda_ready(lam, FUNCTION_NAME)

    print("  Updating Lambda code...")
    response = lam.update_function_code(
        FunctionName=FUNCTION_NAME,
        ZipFile=zip_bytes
    )
    fn_arn = response['FunctionArn']
    print(f"  Code updated: {fn_arn}")

    print("  Waiting for code update to finish...")
    wait_for_lambda_ready(lam, FUNCTION_NAME)

    print("  Updating Lambda configuration...")
    lam.update_function_configuration(
        FunctionName=FUNCTION_NAME,
        Environment={'Variables': env_vars},
        Timeout=180,
        MemorySize=512
    )
    print(f"  Config updated.")

# ─── 3. S3 trigger PERMANENTLY DISABLED ──────────────────────────────────────
print("[3/3] S3 trigger DISABLED — Railway handles all processing")
print("      Not attaching S3 trigger to prevent duplicate invoice records")
print("      Railway /upload endpoint is the only invoice processor")

fn_arn = lam.get_function_configuration(FunctionName=FUNCTION_NAME)['FunctionArn']
set_key('.env', 'LAMBDA_FUNCTION_ARN', fn_arn)

