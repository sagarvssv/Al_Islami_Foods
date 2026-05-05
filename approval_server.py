from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import os, json, threading, tempfile, uuid, boto3
from dotenv import load_dotenv
load_dotenv(override=True)

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from agent.tools.dynamodb_tool import (
        update_invoice_status, get_invoice,
        update_approval_status, update_final_status
    )
    print("[OK] Agent tools imported successfully")
except Exception as e:
    print(f"[ERROR] Failed to import agent tools: {e}")
    def update_invoice_status(invoice_id, status): pass
    def get_invoice(invoice_id): return None
    def update_approval_status(invoice_id, level, status): pass
    def update_final_status(invoice_id, status): pass

try:
    from agent.agentcore_runtime import run_petty_cash_agent
    print("[OK] AgentCore runtime imported successfully")
except Exception as e:
    print(f"[WARN] AgentCore not available: {e}")
    try:
        from agent.agent_core import run_petty_cash_agent
        print("[OK] Fallback to agent_core")
    except Exception as e2:
        print(f"[ERROR] Could not import agent: {e2}")
        def run_petty_cash_agent(bucket, key, submitter_email=''):
            return {'status':'error','errors':['Agent not available'],'invoice':{},'dup_reason':'','invoice_id':''}

pipeline_status  = {}
MANAGER1_EMAIL   = os.getenv('APPROVAL_EMAIL', '')
MANAGER2_EMAIL   = os.getenv('MANAGER2_EMAIL', '')
APPROVAL_API_URL = os.getenv('APPROVAL_API_URL', 'https://web-production-40aa02.up.railway.app')

def get_aws_session():
    return boto3.Session(
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name=os.getenv('AWS_DEFAULT_REGION', 'eu-central-1')
    )

def get_all_records():
    table = get_aws_session().resource('dynamodb').Table(
        os.getenv('DYNAMODB_TABLE', 'al-islami-petty-cash')
    )
    return table.scan().get('Items', [])

def ensure_ses_verified(email: str) -> bool:
    try:
        ses    = get_aws_session().client('ses')
        attrs  = ses.get_identity_verification_attributes(Identities=[email])
        status = attrs['VerificationAttributes'].get(email, {}).get('VerificationStatus', '')
        if status == 'Success':
            return True
        ses.verify_email_identity(EmailAddress=email)
        print(f"[SES] Verification sent to {email}")
        return False
    except Exception as e:
        print(f"[SES] Error: {e}")
        return False

