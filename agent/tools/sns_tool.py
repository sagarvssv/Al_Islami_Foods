import boto3, os
from dotenv import load_dotenv
load_dotenv(override=True)

def get_session():
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


def send_approval_email(invoice: dict, s3_key: str, invoice_id: str, is_duplicate: bool = False):
    vendor   = invoice.get('vendor_name', 'Unknown')
    amount   = invoice.get('total_amount', 0)
    currency = invoice.get('currency', 'AED')
    category = invoice.get('category', 'Other')
    date     = invoice.get('invoice_date', 'N/A')
    inv_num  = invoice.get('invoice_number', 'N/A')
    tax      = invoice.get('tax_amount', 0)
    items    = invoice.get('line_items', [])

    api_url      = os.getenv('APPROVAL_API_URL', 'http://localhost:8000')
    approve_link = f"{api_url}/action?invoice_id={invoice_id}&action=approve"
    reject_link  = f"{api_url}/action?invoice_id={invoice_id}&action=reject"

    # Line items rows
    rows = ''
    for i, item in enumerate(items, 1):
        bg = '#f9f9f9' if i % 2 == 0 else '#ffffff'
        rows += f"""
        <tr style="background:{bg}">
          <td style="padding:8px 12px;border-bottom:1px solid #eee">{item.get('description','?')}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:center">{item.get('qty',1)}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right">{item.get('unit_price',0)}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;font-weight:600">{item.get('total',0)} {currency}</td>
        </tr>"""

    duplicate_banner = ''
    if is_duplicate:
        duplicate_banner = """
        <div style="background:#fff0f0;border:2px solid #cc0000;border-radius:8px;
                    padding:16px 20px;margin:20px 0">
          <p style="margin:0;color:#cc0000;font-size:16px;font-weight:700;
                    letter-spacing:0.5px">
            ⚠️ WARNING: POSSIBLE DUPLICATE INVOICE
          </p>
          <p style="margin:8px 0 0;color:#cc0000;font-size:13px;font-weight:600">
            An approved or pending invoice with the same invoice number or 
            matching vendor, amount and date already exists in the system.<br>
            Please review carefully before approving.
          </p>
        </div>"""

    subject_prefix = '[DUPLICATE] ' if is_duplicate else ''
    subject = f"{subject_prefix}[Al Islami Foods] Petty Cash Approval — {vendor} — {amount} {currency}"

    html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:30px 0">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0"
       style="background:#ffffff;border-radius:12px;overflow:hidden;
              box-shadow:0 2px 8px rgba(0,0,0,0.1)">

  <!-- Header -->
  <tr>
    <td style="background:linear-gradient(135deg,#1a472a,#2d6a4f);
               padding:28px 32px;text-align:center">
      <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700">
        🏢 Al Islami Foods
      </h1>
      <p style="margin:6px 0 0;color:#a8d5b5;font-size:14px">
        Petty Cash Approval Request
      </p>
    </td>
  </tr>

  <!-- Body -->
  <tr><td style="padding:28px 32px">

    {duplicate_banner}

    <!-- Invoice details -->
    <table width="100%" cellpadding="0" cellspacing="0"
           style="background:#f8f9fa;border-radius:8px;padding:0;
                  margin-bottom:24px;overflow:hidden">
      <tr style="background:#e9ecef">
        <td colspan="2" style="padding:12px 16px;font-weight:700;
                                font-size:13px;color:#495057;
                                text-transform:uppercase;letter-spacing:0.5px">
          Invoice Details
        </td>
      </tr>
      <tr>
        <td style="padding:10px 16px;color:#6c757d;font-size:13px;width:40%">Internal ID</td>
        <td style="padding:10px 16px;font-weight:600;font-size:13px;
                   font-family:monospace;color:#212529">{invoice_id}</td>
      </tr>
      <tr style="background:#ffffff">
        <td style="padding:10px 16px;color:#6c757d;font-size:13px">Vendor</td>
        <td style="padding:10px 16px;font-weight:600;font-size:13px;color:#212529">{vendor}</td>
      </tr>
      <tr>
        <td style="padding:10px 16px;color:#6c757d;font-size:13px">Invoice Number</td>
        <td style="padding:10px 16px;font-weight:600;font-size:13px;color:#212529">{inv_num}</td>
      </tr>
      <tr style="background:#ffffff">
        <td style="padding:10px 16px;color:#6c757d;font-size:13px">Invoice Date</td>
        <td style="padding:10px 16px;font-weight:600;font-size:13px;color:#212529">{date}</td>
      </tr>
      <tr>
        <td style="padding:10px 16px;color:#6c757d;font-size:13px">Category</td>
        <td style="padding:10px 16px;font-weight:600;font-size:13px;color:#212529">{category}</td>
      </tr>
      <tr style="background:#ffffff">
        <td style="padding:10px 16px;color:#6c757d;font-size:13px">Tax Amount</td>
        <td style="padding:10px 16px;font-weight:600;font-size:13px;color:#212529">{tax} {currency}</td>
      </tr>
      <tr style="background:#e8f5e9">
        <td style="padding:12px 16px;color:#2d6a4f;font-size:14px;font-weight:700">
          Total Amount
        </td>
        <td style="padding:12px 16px;font-weight:800;font-size:18px;color:#1a472a">
          {amount} {currency}
        </td>
      </tr>
    </table>

    <!-- Line items -->
    {'<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #dee2e6;border-radius:8px;overflow:hidden;margin-bottom:24px"><tr style="background:#343a40"><th style="padding:10px 12px;color:#fff;font-size:12px;text-align:left">Description</th><th style="padding:10px 12px;color:#fff;font-size:12px;text-align:center">Qty</th><th style="padding:10px 12px;color:#fff;font-size:12px;text-align:right">Unit Price</th><th style="padding:10px 12px;color:#fff;font-size:12px;text-align:right">Total</th></tr>' + rows + '</table>' if items else ''}

    <!-- S3 link -->
    <p style="font-size:12px;color:#6c757d;margin-bottom:24px">
      📎 Invoice file:
      <span style="font-family:monospace;color:#495057">
        s3://{os.getenv('S3_BUCKET_NAME')}/{s3_key}
      </span>
    </p>

    <!-- Action buttons -->
    <div style="text-align:center;padding:24px;background:#f8f9fa;
                border-radius:8px;margin-bottom:8px">
      <p style="margin:0 0 16px;font-size:14px;font-weight:600;color:#495057">
        Action Required — Please review and decide:
      </p>
      <a href="{approve_link}"
         style="display:inline-block;background:#28a745;color:#ffffff;
                text-decoration:none;padding:14px 36px;border-radius:6px;
                font-size:15px;font-weight:700;margin:0 8px;
                letter-spacing:0.5px">
        ✅ APPROVE
      </a>
      <a href="{reject_link}"
         style="display:inline-block;background:#dc3545;color:#ffffff;
                text-decoration:none;padding:14px 36px;border-radius:6px;
                font-size:15px;font-weight:700;margin:0 8px;
                letter-spacing:0.5px">
        ❌ REJECT
      </a>
    </div>

  </td></tr>

  <!-- Footer -->
  <tr>
    <td style="background:#f8f9fa;padding:16px 32px;text-align:center;
               border-top:1px solid #dee2e6">
      <p style="margin:0;font-size:11px;color:#adb5bd">
        Processed by Al Islami Foods Petty Cash AI
        &nbsp;|&nbsp; AWS AgentCore · Textract · Claude Sonnet 4.5
      </p>
    </td>
  </tr>

