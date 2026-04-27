import boto3, os, time
from dotenv import load_dotenv
load_dotenv(override=True)

session = boto3.Session(
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_DEFAULT_REGION')
)

logs  = session.client('logs')
group = '/aws/lambda/al-islami-petty-cash-agent'

print(f"Watching CloudWatch logs for Lambda...")
print(f"Log group: {group}")
print(f"Waiting for new invocation...\n")

# Get latest log stream
seen_events = set()
start_time  = int(time.time() * 1000) - 60000  # last 60 seconds

for attempt in range(30):
    try:
        streams = logs.describe_log_streams(
            logGroupName=group,
            orderBy='LastEventTime',
            descending=True,
            limit=3
        )
        if not streams['logStreams']:
            print(f"  No log streams yet... waiting ({attempt+1}/30)")
            time.sleep(5)
            continue

        for stream in streams['logStreams']:
            stream_name = stream['logStreamName']
            events = logs.get_log_events(
                logGroupName=group,
                logStreamName=stream_name,
                startTime=start_time,
                startFromHead=True
            )
            for event in events['events']:
                event_id = event['timestamp']
                if event_id not in seen_events:
                    seen_events.add(event_id)
                    msg = event['message'].strip()
                    if msg:
                        print(f"  {msg}")

        time.sleep(3)

    except logs.exceptions.ResourceNotFoundException:
        print(f"  Log group not created yet — Lambda hasn't run yet ({attempt+1}/30)")
        time.sleep(5)
    except KeyboardInterrupt:
        print("\nStopped watching logs.")
        break