def send_approval_request_email(invoice: dict, invoice_id: str, level: int,
                                to_email: str, is_duplicate: bool = False):
    """Send Level 1 or Level 2 approval request email."""
    try:
        vendor  = invoice.get('vendor_name', 'Unknown')
        amount  = invoice.get('total_amount', 0)
        curr    = invoice.get('currency', 'AED')
        inv_num_raw = (invoice.get('invoice_number') or '').strip()
        inv_num     = inv_num_raw if inv_num_raw else '⚠️ Not mentioned — possible duplicate'
        date    = invoice.get('invoice_date', 'N/A')
        s3_key  = invoice.get('s3_key', '')
        items   = invoice.get('line_items', [])

        approve_link = f"{APPROVAL_API_URL}/action?invoice_id={invoice_id}&action=approve&level={level}"
        reject_link  = f"{APPROVAL_API_URL}/action?invoice_id={invoice_id}&action=reject&level={level}"

        level_label = 'Financial Manager' if level == 1 else 'Manager'
        level_badge = f'Approval Level {level} of 2'

        dup_banner = ''
        if is_duplicate:
            dup_banner = """<div style="background:#fff0f0;border:2px solid #cc0000;border-radius:8px;
padding:14px 18px;margin:16px 0">
<p style="margin:0;color:#cc0000;font-size:14px;font-weight:700">⚠️ WARNING: POSSIBLE DUPLICATE INVOICE</p>
<p style="margin:6px 0 0;color:#cc0000;font-size:12px">Please review carefully before approving.</p>
</div>"""

        # Build manual verification banner if vendor or amount is missing
        vendor_missing = not vendor or vendor in ['Unknown', 'Unknown Vendor', '']
        amount_missing = not amount or float(str(amount).replace(',','') or 0) <= 0
        verify_banner  = ''
        if vendor_missing or amount_missing:
            missing_fields = []
            if vendor_missing: missing_fields.append('Vendor Name')
            if amount_missing: missing_fields.append('Invoice Amount')
            missing_str = ' and '.join(missing_fields)
            verify_banner = f"""<div style="background:#fff8e1;border:2px solid #f59e0b;border-radius:8px;
padding:14px 18px;margin:16px 0">
<p style="margin:0;color:#b45309;font-size:14px;font-weight:700">⚠️ MANUAL VERIFICATION REQUIRED</p>
<p style="margin:6px 0 4px;color:#92400e;font-size:13px">
  The following could not be automatically extracted from this invoice:
  <strong>{missing_str}</strong>
</p>
<p style="margin:0;color:#92400e;font-size:12px">
  Please open the original invoice file in S3, verify the details manually,
  and only approve if the invoice is legitimate and complete.
</p>
</div>"""

        line_rows = ''
        if isinstance(items, list):
            for i, item in enumerate(items[:10]):
                bg = '#f9f9f9' if i % 2 == 0 else '#fff'
                line_rows += (
                    f'<tr style="background:{bg}">'
                    f'<td style="padding:7px 12px;font-size:12px">{item.get("description","?")}</td>'
                    f'<td style="padding:7px 12px;font-size:12px;text-align:center">{item.get("qty",1)}</td>'
                    f'<td style="padding:7px 12px;font-size:12px;text-align:right">{item.get("unit_price",0)}</td>'
                    f'<td style="padding:7px 12px;font-size:12px;text-align:right;font-weight:600">'
                    f'{item.get("total",0)} {curr}</td></tr>'
                )

        subject_prefix = '[DUPLICATE] ' if is_duplicate else ''
        subject = (f"{subject_prefix}[Al Islami Foods] Petty Cash {level_badge} "
                   f"— {vendor} — {amount} {curr}")

        html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:'Segoe UI',Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:30px 0">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0"
  style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1)">
  <tr>
    <td style="background:linear-gradient(135deg,#1a472a,#2d6a4f);padding:24px 32px;text-align:center">
      <h1 style="margin:0;color:#fff;font-size:20px;font-weight:700">🌿 Al Islami Foods</h1>
      <p style="margin:4px 0 0;color:#a8d5b5;font-size:13px">Petty Cash — Approval Request</p>
      <div style="margin-top:10px;background:rgba(255,255,255,0.2);border-radius:20px;
                  padding:5px 18px;display:inline-block">
        <span style="color:#fff;font-size:12px;font-weight:700">{level_badge} — {level_label}</span>
      </div>
    </td>
  </tr>
  <tr><td style="padding:24px 32px">
    {dup_banner}
    {verify_banner}
    <table width="100%" cellpadding="0" cellspacing="0"
           style="background:#f8f9fa;border-radius:8px;overflow:hidden;margin-bottom:20px">
      <tr style="background:#e9ecef">
        <td colspan="2" style="padding:10px 16px;font-weight:700;font-size:11px;
            color:#495057;text-transform:uppercase;letter-spacing:.5px">Invoice Details</td>
      </tr>
      <tr><td style="padding:8px 16px;color:#6c757d;font-size:13px;width:38%">Invoice ID</td>
          <td style="padding:8px 16px;font-weight:600;font-size:13px;font-family:monospace">{invoice_id}</td></tr>
      <tr style="background:#fff">
          <td style="padding:8px 16px;color:#6c757d;font-size:13px">Vendor</td>
          <td style="padding:8px 16px;font-weight:600;font-size:13px">{vendor}</td></tr>
      <tr><td style="padding:8px 16px;color:#6c757d;font-size:13px">Invoice No</td>
          <td style="padding:8px 16px;font-weight:600;font-size:13px">{inv_num}</td></tr>
      <tr style="background:#fff">
          <td style="padding:8px 16px;color:#6c757d;font-size:13px">Date</td>
          <td style="padding:8px 16px;font-weight:600;font-size:13px">{date}</td></tr>
      <tr style="background:#e8f5e9">
          <td style="padding:10px 16px;color:#2d6a4f;font-size:13px;font-weight:700">Amount</td>
          <td style="padding:10px 16px;font-weight:800;font-size:16px;color:#1a472a">{amount} {curr}</td></tr>
    </table>
    {'<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #dee2e6;border-radius:8px;overflow:hidden;margin-bottom:20px"><tr style="background:#343a40"><th style="padding:8px 12px;color:#fff;font-size:11px;text-align:left">Description</th><th style="padding:8px 12px;color:#fff;font-size:11px;text-align:center">Qty</th><th style="padding:8px 12px;color:#fff;font-size:11px;text-align:right">Price</th><th style="padding:8px 12px;color:#fff;font-size:11px;text-align:right">Total</th></tr>' + line_rows + '</table>' if line_rows else ''}
    <div style="text-align:center;padding:20px;background:#f8f9fa;border-radius:8px">
      <p style="margin:0 0 14px;font-size:14px;font-weight:600;color:#495057">
        Action Required — <strong>{level_label}</strong> ({level_badge})
      </p>
      <a href="{approve_link}"
         style="display:inline-block;background:#28a745;color:#fff;text-decoration:none;
                padding:13px 32px;border-radius:6px;font-size:14px;font-weight:700;margin:0 6px">
        ✅ APPROVE
      </a>
      <a href="{reject_link}"
         style="display:inline-block;background:#dc3545;color:#fff;text-decoration:none;
                padding:13px 32px;border-radius:6px;font-size:14px;font-weight:700;margin:0 6px">
        ❌ REJECT
      </a>
    </div>
    {'<p style="margin-top:12px;font-size:11px;color:#adb5bd">📎 s3://' + os.getenv("S3_BUCKET_NAME","") + "/" + s3_key + "</p>" if s3_key else ""}
  </td></tr>
  <tr>
    <td style="background:#f8f9fa;padding:12px 32px;text-align:center;border-top:1px solid #dee2e6">
      <p style="margin:0;font-size:11px;color:#adb5bd">
        Al Islami Foods Petty Cash AI &nbsp;|&nbsp; AgentCore · Textract · Claude
      </p>
    </td>
  </tr>
</table>
</td></tr>
</table>
</body></html>"""

        plain = f"""
Al Islami Foods — Petty Cash {level_badge}
You are: {level_label}
{'*** DUPLICATE INVOICE WARNING ***' if is_duplicate else ''}
{'*** MANUAL VERIFICATION REQUIRED: ' + missing_str + ' could not be extracted — please check the original invoice ***' if verify_banner else ''}
============================================
Vendor     : {vendor}
Invoice No : {inv_num_raw if inv_num_raw else '⚠️ Not found — please check manually'}
Date       : {date}
Amount     : {amount} {curr}
ID         : {invoice_id}