</table>
</td></tr>
</table>
</body>
</html>"""

    # Plain text fallback
    plain = f"""
AL ISLAMI FOODS - PETTY CASH APPROVAL
======================================
{'*** DUPLICATE INVOICE WARNING ***' if is_duplicate else ''}
Vendor      : {vendor}
Invoice No  : {inv_num}
Date        : {date}
Amount      : {amount} {currency}
Category    : {category}

APPROVE: {approve_link}
REJECT : {reject_link}
    """

    # Try SES first (HTML), fall back to SNS (plain text)
    try:
        ses = get_session().client('ses')
        ses.send_email(
            Source=os.getenv('APPROVAL_EMAIL'),
            Destination={'ToAddresses': [os.getenv('APPROVAL_EMAIL')]},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {
                    'Html': {'Data': html,  'Charset': 'UTF-8'},
                    'Text': {'Data': plain, 'Charset': 'UTF-8'}
                }
            }
        )
        print(f"  HTML email sent via SES to: {os.getenv('APPROVAL_EMAIL')}")
    except Exception as e:
        print(f"  SES failed ({str(e)[:60]}), falling back to SNS...")
        sns = get_session().client('sns')
        sns.publish(
            TopicArn=os.getenv('SNS_TOPIC_ARN'),
            Subject=subject,
            Message=plain
        )
        print(f"  Plain email sent via SNS to: {os.getenv('APPROVAL_EMAIL')}")