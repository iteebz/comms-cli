import hashlib
import json
from datetime import datetime, timedelta

import keyring
import msal
import requests

from ...models import Draft, Message

AUTHORITY = "https://login.microsoftonline.com/common"
SCOPES = ["https://graph.microsoft.com/Mail.ReadWrite"]
GRAPH_API_ENDPOINT = "https://graph.microsoft.com/v1.0"

SERVICE_NAME = "comms-cli/outlook"
TOKEN_KEY_SUFFIX = "/token"
CLIENT_ID_SUFFIX = "/client_id"
CLIENT_SECRET_SUFFIX = "/client_secret"


def _get_token(email_addr: str) -> dict | None:
    token_json = keyring.get_password(SERVICE_NAME, f"{email_addr}{TOKEN_KEY_SUFFIX}")
    if token_json:
        return json.loads(token_json)
    return None


def _set_token(email_addr: str, token_dict: dict):
    keyring.set_password(SERVICE_NAME, f"{email_addr}{TOKEN_KEY_SUFFIX}", json.dumps(token_dict))


def _get_client_creds(email_addr: str) -> tuple[str | None, str | None]:
    client_id = keyring.get_password(SERVICE_NAME, f"{email_addr}{CLIENT_ID_SUFFIX}")
    client_secret = keyring.get_password(SERVICE_NAME, f"{email_addr}{CLIENT_SECRET_SUFFIX}")
    return client_id, client_secret


def _set_client_creds(email_addr: str, client_id: str, client_secret: str):
    keyring.set_password(SERVICE_NAME, f"{email_addr}{CLIENT_ID_SUFFIX}", client_id)
    keyring.set_password(SERVICE_NAME, f"{email_addr}{CLIENT_SECRET_SUFFIX}", client_secret)


def _get_access_token(email_addr: str) -> str | None:
    client_id, client_secret = _get_client_creds(email_addr)
    if not client_id or not client_secret:
        return None

    _get_token(email_addr)
    app = msal.ConfidentialClientApplication(
        client_id, authority=AUTHORITY, client_credential=client_secret
    )

    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            return result["access_token"]

    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise ValueError("Failed to create device flow")

    print(flow["message"])

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" in result:
        _set_token(email_addr, result)
        return result["access_token"]

    return None


def test_connection(
    account_id: str, email_addr: str, client_id: str | None = None, client_secret: str | None = None
) -> tuple[bool, str]:
    if client_id and client_secret:
        _set_client_creds(email_addr, client_id, client_secret)

    try:
        token = _get_access_token(email_addr)
        if not token:
            return False, "Failed to get access token"

        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(f"{GRAPH_API_ENDPOINT}/me", headers=headers)
        if response.status_code == 200:
            return True, "Connected successfully"
        return False, f"HTTP {response.status_code}"
    except Exception as e:
        return False, f"Connection failed: {e}"


def fetch_threads(account_id: str, email_addr: str) -> list[dict]:
    return []


def fetch_messages(account_id: str, email_addr: str, since_days: int = 7) -> list[Message]:
    token = _get_access_token(email_addr)
    if not token:
        return []

    headers = {"Authorization": f"Bearer {token}"}
    since_date = (datetime.now() - timedelta(days=since_days)).isoformat()
    filter_query = f"receivedDateTime ge {since_date}"

    response = requests.get(
        f"{GRAPH_API_ENDPOINT}/me/messages",
        headers=headers,
        params={"$filter": filter_query, "$top": 100},
    )

    if response.status_code != 200:
        return []

    messages = []
    for item in response.json().get("value", []):
        msg_id = item.get("id", "")
        thread_id = item.get("conversationId", msg_id)
        from_addr = item.get("from", {}).get("emailAddress", {}).get("address", "")
        to_addrs = item.get("toRecipients", [])
        to_addr = to_addrs[0].get("emailAddress", {}).get("address", "") if to_addrs else ""
        subject = item.get("subject", "")
        body = item.get("body", {}).get("content", "")
        received_dt = item.get("receivedDateTime", "")
        is_read = item.get("isRead", True)

        msg_hash = hashlib.sha256(f"{msg_id}{from_addr}{received_dt}".encode()).hexdigest()[:16]
        thread_hash = hashlib.sha256(thread_id.encode()).hexdigest()[:16]

        messages.append(
            Message(
                id=msg_hash,
                thread_id=thread_hash,
                account_id=account_id,
                provider="outlook",
                from_addr=from_addr,
                to_addr=to_addr,
                subject=subject,
                body=body,
                body_html=item.get("body", {}).get("content", ""),
                headers=json.dumps(item),
                status="read" if is_read else "unread",
                timestamp=datetime.fromisoformat(received_dt.replace("Z", "+00:00")),
                synced_at=datetime.now(),
            )
        )

    return messages


def send_message(account_id: str, email_addr: str, draft: Draft) -> bool:
    token = _get_access_token(email_addr)
    if not token:
        return False

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    message = {
        "subject": draft.subject or "(no subject)",
        "body": {"contentType": "Text", "content": draft.body},
        "toRecipients": [{"emailAddress": {"address": draft.to_addr}}],
    }

    if draft.cc_addr:
        message["ccRecipients"] = [{"emailAddress": {"address": draft.cc_addr}}]

    response = requests.post(
        f"{GRAPH_API_ENDPOINT}/me/sendMail", headers=headers, json={"message": message}
    )

    return response.status_code == 202


def store_credentials(email_addr: str, client_id: str, client_secret: str):
    _set_client_creds(email_addr, client_id, client_secret)
