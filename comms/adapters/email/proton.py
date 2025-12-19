import email
import hashlib
import imaplib
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import keyring

from ...models import Draft, Message

PROTON_IMAP_HOST = "127.0.0.1"
PROTON_IMAP_PORT = 1143
PROTON_SMTP_HOST = "127.0.0.1"
PROTON_SMTP_PORT = 1025

SERVICE_NAME = "comms-cli/proton"


def _get_password(email_addr: str) -> str | None:
    return keyring.get_password(SERVICE_NAME, email_addr)


def _set_password(email_addr: str, password: str):
    keyring.set_password(SERVICE_NAME, email_addr, password)


def test_connection(account_id: str, email_addr: str) -> tuple[bool, str]:
    password = _get_password(email_addr)
    if not password:
        return False, "No password found in keyring"

    try:
        mail = imaplib.IMAP4(PROTON_IMAP_HOST, PROTON_IMAP_PORT)
        mail.login(email_addr, password)
        mail.logout()
        return True, "Connected successfully"
    except Exception as e:
        return False, f"Connection failed: {e}"


def fetch_messages(account_id: str, email_addr: str, since_days: int = 7) -> list[Message]:
    password = _get_password(email_addr)
    if not password:
        return []

    mail = imaplib.IMAP4(PROTON_IMAP_HOST, PROTON_IMAP_PORT)
    mail.login(email_addr, password)
    mail.select("INBOX")

    since_date = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
    _, message_numbers = mail.search(None, f"(SINCE {since_date})")

    messages = []
    for num in message_numbers[0].split():
        _, msg_data = mail.fetch(num, "(RFC822)")
        email_body = msg_data[0][1]
        email_message = email.message_from_bytes(email_body)

        msg_id = email_message.get("Message-ID", "")
        thread_id = email_message.get("In-Reply-To") or msg_id
        from_addr = email_message.get("From", "")
        to_addr = email_message.get("To", "")
        subject = email_message.get("Subject", "")
        date_str = email_message.get("Date", "")

        body = ""
        if email_message.is_multipart():
            for part in email_message.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode()
                    break
        else:
            body = email_message.get_payload(decode=True).decode()

        msg_hash = hashlib.sha256(f"{msg_id}{from_addr}{date_str}".encode()).hexdigest()[:16]

        messages.append(
            Message(
                id=msg_hash,
                thread_id=hashlib.sha256(thread_id.encode()).hexdigest()[:16],
                account_id=account_id,
                provider="proton",
                from_addr=from_addr,
                to_addr=to_addr,
                subject=subject,
                body=body,
                body_html=None,
                headers=str(email_message),
                status="unread",
                timestamp=datetime.now(),
                synced_at=datetime.now(),
            )
        )

    mail.logout()
    return messages


def send_message(account_id: str, email_addr: str, draft: Draft) -> bool:
    password = _get_password(email_addr)
    if not password:
        return False

    msg = MIMEMultipart()
    msg["From"] = email_addr
    msg["To"] = draft.to_addr
    if draft.cc_addr:
        msg["Cc"] = draft.cc_addr
    msg["Subject"] = draft.subject or "(no subject)"

    msg.attach(MIMEText(draft.body, "plain"))

    try:
        server = smtplib.SMTP(PROTON_SMTP_HOST, PROTON_SMTP_PORT)
        server.login(email_addr, password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception:
        return False


def store_credentials(email_addr: str, password: str):
    _set_password(email_addr, password)
