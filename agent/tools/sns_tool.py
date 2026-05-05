import boto3, os
from dotenv import load_dotenv
load_dotenv(override=True)

def get_session():
    return boto3.Session(
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name=os.getenv('AWS_DEFAULT_REGION')
    )

def send_approval_email(invoice: dict, s3_key: str, invoice_id: str, is_duplicate: bool = False):
    vendor_raw  = (invoice.get('vendor_name') or '').strip()
    vendor      = '' if vendor_raw.lower() in ['unknown','unknown vendor','n/a','none',''] else vendor_raw
    amount_raw  = invoice.get('total_amount', 0)
    try:
        amount_val = float(str(amount_raw).replace(',','').replace(' ','') or 0)
    except:
        amount_val = 0
    amount      = amount_raw
    curr        = invoice.get('currency', 'AED')
    inv_num_raw = (invoice.get('invoice_number') or '').strip()
    if inv_num_raw.lower() in ['unknown','n/a','none','null','-','--','']:
        inv_num_raw = ''
    inv_num     = inv_num_raw if inv_num_raw else 'Not found'
    date        = invoice.get('invoice_date', '')
    cat         = invoice.get('category', 'Other')
    submitter   = invoice.get('submitter_email', '')

    APPROVAL_API_URL = os.getenv('APPROVAL_API_URL', 'https://web-production-40aa02.up.railway.app')
    approve_link = f"{APPROVAL_API_URL}/action?invoice_id={invoice_id}&action=approve&level=1"
    reject_link  = f"{APPROVAL_API_URL}/action?invoice_id={invoice_id}&action=reject&level=1"

    # ── Detect missing fields ────────────────────────────────────────────
    vendor_missing = not vendor
    amount_missing = amount_val <= 0
    inv_no_missing = not inv_num_raw

    missing_fields = []
    if vendor_missing: missing_fields.append('Vendor Name')
    if amount_missing: missing_fields.append('Invoice Amount')
    if inv_no_missing: missing_fields.append('Invoice Number')

    # ── Build banners ────────────────────────────────────────────────────
    dup_banner = ''
    if is_duplicate:
        dup_banner = """<div style="background:#fff0f0;border:2px solid #cc0000;border-radius:8px;padding:14px 18px;margin:0 0 14px">
<p style="margin:0 0 5px;color:#cc0000;font-size:14px;font-weight:800">⚠️ WARNING: POSSIBLE DUPLICATE INVOICE</p>
<p style="margin:0;color:#cc0000;font-size:12px">An approved or pending invoice with the same details already exists. Please review carefully before approving.</p>
</div>"""

    verify_banner = ''
    if missing_fields:
        missing_str = ', '.join(missing_fields)
        if is_duplicate:
            title = '⚠️ DUPLICATE + MISSING DATA — MANUAL APPROVAL REQUIRED'
            body  = f'This invoice is a possible <strong>duplicate</strong> AND has missing data: <strong>{missing_str}</strong>. Please open the original file in S3 and verify before approving.'
        else:
            title = '⚠️ MISSING DATA — PLEASE APPROVE MANUALLY'
            body  = f'The following could not be automatically extracted: <strong>{missing_str}</strong>. Please open the original invoice file in S3 and verify the details before approving.'

        bucket = os.getenv('S3_BUCKET_NAME','al-islami-petty-cash-invoices')
        verify_banner = f"""<div style="background:#fff8e1;border:2px solid #f59e0b;border-radius:8px;padding:16px 20px;margin:0 0 14px">
<p style="margin:0 0 8px;color:#b45309;font-size:14px;font-weight:800">{title}</p>
<p style="margin:0 0 10px;color:#92400e;font-size:13px">{body}</p>
<div style="background:#fef3c7;border-radius:6px;padding:10px 14px">
  <p style="margin:0;font-size:12px;color:#78350f;font-weight:600">📎 Original invoice file:</p>
  <p style="margin:4px 0 0;font-size:12px;color:#92400e;word-break:break-all">s3://{bucket}/{s3_key}</p>
  <p style="margin:6px 0 0;font-size:11px;color:#92400e">Open in AWS S3 Console to view the original invoice.</p>
</div>
</div>"""

    # ── Email subject ────────────────────────────────────────────────────
    prefix = '[DUPLICATE] ' if is_duplicate else ''
    warn   = '[ACTION REQUIRED] ' if missing_fields else ''
    subject = f"{prefix}{warn}[Al Islami Foods] Petty Cash Approval — {vendor_raw or 'Unknown Vendor'} — {amount} {curr}"

    inv_num_display = f'<span style="font-weight:600">{inv_num_raw}</span>' if inv_num_raw else '<span style="color:#e65100;font-weight:600">⚠️ Not found — check manually</span>'
    vendor_display  = f'<span style="font-weight:600">{vendor_raw}</span>' if vendor_raw else '<span style="color:#e65100;font-weight:600">⚠️ Unknown — check manually</span>'
    amount_display  = f'<span style="font-weight:800;font-size:16px;color:{"#1a472a" if amount_val > 0 else "#e65100"}">{amount} {curr}{"" if amount_val > 0 else " ⚠️"}</span>'

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:'Segoe UI',Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:30px 0">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0"
  style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1)">
  <tr>
    <td style="background:linear-gradient(135deg,#1a472a,#2d6a4f);padding:22px 32px;text-align:center">
      <h1 style="margin:0;color:#fff;font-size:20px;font-weight:700">🌿 Al Islami Foods</h1>
      <p style="margin:4px 0 0;color:#a8d5b5;font-size:12px">Petty Cash — Approval Request (Level 1 of 2)</p>
    </td>
  </tr>
  <tr><td style="padding:22px 28px">
    {dup_banner}
    {verify_banner}
    <table width="100%" cellpadding="0" cellspacing="0"
           style="background:#f8f9fa;border-radius:8px;overflow:hidden;margin-bottom:18px">
      <tr style="background:#e9ecef">
        <td colspan="2" style="padding:10px 16px;font-weight:700;font-size:11px;
            color:#495057;text-transform:uppercase;letter-spacing:.5px">Invoice Details</td>
      </tr>
      <tr><td style="padding:8px 16px;color:#6c757d;font-size:13px;width:38%">Internal ID</td>
          <td style="padding:8px 16px;font-family:monospace;font-weight:600">{invoice_id}</td></tr>
      <tr style="background:#fff">
          <td style="padding:8px 16px;color:#6c757d;font-size:13px">Vendor</td>
          <td style="padding:8px 16px">{vendor_display}</td></tr>
      <tr><td style="padding:8px 16px;color:#6c757d;font-size:13px">Invoice No</td>
          <td style="padding:8px 16px">{inv_num_display}</td></tr>
      <tr style="background:#fff">
          <td style="padding:8px 16px;color:#6c757d;font-size:13px">Date</td>
          <td style="padding:8px 16px;font-weight:600">{date or "—"}</td></tr>
      <tr><td style="padding:8px 16px;color:#6c757d;font-size:13px">Category</td>
          <td style="padding:8px 16px;font-weight:600">{cat}</td></tr>
      <tr style="background:#fff">
          <td style="padding:8px 16px;color:#6c757d;font-size:13px">Total Amount</td>
          <td style="padding:8px 16px">{amount_display}</td></tr>
      {"<tr><td style='padding:8px 16px;color:#6c757d;font-size:13px'>Submitter</td><td style='padding:8px 16px;font-size:12px;color:#495057'>" + submitter + "</td></tr>" if submitter else ""}
    </table>
    <div style="text-align:center;padding:18px;background:#f8f9fa;border-radius:8px">
      <p style="margin:0 0 12px;font-size:14px;font-weight:600;color:#495057">
        Action Required — Financial Manager (Level 1 of 2)
      </p>
      <a href="{approve_link}"
         style="display:inline-block;background:#28a745;color:#fff;text-decoration:none;
                padding:12px 30px;border-radius:6px;font-size:14px;font-weight:700;margin:0 6px">
        ✅ APPROVE
      </a>
      <a href="{reject_link}"
         style="display:inline-block;background:#dc3545;color:#fff;text-decoration:none;
                padding:12px 30px;border-radius:6px;font-size:14px;font-weight:700;margin:0 6px">
        ❌ REJECT
      </a>
    </div>
    <p style="font-size:11px;color:#adb5bd;text-align:center;margin-top:12px">
      📎 s3://{os.getenv("S3_BUCKET_NAME","al-islami-petty-cash-invoices")}/{s3_key}
    </p>
  </td></tr>
  <tr>
    <td style="background:#f8f9fa;padding:12px 28px;text-align:center;border-top:1px solid #dee2e6">
      <p style="margin:0;font-size:11px;color:#adb5bd">
        Al Islami Foods Petty Cash AI &nbsp;|&nbsp; AgentCore · Textract · Claude
      </p>
    </td>
  </tr>
