import sys, os
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv(override=True)
from approval_server import send_submitter_notification

invoice = {
    'vendor_name'    : 'Global Tech Supplies Inc.',
    'invoice_number' : 'INV-2024-0131',
    'invoice_date'   : '2024-01-31',
    'total_amount'   : '275727.1',
    'currency'       : 'USD',
    'submitter_email': 'prapultivanani@gmail.com'
}
send_submitter_notification('prapultivanani@gmail.com', invoice, 'REJECTED', '2A1B2532')
print('Done — check prapultivanani@gmail.com inbox')
