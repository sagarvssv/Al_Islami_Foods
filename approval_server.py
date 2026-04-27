from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import os, json, threading, tempfile, uuid, boto3
from dotenv import load_dotenv
load_dotenv(override=True)

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent.tools.dynamodb_tool import update_invoice_status, get_invoice

pipeline_status = {}

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
    """Check if email is verified in SES. If not, send verification."""
    try:
        ses   = get_aws_session().client('ses')
        attrs = ses.get_identity_verification_attributes(Identities=[email])
        status = attrs['VerificationAttributes'].get(email, {}).get('VerificationStatus', '')
        if status == 'Success':
            return True
        # Not verified — send verification email
        ses.verify_email_identity(EmailAddress=email)
        print(f"[SES] Verification email sent to {email} — they must click the link first")
        return False
    except Exception as e:
        print(f"[SES] Could not check/verify {email}: {e}")
        return False

def send_submitter_notification(submitter_email: str, invoice: dict, status: str, invoice_id: str):
    """Send approve/reject result email to the invoice submitter."""
    if not submitter_email or not submitter_email.strip():
        print(f"[NOTIFY] No submitter email — skipping notification")
        return

    submitter_email = submitter_email.strip()
    print(f"[NOTIFY] Sending {status} notification to: {submitter_email}")

    # Ensure submitter email is verified in SES sandbox
    if not ensure_ses_verified(submitter_email):
        print(f"[NOTIFY] {submitter_email} not yet verified in SES.")
        print(f"[NOTIFY] Verification email sent — submitter must click the link once.")
        print(f"[NOTIFY] After verification, future notifications will be delivered.")
        return

    try:
        ses     = get_aws_session().client('ses')
        vendor  = invoice.get('vendor_name', 'Unknown')
        amount  = invoice.get('total_amount', 0)
        curr    = invoice.get('currency', 'AED')
        inv_num = invoice.get('invoice_number', 'N/A')
        date    = invoice.get('invoice_date', 'N/A')

        is_approved = (status == 'APPROVED')
        color  = '#28a745' if is_approved else '#dc3545'
        icon   = '✅' if is_approved else '❌'
        subject = f"{icon} Invoice {status} — {vendor} — {amount} {curr}"

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
      <p style="margin:4px 0 0;color:#a8d5b5;font-size:13px">Petty Cash — Invoice Decision</p>
    </td>
  </tr>
  <tr>
    <td style="padding:28px 32px;text-align:center">
      <div style="font-size:52px;margin-bottom:8px">{icon}</div>
      <h2 style="color:{color};font-size:22px;margin:0 0 6px">Your Invoice has been {status}</h2>
      <p style="color:#6c757d;font-size:14px;margin:0 0 20px">
        The finance manager has reviewed your submission.
      </p>
      <table width="100%" cellpadding="0" cellspacing="0"
             style="background:#f8f9fa;border-radius:8px;overflow:hidden;text-align:left">
        <tr style="background:#e9ecef">
          <td colspan="2" style="padding:10px 16px;font-weight:700;font-size:11px;
                                  color:#495057;text-transform:uppercase;letter-spacing:.5px">
            Invoice Details
          </td>
        </tr>
        <tr>
          <td style="padding:8px 16px;color:#6c757d;font-size:13px;width:38%">Vendor</td>
          <td style="padding:8px 16px;font-weight:600;font-size:13px">{vendor}</td>
        </tr>
        <tr style="background:#fff">
          <td style="padding:8px 16px;color:#6c757d;font-size:13px">Invoice No</td>
          <td style="padding:8px 16px;font-weight:600;font-size:13px">{inv_num}</td>
        </tr>
        <tr>
          <td style="padding:8px 16px;color:#6c757d;font-size:13px">Date</td>
          <td style="padding:8px 16px;font-weight:600;font-size:13px">{date}</td>
        </tr>
        <tr style="background:#fff">
          <td style="padding:8px 16px;color:#6c757d;font-size:13px">Amount</td>
          <td style="padding:8px 16px;font-weight:700;font-size:14px;color:{color}">{amount} {curr}</td>
        </tr>
        <tr>
          <td style="padding:10px 16px;color:#6c757d;font-size:13px">Decision</td>
          <td style="padding:10px 16px">
            <span style="background:{color};color:#fff;padding:4px 14px;
                         border-radius:20px;font-size:12px;font-weight:700">{status}</span>
          </td>
        </tr>
      </table>
      <p style="font-size:11px;color:#adb5bd;margin-top:16px">
        Invoice ID: <span style="font-family:monospace">{invoice_id}</span>
      </p>
    </td>
  </tr>
  <tr>
    <td style="background:#f8f9fa;padding:14px 32px;text-align:center;
               border-top:1px solid #dee2e6">
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
Al Islami Foods — Petty Cash Decision
======================================
Your invoice has been {status} by the finance manager.