</table>
</td></tr>
</table>
</body></html>"""

    plain = f"""Al Islami Foods — Petty Cash Approval (Level 1)
{"DUPLICATE INVOICE WARNING" if is_duplicate else ""}
{"MISSING DATA - PLEASE VERIFY MANUALLY: " + ", ".join(missing_fields) if missing_fields else ""}
Vendor: {vendor_raw or "Unknown"} | Invoice No: {inv_num_raw or "NOT FOUND"} | Amount: {amount} {curr}
APPROVE: {approve_link}
REJECT:  {reject_link}
File: s3://{os.getenv("S3_BUCKET_NAME","al-islami-petty-cash-invoices")}/{s3_key}"""

    try:
        ses = get_session().client('ses')
        manager_email = os.getenv('APPROVAL_EMAIL')
        ses.send_email(
            Source=manager_email,
            Destination={'ToAddresses': [manager_email]},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {
                    'Html': {'Data': html,  'Charset': 'UTF-8'},
                    'Text': {'Data': plain, 'Charset': 'UTF-8'}
                }
            }
        )
        print(f"  HTML email sent via SES to: {manager_email}")
        if missing_fields:
            print(f"  [WARNING] Missing fields flagged: {missing_fields}")
    except Exception as e:
        print(f"  SES failed: {e} — trying SNS...")
        try:
            sns = get_session().client('sns')
            sns.publish(
                TopicArn=os.getenv('SNS_TOPIC_ARN'),
                Subject=subject[:100],
                Message=plain
            )
            print(f"  SNS fallback sent")
        except Exception as e2:
            print(f"  SNS also failed: {e2}")