APPROVE: {approve_link}
REJECT : {reject_link}
        """

        ses = get_aws_session().client('ses')
        ses.send_email(
            Source=MANAGER1_EMAIL,
            Destination={'ToAddresses': [to_email]},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {
                    'Html': {'Data': html,  'Charset': 'UTF-8'},
                    'Text': {'Data': plain, 'Charset': 'UTF-8'}
                }
            }
        )
        print(f"[EMAIL] Level {level} request sent to: {to_email}")

    except Exception as e:
        print(f"[EMAIL ERROR] Level {level} to {to_email}: {e}")
        try:
            sns = get_aws_session().client('sns')
            sns.publish(
                TopicArn=os.getenv('SNS_TOPIC_ARN'),
                Subject=f"[Al Islami Foods] Approval L{level} — {invoice.get('vendor_name')}",
                Message=f"APPROVE: {APPROVAL_API_URL}/action?invoice_id={invoice_id}&action=approve&level={level}\nREJECT: {APPROVAL_API_URL}/action?invoice_id={invoice_id}&action=reject&level={level}"
            )
        except Exception as e2:
            print(f"[SNS ERROR] {e2}")

def send_submitter_notification(submitter_email: str, invoice: dict,
                                status: str, invoice_id: str):
    """Notify the submitter of the final decision."""
    if not submitter_email:
        return
    submitter_email = submitter_email.strip()
    if not ensure_ses_verified(submitter_email):
        return
    try:
        ses     = get_aws_session().client('ses')
        vendor  = invoice.get('vendor_name', 'Unknown')
        amount  = invoice.get('total_amount', 0)
        curr    = invoice.get('currency', 'AED')
        inv_num_raw = (invoice.get('invoice_number') or '').strip()
        if inv_num_raw.lower() in ['unknown', 'n/a', 'none', '-', '--', '']:
            inv_num_raw = ''
        inv_num = inv_num_raw if inv_num_raw else '⚠️ Not found — please check manually'
        date        = invoice.get('invoice_date', 'N/A')
        cat         = invoice.get('category', 'Other')

        is_approved = 'APPROVED' in status
        color   = '#28a745' if is_approved else '#dc3545'
        icon    = '✅' if is_approved else '❌'
        label   = 'FULLY APPROVED' if is_approved else 'REJECTED'
        subject = f"{icon} Invoice {label} — {vendor} — {amount} {curr}"

        html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:'Segoe UI',Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:30px 0">
<tr><td align="center">
<table width="540" cellpadding="0" cellspacing="0"
  style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1)">
  <tr>
    <td style="background:linear-gradient(135deg,#1a472a,#2d6a4f);padding:24px 32px;text-align:center">
      <h1 style="margin:0;color:#fff;font-size:20px;font-weight:700">🌿 Al Islami Foods</h1>
      <p style="margin:4px 0 0;color:#a8d5b5;font-size:12px">Petty Cash — Invoice Decision</p>
    </td>
  </tr>
  <tr>
    <td style="padding:28px 32px;text-align:center">
      <div style="width:72px;height:72px;border-radius:50%;background:{'#e8f5e9' if is_approved else '#fde8e8'};
                  margin:0 auto 14px;display:flex;align-items:center;justify-content:center;
                  font-size:38px;line-height:72px">{icon}</div>
      <h2 style="color:{color};font-size:22px;margin:0 0 6px;font-weight:800">
        Invoice {'Fully Approved!' if is_approved else 'Rejected'}
      </h2>
      <p style="color:#6c757d;font-size:14px;margin:0 0 20px">
        {'Both managers have approved your submission.' if is_approved else 'Your submission has been reviewed and rejected.'}
      </p>

      <div style="background:#{'f0fff4' if is_approved else 'fff5f5'};border:2px solid {color};
                  border-radius:10px;padding:16px 20px;margin-bottom:20px;text-align:center">
        <div style="font-size:13px;color:#495057;margin-bottom:4px">Decision</div>
        <div style="font-size:20px;font-weight:800;color:{color}">{label}</div>
      </div>

      <table width="100%" cellpadding="0" cellspacing="0"
             style="background:#f8f9fa;border-radius:8px;overflow:hidden;text-align:left;margin-bottom:16px">
        <tr style="background:#e9ecef">
          <td colspan="2" style="padding:10px 16px;font-weight:700;font-size:11px;
              color:#495057;text-transform:uppercase;letter-spacing:.5px">Invoice Details</td>
        </tr>
        <tr><td style="padding:8px 16px;color:#6c757d;font-size:13px;width:40%">Vendor</td>
            <td style="padding:8px 16px;font-weight:600;font-size:13px">{vendor}</td></tr>
        <tr style="background:#fff">
            <td style="padding:8px 16px;color:#6c757d;font-size:13px">Invoice No</td>
            <td style="padding:8px 16px;font-weight:600;font-size:13px">{inv_num}</td></tr>
        <tr><td style="padding:8px 16px;color:#6c757d;font-size:13px">Date</td>
            <td style="padding:8px 16px;font-weight:600;font-size:13px">{date}</td></tr>
        <tr style="background:#fff">
            <td style="padding:8px 16px;color:#6c757d;font-size:13px">Category</td>
            <td style="padding:8px 16px;font-weight:600;font-size:13px">{cat}</td></tr>
        <tr style="background:#{'e8f5e9' if is_approved else 'fff5f5'}">
            <td style="padding:10px 16px;color:#{'2d6a4f' if is_approved else 'dc3545'};font-size:13px;font-weight:700">Amount</td>
            <td style="padding:10px 16px;font-weight:800;font-size:16px;color:{color}">{amount} {curr}</td></tr>
      </table>

      <p style="font-size:11px;color:#adb5bd;margin:0">
        Invoice ID: <span style="font-family:monospace">{invoice_id}</span>
      </p>
    </td>
  </tr>
  <tr>
    <td style="background:#f8f9fa;padding:12px 32px;text-align:center;border-top:1px solid #dee2e6">
      <p style="margin:0;font-size:11px;color:#adb5bd">
        Al Islami Foods Petty Cash AI &nbsp;|&nbsp; AgentCore · Textract · Claude
      </p>
    </td>
  </tr>
</table>
</td></tr>
</table>
</body></html>"""

        plain = f"""Al Islami Foods — Invoice {label}
Vendor: {vendor} | Invoice No: {inv_num} | Amount: {amount} {curr}
Category: {cat} | ID: {invoice_id}
{'Both managers have approved your submission.' if is_approved else 'Your submission has been rejected.'}"""

        ses.send_email(
            Source=MANAGER1_EMAIL,
            Destination={'ToAddresses': [submitter_email]},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {
                    'Html': {'Data': html,  'Charset': 'UTF-8'},
                    'Text': {'Data': plain, 'Charset': 'UTF-8'}
                }
            }
        )
        print(f"[NOTIFY] Submitter notified: {submitter_email} -> {label}")
    except Exception as e:
        print(f"[NOTIFY ERROR] {e}")

