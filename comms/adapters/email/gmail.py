import base64
import hashlib
import json
from datetime import datetime
from email.mime.text import MIMEText

import keyring
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from ...models import Draft, Message

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
SERVICE_NAME = "comms-cli/gmail"
TOKEN_KEY_SUFFIX = "/token"


def _get_token(email_addr: str) -> dict | None:
    token_json = keyring.get_password(SERVICE_NAME, f"{email_addr}{TOKEN_KEY_SUFFIX}")
    if token_json:
        return json.loads(token_json)
    return None


def _set_token(email_addr: str, token_dict: dict):
    keyring.set_password(SERVICE_NAME, f"{email_addr}{TOKEN_KEY_SUFFIX}", json.dumps(token_dict))


def _get_credentials(email_addr: str, credentials_path: str | None = None) -> Credentials:
    token_data = _get_token(email_addr)
    creds = None

    if token_data:
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not credentials_path:
                raise ValueError("credentials.json path required for initial OAuth flow")

            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)

        _set_token(email_addr, json.loads(creds.to_json()))

    return creds


def test_connection(
    account_id: str, email_addr: str, credentials_path: str | None = None
) -> tuple[bool, str]:
    try:
        creds = _get_credentials(email_addr, credentials_path)
        service = build("gmail", "v1", credentials=creds)
        service.users().getProfile(userId="me").execute()
        return True, "Connected successfully"
    except Exception as e:
        return False, f"Connection failed: {e}"


def fetch_messages(account_id: str, email_addr: str, since_days: int = 7) -> list[Message]:
    creds = _get_credentials(email_addr)
    service = build("gmail", "v1", credentials=creds)

    query = f"newer_than:{since_days}d"
    results = service.users().messages().list(userId="me", q=query, maxResults=100).execute()
    message_ids = results.get("messages", [])

    messages = []
    for msg_ref in message_ids:
        msg = service.users().messages().get(userId="me", id=msg_ref["id"], format="full").execute()

        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        msg_id = headers.get("Message-ID", msg_ref["id"])
        thread_id = msg.get("threadId", msg_id)
        from_addr = headers.get("From", "")
        to_addr = headers.get("To", "")
        subject = headers.get("Subject", "")
        date_str = headers.get("Date", "")

        body = ""
        if "parts" in msg["payload"]:
            for part in msg["payload"]["parts"]:
                if part["mimeType"] == "text/plain" and "data" in part["body"]:
                    body = base64.urlsafe_b64decode(part["body"]["data"]).decode()
                    break
        elif "body" in msg["payload"] and "data" in msg["payload"]["body"]:
            body = base64.urlsafe_b64decode(msg["payload"]["body"]["data"]).decode()

        msg_hash = hashlib.sha256(f"{msg_id}{from_addr}{date_str}".encode()).hexdigest()[:16]
        thread_hash = hashlib.sha256(thread_id.encode()).hexdigest()[:16]

        label_ids = msg.get("labelIds", [])
        status = "unread" if "UNREAD" in label_ids else "read"

        messages.append(
            Message(
                id=msg_hash,
                thread_id=thread_hash,
                account_id=account_id,
                provider="gmail",
                from_addr=from_addr,
                to_addr=to_addr,
                subject=subject,
                body=body,
                body_html=None,
                headers=json.dumps(headers),
                status=status,
                timestamp=datetime.now(),
                synced_at=datetime.now(),
            )
        )

    return messages


def send_message(account_id: str, email_addr: str, draft: Draft) -> bool:
    try:
        creds = _get_credentials(email_addr)
        service = build("gmail", "v1", credentials=creds)

        message = MIMEText(draft.body)
        message["to"] = draft.to_addr
        message["from"] = email_addr
        if draft.cc_addr:
            message["cc"] = draft.cc_addr
        message["subject"] = draft.subject or "(no subject)"

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return True
    except Exception:
        return False


def store_credentials(email_addr: str, credentials_path: str):
    _get_credentials(email_addr, credentials_path)