Vendor      : {vendor}
Invoice No  : {inv_num}
Date        : {date}
Amount      : {amount} {curr}
Decision    : {status}
Invoice ID  : {invoice_id}

Al Islami Foods Petty Cash AI
        """

        from_email = os.getenv('APPROVAL_EMAIL')
        ses.send_email(
            Source=from_email,
            Destination={'ToAddresses': [submitter_email]},
            Message={
                'Subject': {'Data': subject,  'Charset': 'UTF-8'},
                'Body': {
                    'Html': {'Data': html,  'Charset': 'UTF-8'},
                    'Text': {'Data': plain, 'Charset': 'UTF-8'}
                }
            }
        )
        print(f"[NOTIFY] ✓ Notification sent to {submitter_email} — {status}")

    except Exception as e:
        print(f"[NOTIFY ERROR] Failed to send to {submitter_email}: {e}")


def parse_multipart(body: bytes, content_type: str):
    """Parse multipart/form-data. Returns dict with file_data, filename, submitter_email."""
    result = {'file_data': None, 'filename': 'invoice.pdf', 'submitter_email': ''}
    if 'boundary=' not in content_type:
        return result
    boundary = content_type.split('boundary=')[-1].strip().encode()
    parts    = body.split(b'--' + boundary)
    for part in parts:
        if b'Content-Disposition' not in part:
            continue
        if b'\r\n\r\n' not in part:
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
                    field_name = seg.split('=',1)[1].strip().strip('"')
                elif seg.startswith('filename='):
                    filename = seg.split('=',1)[1].strip().strip('"')
        if field_name == 'submitter_email':
            result['submitter_email'] = content.decode('utf-8', errors='ignore').strip()
        elif field_name == 'file' and filename:
            safe = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_')
            clean = ''.join(c if c in safe else '_' for c in filename.split('\n')[0].strip())
            result['filename']  = clean or 'invoice.pdf'
            result['file_data'] = content
    return result


class Handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        path   = parsed.path

        # ── Approve / Reject ───────────────────────────────────────────────
        if path == '/action':
            invoice_id = params.get('invoice_id', [None])[0]
            action     = params.get('action',     [None])[0]
            if not invoice_id or action not in ['approve', 'reject']:
                return self._respond(400, 'Invalid request')
            invoice = get_invoice(invoice_id)
            if not invoice:
                return self._respond(404, f'Invoice {invoice_id} not found')
            if invoice.get('status') in ['APPROVED', 'REJECTED']:
                return self._html_response(invoice_id, invoice.get('status'), invoice, already_done=True)

            new_status = 'APPROVED' if action == 'approve' else 'REJECTED'
            update_invoice_status(invoice_id, new_status)
            invoice['status'] = new_status

            submitter_email = invoice.get('submitter_email', '').strip()
            print(f"[ACTION] {invoice_id} -> {new_status} | submitter_email='{submitter_email}'")

            # Send notification to submitter in background
            if submitter_email:
                threading.Thread(
                    target=send_submitter_notification,
                    args=(submitter_email, invoice, new_status, invoice_id),
                    daemon=True
                ).start()
            else:
                print(f"[ACTION] No submitter_email on record {invoice_id} — no notification sent")

            return self._html_response(invoice_id, new_status, invoice)

        # ── Records ────────────────────────────────────────────────────────
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

            # Write temp file and upload to S3
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

            # Auto-verify submitter email in SES sandbox (background)
            if submitter_email:
                threading.Thread(
                    target=ensure_ses_verified,
                    args=(submitter_email,),
                    daemon=True
                ).start()

            # Tracking ID
            tracking_id = str(uuid.uuid4())[:8].upper()
            pipeline_status[tracking_id] = {'pipeline_status': 'processing', 'current_step': 1}

            def run_agent(tid, key, sub_email):
                from agent.agent_core import run_petty_cash_agent
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
                    print(f"[PIPELINE] {tid} -> {result.get('status')} | submitter={sub_email}")
                except Exception as e:
                    pipeline_status[tid] = {
                        'pipeline_status': 'error', 'current_step': 1, 'error': str(e)
                    }
                    print(f"[ERROR] {tid}: {e}")
                    import traceback; traceback.print_exc()

            threading.Thread(target=run_agent, args=(tracking_id, s3_key, submitter_email), daemon=True).start()
            self._json(200, {'tracking_id': tracking_id, 'invoice_id': tracking_id, 's3_key': s3_key})

        except Exception as e:
            print(f"[UPLOAD ERROR] {e}")
            import traceback; traceback.print_exc()
            self._respond(500, str(e))

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin',  '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _respond(self, code, msg):
        try:
            self.send_response(code); self._cors()
            self.send_header('Content-Type','text/plain')
            self.end_headers(); self.wfile.write(msg.encode())
        except Exception: pass

    def _json(self, code, data):
        try:
            payload = json.dumps(data, default=str).encode()
            self.send_response(code); self._cors()
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers(); self.wfile.write(payload)
        except Exception: pass

    def _html_response(self, invoice_id, status, invoice, already_done=False):
        color  = '#28a745' if status=='APPROVED' else '#dc3545'
        icon   = '&#10003;' if status=='APPROVED' else '&#10007;'
        msg    = 'already been' if already_done else 'been'
        vendor = invoice.get('vendor_name','Unknown')
        amount = invoice.get('total_amount',0)
        curr   = invoice.get('currency','AED')
        sub    = invoice.get('submitter_email','').strip()
        notif  = (f'<p style="color:#6c757d;font-size:13px;margin-top:12px">'
                  f'Notification sent to: <strong>{sub}</strong></p>') if sub else ''
        html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Invoice {status}</title>
<style>
body{{font-family:'Segoe UI',Arial,sans-serif;background:#f4f4f4;
  display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
.card{{background:#fff;border-radius:16px;padding:40px 48px;text-align:center;
  max-width:440px;width:92%;box-shadow:0 4px 24px rgba(0,0,0,.1)}}
.icon{{font-size:56px;color:{color};margin-bottom:8px}}
h2{{color:#212529;margin:8px 0;font-size:22px}}
.badge{{background:{color};color:#fff;padding:10px 28px;border-radius:24px;
  font-size:15px;font-weight:700;display:inline-block;margin:16px 0}}
.detail{{color:#6c757d;font-size:14px;line-height:1.8}}
.id{{font-family:monospace;font-size:12px;color:#aaa;margin-top:16px}}
.brand{{color:#2d6a4f;font-size:11px;margin-top:20px;font-weight:600}}
</style></head>
<body><div class="card">
  <div class="icon">{icon}</div>
  <h2>Invoice has {msg} {status}</h2>
  <div class="badge">{status}</div>
  <div class="detail"><strong>{vendor}</strong><br>{amount} {curr}</div>
  {notif}
  <div class="id">Invoice ID: {invoice_id}</div>
  <div class="brand">Al Islami Foods — Petty Cash AI</div>
</div></body></html>"""
        try:
            payload = html.encode('utf-8')
            self.send_response(200); self._cors()
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers(); self.wfile.write(payload)
        except Exception: pass

    def log_message(self, *args): pass


if __name__ == '__main__':
    port   = 8000
    server = HTTPServer(('0.0.0.0', port), Handler)
    print(f"\nAl Islami Foods — Approval Server")
    print(f"{'='*45}")
    print(f"Running on : http://localhost:{port}")
    print(f"Region     : {os.getenv('AWS_DEFAULT_REGION','eu-central-1')}")
    print(f"S3 Bucket  : {os.getenv('S3_BUCKET_NAME','not set')}")
    print(f"DynamoDB   : {os.getenv('DYNAMODB_TABLE','al-islami-petty-cash')}")
    print(f"{'='*45}")
    print(f"\nEndpoints:")
    print(f"  POST /upload                  upload invoice + submitter email")
    print(f"  GET  /status/TRACKING_ID      pipeline progress")
    print(f"  GET  /records                 all DynamoDB records")
    print(f"  GET  /action?invoice_id=X&action=approve|reject")
    print(f"\nFlow:")
    print(f"  Upload -> S3 -> Textract -> Claude -> DynamoDB -> Manager email")
    print(f"  Manager approves/rejects -> Submitter notified automatically")
    print(f"\nPress Ctrl+C to stop\n")
    server.serve_forever()