def send_rejection_notification(submitter_email: str, invoice: dict,
                               invoice_id: str, reason: str, notes: str):
    """Send detailed rejection email to the submitter with reason."""
    if not submitter_email:
        return
    submitter_email = submitter_email.strip()
    if not ensure_ses_verified(submitter_email):
        return
    try:
        ses    = get_aws_session().client('ses')
        vendor = invoice.get('vendor_name', 'Unknown')
        amount = invoice.get('total_amount', 0)
        curr   = invoice.get('currency', 'AED')
        inv_num_raw = (invoice.get('invoice_number') or '').strip()
        if inv_num_raw.lower() in ['unknown', 'n/a', 'none', '-', '--', '']:
            inv_num_raw = ''
        inv_num = inv_num_raw if inv_num_raw else '⚠️ Not found — please check manually'
        date        = invoice.get('invoice_date', 'N/A')

        reason_labels = {
            'duplicate'      : 'Duplicate Invoice',
            'missing_info'   : 'Missing Information',
            'over_budget'    : 'Over Budget / Exceeds Limit',
            'not_approved'   : 'Vendor / Purchase Not Pre-Approved',
            'wrong_category' : 'Wrong Category',
            'policy'         : 'Violates Company Policy',
            'other'          : 'Other Reason',
        }
        reason_label = reason_labels.get(reason, reason)
        subject = f"❌ Invoice Rejected — {vendor} — {amount} {curr}"

        html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:'Segoe UI',Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:30px 0">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0"
  style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1)">
  <tr>
    <td style="background:linear-gradient(135deg,#1a472a,#2d6a4f);padding:24px 32px;text-align:center">
      <h1 style="margin:0;color:#fff;font-size:20px;font-weight:700">🌿 Al Islami Foods</h1>
      <p style="margin:4px 0 0;color:#a8d5b5;font-size:13px">Petty Cash — Invoice Decision</p>
    </td>
  </tr>
  <tr><td style="padding:28px 32px;text-align:center">
    <div style="font-size:52px;margin-bottom:8px">❌</div>
    <h2 style="color:#dc3545;font-size:22px;margin:0 0 6px">Your Invoice has been Rejected</h2>
    <p style="color:#6c757d;font-size:14px;margin:0 0 20px">
      The finance manager has reviewed and rejected your submission.
    </p>
    <table width="100%" cellpadding="0" cellspacing="0"
           style="background:#f8f9fa;border-radius:8px;overflow:hidden;margin-bottom:16px;text-align:left">
      <tr style="background:#e9ecef">
        <td colspan="2" style="padding:10px 16px;font-weight:700;font-size:11px;
            color:#495057;text-transform:uppercase;letter-spacing:.5px">Invoice Details</td>
      </tr>
      <tr><td style="padding:8px 16px;color:#6c757d;font-size:13px;width:38%">Vendor</td>
          <td style="padding:8px 16px;font-weight:600;font-size:13px">{vendor}</td></tr>
      <tr style="background:#fff">
          <td style="padding:8px 16px;color:#6c757d;font-size:13px">Invoice No</td>
          <td style="padding:8px 16px;font-weight:600;font-size:13px">{inv_num}</td></tr>
      <tr><td style="padding:8px 16px;color:#6c757d;font-size:13px">Date</td>
          <td style="padding:8px 16px;font-weight:600;font-size:13px">{date}</td></tr>
      <tr style="background:#fff">
          <td style="padding:8px 16px;color:#6c757d;font-size:13px">Amount</td>
          <td style="padding:8px 16px;font-weight:700;font-size:14px;color:#dc3545">{amount} {curr}</td></tr>
    </table>
    <div style="background:#fff5f5;border:2px solid #dc3545;border-radius:8px;padding:16px 20px;text-align:left;margin-bottom:16px">
      <p style="margin:0 0 6px;font-weight:700;font-size:13px;color:#dc3545">Rejection Reason:</p>
      <p style="margin:0 0 10px;font-size:14px;color:#212529;font-weight:600">{reason_label}</p>
      {'<p style="margin:0;font-size:13px;color:#495057;line-height:1.6"><strong>Additional Notes:</strong><br>' + notes + '</p>' if notes else ''}
    </div>
    <p style="font-size:12px;color:#6c757d;margin:0">
      Please review the above reason and resubmit a corrected invoice if applicable.
    </p>
    <p style="font-size:11px;color:#adb5bd;margin-top:14px">
      Invoice ID: <span style="font-family:monospace">{invoice_id}</span>
    </p>
  </td></tr>
  <tr>
    <td style="background:#f8f9fa;padding:12px 32px;text-align:center;border-top:1px solid #dee2e6">
      <p style="margin:0;font-size:11px;color:#adb5bd">
        Al Islami Foods Petty Cash AI &nbsp;|&nbsp; AgentCore · Textract · Claude
      </p>
    </td>
  </tr>
</table>
</td></tr>
</table>
</body></html>"""

        plain = f"""
