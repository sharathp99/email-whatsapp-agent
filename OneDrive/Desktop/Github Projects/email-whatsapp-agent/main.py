import os
import base64
import time
import schedule
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from dotenv import load_dotenv
import openai
from twilio.rest import Client
from bs4 import BeautifulSoup

# Load environment variables
load_dotenv()

# Gmail API scope
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def authenticate_gmail():
    """Authenticate Gmail API and return service credentials"""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    print("Gmail authentication successful.")
    return creds

def get_email_body(payload):
    """Recursively extract email body (plain text or HTML)"""
    if 'parts' in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain' and 'data' in part['body']:
                return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
            elif part['mimeType'] == 'text/html' and 'data' in part['body']:
                html_body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                soup = BeautifulSoup(html_body, 'html.parser')
                return soup.get_text()
            elif 'parts' in part:
                body = get_email_body(part)
                if body:
                    return body
    elif 'body' in payload and 'data' in payload['body']:
        return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
    return "No Content"

def fetch_emails():
    """Fetch latest 5 emails from Gmail inbox"""
    creds = authenticate_gmail()
    service = build('gmail', 'v1', credentials=creds)
    emails = []

    try:
        results = service.users().messages().list(userId='me', labelIds=['INBOX'], maxResults=5).execute()
        messages = results.get('messages', [])

        for msg in messages:
            msg_data = service.users().messages().get(userId='me', id=msg['id']).execute()
            headers = msg_data.get('payload', {}).get('headers', [])
            subject = next((item['value'] for item in headers if item['name'] == 'Subject'), 'No Subject')
            body = get_email_body(msg_data['payload'])
            emails.append({'subject': subject, 'body': body})
    except Exception as e:
        print(f"Error fetching emails: {e}")

    return emails

def summarize_email(email_body):
    """Summarize email content using OpenAI GPT-4"""
    openai.api_key = os.getenv('OPENAI_API_KEY')
    email_body = email_body[:2000]  # Limit size for GPT input
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that summarizes emails."},
                {"role": "user", "content": f"Summarize this email in 2-3 sentences: {email_body}"}
            ]
        )
        return response['choices'][0]['message']['content']
    except Exception as e:
        print(f"Error generating summary: {e}")
        return "Failed to generate summary."

def send_whatsapp_message(message):
    """Send message via WhatsApp using Twilio"""
    try:
        client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
        msg = client.messages.create(
            body=message,
            from_=os.getenv('TWILIO_WHATSAPP_NUMBER'),
            to=os.getenv('YOUR_WHATSAPP_NUMBER')
        )
        return msg.sid
    except Exception as e:
        print(f"Error sending WhatsApp message: {e}")
        return None

def job():
    """Main job: fetch emails, summarize, send WhatsApp messages"""
    print("Checking for new emails...")
    emails = fetch_emails()
    print(f"Fetched {len(emails)} emails.")

    for email in emails:
        summary = summarize_email(email['body'])
        sid = send_whatsapp_message(f"Subject: {email['subject']}\nSummary: {summary}")
        if sid:
            print(f"Sent summary: {summary}")
        else:
            print(f"Failed to send summary for email: {email['subject']}")

# Schedule the job every 10 minutes
schedule.every(10).minutes.do(job)

print("Email WhatsApp bot started...")
while True:
    try:
        schedule.run_pending()
    except Exception as e:
        print(f"Error in scheduled job: {e}")
    time.sleep(1)
