import os

NEW_SESSION = '''def get_session():
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
'''

tools = [
    'agent/tools/s3_tool.py',
    'agent/tools/textract_tool.py',
    'agent/tools/llm_tool.py',
    'agent/tools/sns_tool.py',
    'agent/tools/dynamodb_tool.py',
]

for path in tools:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(path, 'r', encoding='cp1252') as f:
            content = f.read()

    start = content.find('def get_session():')
    if start == -1:
        print(f"  SKIP (no get_session): {path}")
        continue

    end = content.find('\ndef ', start + 1)
    if end == -1:
        end = len(content)

    new_content = content[:start] + NEW_SESSION + '\n' + content[end:]

    with open(path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"  Fixed: {path}")

print("\nAll sessions updated.")