Al Islami Foods — Invoice Rejected
====================================
Vendor     : {vendor}
Invoice No : {inv_num}
Date       : {date}
Amount     : {amount} {curr}
ID         : {invoice_id}

Rejection Reason: {reason_label}
{('Notes: ' + notes) if notes else ''}

Please review and resubmit a corrected invoice if applicable.
Al Islami Foods Petty Cash AI
        """

        ses.send_email(
            Source=MANAGER1_EMAIL,
            Destination={'ToAddresses': [submitter_email]},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {
                    'Html': {'Data': html,  'Charset': 'UTF-8'},
                    'Text': {'Data': plain, 'Charset': 'UTF-8'}
                }
            }
        )
        print(f"[REJECT NOTIFY] ✓ Sent to {submitter_email} — reason: {reason}")
    except Exception as e:
        print(f"[REJECT NOTIFY ERROR] {e}")


def parse_multipart(body: bytes, content_type: str):
    result = {'file_data': None, 'filename': 'invoice.pdf', 'submitter_email': ''}
    if 'boundary=' not in content_type:
        return result
    boundary = content_type.split('boundary=')[-1].strip().encode()
    parts    = body.split(b'--' + boundary)
    for part in parts:
        if b'Content-Disposition' not in part or b'\r\n\r\n' not in part:
            continue
        header_bytes, content = part.split(b'\r\n\r\n', 1)
        content    = content.rstrip(b'\r\n--')
        header_str = header_bytes.decode('utf-8', errors='ignore')
        field_name = ''
        filename   = ''
        for line in header_str.split('\r\n'):
            if 'Content-Disposition' not in line:
                continue
            for seg in line.split(';'):
                seg = seg.strip()
                if seg.startswith('name='):
                    field_name = seg.split('=', 1)[1].strip().strip('"')
                elif seg.startswith('filename='):
                    filename = seg.split('=', 1)[1].strip().strip('"')
        if field_name == 'submitter_email':
            result['submitter_email'] = content.decode('utf-8', errors='ignore').strip()
        elif field_name == 'file' and filename:
            safe  = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_')
            clean = ''.join(c if c in safe else '_' for c in filename.split('\n')[0].strip())
            result['filename']  = clean or 'invoice.pdf'
            result['file_data'] = content
    return result


class Handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        path   = parsed.path

        # ── Health / Root ──────────────────────────────────────────────────
        if path in ['/', '', '/health']:
            self._json(200, {
                'status'   : 'online',
                'service'  : 'Al Islami Foods Petty Cash AI',
                'version'  : '2.0',
                'approval' : 'Two-level: Financial Manager + Manager',
                'manager1' : MANAGER1_EMAIL,
                'manager2' : MANAGER2_EMAIL or 'not configured',
            })

        # ── Approve / Reject ───────────────────────────────────────────────
        elif path == '/action':
            invoice_id = params.get('invoice_id', [None])[0]
            action     = params.get('action',     [None])[0]
            level      = int(params.get('level',  ['1'])[0])

            if not invoice_id or action not in ['approve', 'reject']:
                return self._respond(400, 'Invalid request')

            invoice = get_invoice(invoice_id)
            if not invoice:
                return self._respond(404, f'Invoice {invoice_id} not found')

            # Check if already actioned at this level
            level_field = f'approval_{level}_status'
            current     = invoice.get(level_field, 'PENDING')
            if current in ['APPROVED', 'REJECTED']:
                return self._html_page(invoice_id, current, invoice,
                                       already_done=True, level=level)

            if action == 'reject':
                # Show rejection reason form — status updated after form submission
                return self._rejection_form(invoice_id, invoice, level)

            new_status = 'APPROVED'
            update_approval_status(invoice_id, level, new_status)
            invoice[level_field] = new_status
            print(f"[ACTION] {invoice_id} Level {level} -> {new_status}")

            if action == 'approve' and level == 1:
                if MANAGER2_EMAIL:
                    # Send to Manager 2
                    update_invoice_status(invoice_id, 'AWAITING_MANAGER2')
                    invoice['status'] = 'AWAITING_MANAGER2'
                    is_dup = 'duplicate' in invoice.get('status', '').lower()
                    threading.Thread(
                        target=send_approval_request_email,
                        args=(invoice, invoice_id, 2, MANAGER2_EMAIL, is_dup),
                        daemon=True
                    ).start()
                    return self._html_page(invoice_id, 'APPROVED_L1', invoice, level=1)
                else:
                    # No Manager 2 — fully approved
                    update_final_status(invoice_id, 'FULLY_APPROVED')
                    submitter = invoice.get('submitter_email', '')
                    if submitter:
                        threading.Thread(
                            target=send_submitter_notification,
                            args=(submitter, invoice, 'FULLY_APPROVED', invoice_id),
                            daemon=True
                        ).start()
                    return self._html_page(invoice_id, 'FULLY_APPROVED', invoice, level=1)

            if action == 'approve' and level == 2:
                # Both levels approved
                update_final_status(invoice_id, 'FULLY_APPROVED')
                invoice['final_status'] = 'FULLY_APPROVED'
                submitter = invoice.get('submitter_email', '')
                if submitter:
                    threading.Thread(
                        target=send_submitter_notification,
                        args=(submitter, invoice, 'FULLY_APPROVED', invoice_id),
                        daemon=True
                    ).start()
                return self._html_page(invoice_id, 'FULLY_APPROVED', invoice, level=2)

        # ── Records ────────────────────────────────────────────────────────
        elif path == '/reverse':
            # Reset invoice back to PENDING and resend approval email
            invoice_id = params.get('invoice_id', [None])[0]
            if not invoice_id:
                return self._respond(400, 'Missing invoice_id')
            invoice = get_invoice(invoice_id)
            if not invoice:
                return self._respond(404, f'Invoice {invoice_id} not found')
            try:
                from datetime import datetime
                table = get_aws_session().resource('dynamodb').Table(
                    os.getenv('DYNAMODB_TABLE', 'al-islami-petty-cash')
                )
                table.update_item(
                    Key={'invoice_id': invoice_id},
                    UpdateExpression=(
                        'SET #st = :p, final_status = :p, '
                        'approval_1_status = :p, approval_2_status = :w, '
                        'rejection_reason = :e, rejection_notes = :e, '
                        'updated_at = :ts'
                    ),
                    ExpressionAttributeNames={'#st': 'status'},
                    ExpressionAttributeValues={
                        ':p' : 'PENDING',
                        ':w' : 'WAITING',
                        ':e' : '',
                        ':ts': datetime.utcnow().isoformat()
                    }
                )
                invoice['status']            = 'PENDING'
                invoice['approval_1_status'] = 'PENDING'
                invoice['approval_2_status'] = 'WAITING'
                print(f"[REVERSE] {invoice_id} reset to PENDING")
                # Resend Level 1 approval email
                threading.Thread(
                    target=send_approval_request_email,
                    args=(invoice, invoice_id, 1, MANAGER1_EMAIL, False),
                    daemon=True
                ).start()
                self._json(200, {'status': 'reversed', 'invoice_id': invoice_id})
            except Exception as e:
                print(f"[REVERSE ERROR] {e}")
                self._respond(500, str(e))

        elif path == '/records':
            try:
                self._json(200, get_all_records())
            except Exception as e:
                self._respond(500, str(e))

        # ── Status polling ─────────────────────────────────────────────────
        elif path.startswith('/status/'):
            tid    = path.split('/')[-1]
            status = pipeline_status.get(tid, {'pipeline_status': 'processing', 'current_step': 1})
            self._json(200, status)

        elif path == '/reject-submit':
            # Handle rejection reason form submission via GET with params
            invoice_id     = params.get('invoice_id', [None])[0]
            level          = int(params.get('level', ['1'])[0])
            reason         = params.get('reason', ['other'])[0]
            notes          = params.get('notes', [''])[0]

            if not invoice_id:
                return self._respond(400, 'Missing invoice_id')

            invoice = get_invoice(invoice_id)
            if not invoice:
                return self._respond(404, f'Invoice {invoice_id} not found')

            level_field = f'approval_{level}_status'
            if invoice.get(level_field) in ['APPROVED', 'REJECTED']:
                return self._html_page(invoice_id, 'REJECTED', invoice,
                                       already_done=True, level=level)

            # Update approval level and final status
            update_approval_status(invoice_id, level, 'REJECTED')
            update_final_status(invoice_id, 'REJECTED')

            # Save rejection reason to DynamoDB
            try:
                table = get_aws_session().resource('dynamodb').Table(
                    os.getenv('DYNAMODB_TABLE', 'al-islami-petty-cash')
                )
                from datetime import datetime
                table.update_item(
                    Key={'invoice_id': invoice_id},
                    UpdateExpression='SET rejection_reason = :rr, rejection_notes = :rn, updated_at = :ts',
                    ExpressionAttributeValues={
                        ':rr': reason,
                        ':rn': notes,
                        ':ts': datetime.utcnow().isoformat()
                    }
                )
                print(f"[REJECT] {invoice_id} reason={reason} notes={notes[:50]}")
            except Exception as e:
                print(f"[REJECT] DynamoDB update error: {e}")

            invoice['rejection_reason'] = reason
            invoice['rejection_notes']  = notes

            # Send rejection email to submitter
            submitter = invoice.get('submitter_email', '')
            if submitter:
                threading.Thread(
                    target=send_rejection_notification,
                    args=(submitter, invoice, invoice_id, reason, notes),
                    daemon=True
                ).start()

            return self._html_page(invoice_id, 'REJECTED', invoice, level=level)

        else:
            self._respond(404, 'Not found')

    def do_POST(self):
        if self.path != '/upload':
            return self._respond(404, 'Not found')
        try:
            content_type = self.headers.get('Content-Type', '')
            length       = int(self.headers.get('Content-Length', 0))
            body         = self.rfile.read(length)
            parsed          = parse_multipart(body, content_type)
            file_data       = parsed['file_data']
            filename        = parsed['filename']
            submitter_email = parsed['submitter_email']

            if file_data is None:
                return self._respond(400, 'No file found in request')

            print(f"[UPLOAD] {filename} ({len(file_data)} bytes) | submitter={submitter_email or 'none'}")

            suffix = os.path.splitext(filename)[1] or '.pdf'
            tmp    = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            tmp.write(file_data)
            tmp.close()
            s3_key = f"uploads/{filename}"
            get_aws_session().client('s3').upload_file(
                tmp.name, os.getenv('S3_BUCKET_NAME'), s3_key
            )
            os.unlink(tmp.name)
            print(f"[UPLOAD] -> s3://{os.getenv('S3_BUCKET_NAME')}/{s3_key}")

            if submitter_email:
                threading.Thread(target=ensure_ses_verified, args=(submitter_email,), daemon=True).start()

            tracking_id = str(uuid.uuid4())[:8].upper()
            pipeline_status[tracking_id] = {'pipeline_status': 'processing', 'current_step': 1}

            def run_agent(tid, key, sub_email):
                try:
                    pipeline_status[tid]['current_step'] = 2
                    result = run_petty_cash_agent(
                        os.getenv('S3_BUCKET_NAME'), key,
                        submitter_email=sub_email
                    )
                    pipeline_status[tid] = {
                        'pipeline_status': result.get('status', 'done'),
                        'current_step'   : 6,
                        'invoice_id'     : result.get('invoice_id', ''),
                        'invoice'        : result.get('invoice', {}),
                        'dup_reason'     : result.get('dup_reason', ''),
                        'errors'         : result.get('errors', []),
                    }
                    print(f"[PIPELINE] {tid} -> {result.get('status')}")
                except Exception as e:
                    pipeline_status[tid] = {
                        'pipeline_status': 'error', 'current_step': 1, 'error': str(e)
                    }
                    import traceback; traceback.print_exc()

            threading.Thread(target=run_agent, args=(tracking_id, s3_key, submitter_email), daemon=True).start()
            self._json(200, {'tracking_id': tracking_id, 'invoice_id': tracking_id, 's3_key': s3_key})

        except Exception as e:
            import traceback; traceback.print_exc()
            self._respond(500, str(e))

    # ── Helpers ────────────────────────────────────────────────────────────
    def _cors(self):
        self.send_header('Access-Control-Allow-Origin',  '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,PUT,DELETE,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type,Accept,Authorization,X-Requested-With')
        self.send_header('Access-Control-Allow-Credentials', 'false')
        self.send_header('Access-Control-Max-Age', '86400')

    def _respond(self, code, msg):
        try:
            self.send_response(code); self._cors()
            self.send_header('Content-Type', 'text/plain')
            self.end_headers(); self.wfile.write(msg.encode())
        except Exception: pass

    def _json(self, code, data):
        try:
            payload = json.dumps(data, default=str).encode()
            self.send_response(code); self._cors()
            self.send_header('Content-Type',   'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers(); self.wfile.write(payload)
        except Exception: pass

    def _rejection_form(self, invoice_id, invoice, level):
        """Show a rejection reason form to the manager."""
        vendor  = invoice.get('vendor_name', 'Unknown')
        amount  = invoice.get('total_amount', 0)
        curr    = invoice.get('currency', 'AED')
        inv_num_raw2 = (invoice.get('invoice_number') or '').strip()
        if inv_num_raw2.lower() in ['unknown', 'n/a', 'none', '-', '--', '']:
            inv_num_raw2 = ''
        inv_num = inv_num_raw2 if inv_num_raw2 else '⚠️ Not found'
        api_url = APPROVAL_API_URL

        html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reject Invoice — Al Islami Foods</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',Arial,sans-serif;background:#f4f4f4;
  display:flex;align-items:center;justify-content:center;min-height:100vh;padding:20px}}
.card{{background:#fff;border-radius:16px;max-width:500px;width:100%;
  box-shadow:0 4px 24px rgba(0,0,0,.1);overflow:hidden}}
.header{{background:linear-gradient(135deg,#1a472a,#2d6a4f);padding:20px 28px;text-align:center}}
.header h1{{color:#fff;font-size:18px;font-weight:700;margin:0}}
.header p{{color:#a8d5b5;font-size:12px;margin:4px 0 0}}
.body{{padding:24px 28px}}
.inv-info{{background:#f8f9fa;border-radius:8px;padding:12px 16px;margin-bottom:20px;font-size:13px}}
.inv-info strong{{color:#1a472a}}
.inv-row{{display:flex;justify-content:space-between;padding:3px 0;color:#495057}}
.section-title{{font-size:13px;font-weight:700;color:#212529;margin-bottom:10px}}
.reason-grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:16px}}
.reason-btn{{padding:10px 12px;border:2px solid #dee2e6;border-radius:8px;
  background:#fff;cursor:pointer;font-size:12px;font-weight:600;color:#495057;
  text-align:center;transition:all .15s}}
.reason-btn:hover,.reason-btn.selected{{border-color:#dc3545;background:#fff5f5;color:#dc3545}}
.notes-label{{font-size:13px;font-weight:600;color:#212529;margin-bottom:6px;display:block}}
textarea{{width:100%;padding:10px 12px;border:1.5px solid #dee2e6;border-radius:8px;
  font-size:13px;font-family:inherit;resize:vertical;min-height:80px;outline:none}}
textarea:focus{{border-color:#dc3545}}
.actions{{display:flex;gap:10px;margin-top:20px}}
.btn-reject{{flex:1;padding:12px;background:#dc3545;color:#fff;border:none;
  border-radius:8px;font-size:14px;font-weight:700;cursor:pointer}}
.btn-reject:hover{{background:#c0392b}}
.btn-cancel{{padding:12px 20px;background:#f8f9fa;color:#6c757d;border:1px solid #dee2e6;
  border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;text-decoration:none;display:flex;align-items:center}}
.btn-cancel:hover{{background:#e9ecef}}
.err{{color:#dc3545;font-size:12px;margin-top:6px;display:none}}
</style></head>
<body>
<div class="card">
  <div class="header">
    <h1>🌿 Al Islami Foods</h1>
    <p>Petty Cash — Rejection Reason</p>
  </div>
  <div class="body">
    <div class="inv-info">
      <div class="inv-row"><span>Vendor</span><strong>{vendor}</strong></div>
      <div class="inv-row"><span>Invoice No</span><strong>{inv_num}</strong></div>
      <div class="inv-row"><span>Amount</span><strong style="color:#dc3545">{amount} {curr}</strong></div>
    </div>

    <div class="section-title">Select rejection reason:</div>
    <div class="reason-grid" id="reason-grid">
      <div class="reason-btn" onclick="selectReason('duplicate')">🔁 Duplicate Invoice</div>
      <div class="reason-btn" onclick="selectReason('missing_info')">📋 Missing Information</div>
      <div class="reason-btn" onclick="selectReason('over_budget')">💰 Over Budget</div>
      <div class="reason-btn" onclick="selectReason('not_approved')">🚫 Not Pre-Approved</div>
      <div class="reason-btn" onclick="selectReason('wrong_category')">🏷️ Wrong Category</div>
      <div class="reason-btn" onclick="selectReason('policy')">📜 Policy Violation</div>
      <div class="reason-btn" onclick="selectReason('other')" style="grid-column:span 2">✍️ Other Reason</div>
    </div>

    <label class="notes-label">Additional notes (optional):</label>
    <textarea id="notes" placeholder="Provide more details about the rejection..."></textarea>
    <div class="err" id="err-msg">Please select a rejection reason.</div>

    <div class="actions">
      <a class="btn-cancel" href="{api_url}/action?invoice_id={invoice_id}&action=approve&level={level}"
         onclick="return confirm('Go back to approve instead?')">← Back</a>
      <button class="btn-reject" onclick="submitRejection()">❌ Confirm Rejection</button>
    </div>
  </div>
</div>
<script>
let selectedReason = '';
function selectReason(r) {{
  selectedReason = r;
  document.querySelectorAll('.reason-btn').forEach(b => b.classList.remove('selected'));
  event.target.classList.add('selected');
  document.getElementById('err-msg').style.display = 'none';
}}
function submitRejection() {{
  if (!selectedReason) {{
    document.getElementById('err-msg').style.display = 'block';
    return;
  }}
  const notes   = encodeURIComponent(document.getElementById('notes').value.trim());
  const reason  = encodeURIComponent(selectedReason);
  window.location.href = '{api_url}/reject-submit?invoice_id={invoice_id}&level={level}&reason=' + reason + '&notes=' + notes;
}}
</script>
</body></html>"""

        try:
            payload = html.encode('utf-8')
            self.send_response(200); self._cors()
            self.send_header('Content-Type',   'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers(); self.wfile.write(payload)
        except Exception: pass

    def _html_page(self, invoice_id, status, invoice, already_done=False, level=1):
        cfg = {
            'APPROVED'       : ('#28a745', '&#10003;', 'Approved by you'),
            'APPROVED_L1'    : ('#17a2b8', '&#10003;', 'Level 1 Approved'),
            'FULLY_APPROVED' : ('#28a745', '&#10003;', 'Fully Approved'),
            'REJECTED'       : ('#dc3545', '&#10007;', 'Rejected'),
        }
        color, icon, label = cfg.get(status, ('#6c757d', '?', status))
        msg    = 'already been' if already_done else 'been'
        vendor = invoice.get('vendor_name', 'Unknown')
        amount = invoice.get('total_amount', 0)
        curr   = invoice.get('currency', 'AED')
        sub    = invoice.get('submitter_email', '').strip()

        extra = ''
        if status == 'APPROVED_L1':
            extra = f'<p style="color:#17a2b8;font-size:13px;margin-top:12px">📧 Approval request forwarded to Manager (Level 2)</p>'
        if status == 'FULLY_APPROVED' and sub:
            extra = f'<p style="color:#28a745;font-size:13px;margin-top:12px">📧 Submitter notified: {sub}</p>'
        if status == 'REJECTED' and sub:
            extra = f'<p style="color:#dc3545;font-size:13px;margin-top:12px">📧 Submitter notified: {sub}</p>'

        html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>
body{{font-family:'Segoe UI',Arial,sans-serif;background:#f4f4f4;
  display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
.card{{background:#fff;border-radius:16px;padding:36px 44px;text-align:center;
  max-width:440px;width:92%;box-shadow:0 4px 24px rgba(0,0,0,.1)}}
.level{{background:#e9ecef;color:#495057;font-size:11px;font-weight:700;
  padding:3px 12px;border-radius:10px;display:inline-block;margin-bottom:12px}}
.icon{{font-size:52px;color:{color};margin-bottom:8px}}
h2{{color:#212529;margin:8px 0;font-size:20px}}
.badge{{background:{color};color:#fff;padding:9px 26px;border-radius:24px;
  font-size:14px;font-weight:700;display:inline-block;margin:12px 0}}
.detail{{color:#6c757d;font-size:14px;line-height:1.8}}
.id{{font-family:monospace;font-size:11px;color:#aaa;margin-top:14px}}
.brand{{color:#2d6a4f;font-size:11px;margin-top:16px;font-weight:600}}
</style></head>
<body><div class="card">
  <div class="level">Level {level} of 2</div>
  <div class="icon">{icon}</div>
  <h2>Invoice has {msg} {label}</h2>
  <div class="badge">{label.upper()}</div>
  <div class="detail"><strong>{vendor}</strong><br>{amount} {curr}</div>
  {extra}
  <div class="id">Invoice ID: {invoice_id}</div>
  <div class="brand">Al Islami Foods — Petty Cash AI</div>
</div></body></html>"""

        try:
            payload = html.encode('utf-8')
            self.send_response(200); self._cors()
            self.send_header('Content-Type',   'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers(); self.wfile.write(payload)
        except Exception: pass

    def log_message(self, *args): pass


if __name__ == '__main__':
    port   = int(os.getenv('PORT', 8000))
    server = HTTPServer(('0.0.0.0', port), Handler)
    print(f"\nAl Islami Foods — Approval Server v2.0")
    print(f"{'='*48}")
    print(f"Running on  : http://0.0.0.0:{port}")
    print(f"Region      : {os.getenv('AWS_DEFAULT_REGION', 'eu-central-1')}")
    print(f"Manager 1   : {MANAGER1_EMAIL} (Financial Manager)")
    print(f"Manager 2   : {MANAGER2_EMAIL or 'NOT SET'} (Manager)")
    print(f"{'='*48}")
    print(f"\nTwo-level approval flow:")
    print(f"  1. Invoice uploaded -> Financial Manager email sent")
    print(f"  2. FM approves -> Manager email sent")
    print(f"  3. Manager approves -> FULLY APPROVED -> submitter notified")
    print(f"  Either rejects -> REJECTED -> submitter notified")
    print(f"\nPress Ctrl+C to stop\n")
    server.serve_forever()