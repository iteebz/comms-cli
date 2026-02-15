import json
import subprocess
from datetime import datetime
from pathlib import Path

SIGNAL_CLI = "signal-cli"
CONFIG_DIR = Path.home() / ".local/share/signal-cli"


def _store_messages(phone: str, messages: list[dict]) -> int:
    from ...db import get_db

    stored = 0
    with get_db() as conn:
        for msg in messages:
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO signal_messages
                    (id, account_phone, sender_phone, sender_name, body, timestamp, group_id, received_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        msg["id"],
                        phone,
                        msg["from"],
                        msg.get("from_name", ""),
                        msg["body"],
                        msg["timestamp"],
                        msg.get("group"),
                        datetime.now().isoformat(),
                    ),
                )
                stored += 1
            except Exception:
                pass
    return stored


def get_messages(
    phone: str | None = None,
    sender: str | None = None,
    limit: int = 50,
    unread_only: bool = False,
) -> list[dict]:
    from ...db import get_db

    query = "SELECT * FROM signal_messages WHERE 1=1"
    params = []

    if phone:
        query += " AND account_phone = ?"
        params.append(phone)
    if sender:
        query += " AND sender_phone = ?"
        params.append(sender)
    if unread_only:
        query += " AND read_at IS NULL"

    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def get_message(message_id: str) -> dict | None:
    from ...db import get_db

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM signal_messages WHERE id = ? OR id LIKE ?",
            (message_id, f"{message_id}%"),
        ).fetchone()
        return dict(row) if row else None


def mark_read(message_id: str) -> bool:
    from ...db import get_db

    with get_db() as conn:
        conn.execute(
            "UPDATE signal_messages SET read_at = ? WHERE id = ?",
            (datetime.now().isoformat(), message_id),
        )
    return True


def reply(phone: str, message_id: str, body: str) -> tuple[bool, str, dict | None]:
    msg = get_message(message_id)
    if not msg:
        return False, f"Message {message_id} not found", None

    recipient = msg["sender_phone"]
    success, result = send(phone, recipient, body)

    if success:
        mark_read(msg["id"])

    return success, result, msg


def get_conversations(phone: str) -> list[dict]:
    from ...db import get_db

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT sender_phone, sender_name,
                   COUNT(*) as message_count,
                   MAX(timestamp) as last_timestamp,
                   SUM(CASE WHEN read_at IS NULL THEN 1 ELSE 0 END) as unread_count
            FROM signal_messages
            WHERE account_phone = ?
            GROUP BY sender_phone
            ORDER BY last_timestamp DESC
            """,
            (phone,),
        ).fetchall()
        return [dict(row) for row in rows]


def _run(args: list[str], account: str | None = None) -> dict | list | None:
    cmd = [SIGNAL_CLI]
    if account:
        cmd.extend(["-a", account])
    cmd.extend(args)
    cmd.extend(["--output=json"])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return None
        if not result.stdout.strip():
            return {}
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        return None


def list_accounts() -> list[str]:
    result = subprocess.run(
        [SIGNAL_CLI, "listAccounts"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return []
    accounts = []
    for line in result.stdout.strip().split("\n"):
        if line.startswith("Number: "):
            accounts.append(line.replace("Number: ", "").strip())
    return accounts


def is_registered(phone: str) -> bool:
    accounts = list_accounts()
    return phone in accounts


def register(phone: str) -> tuple[bool, str]:
    result = subprocess.run(
        [SIGNAL_CLI, "-a", phone, "register"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True, "Verification code sent via SMS"
    return False, result.stderr or "Registration failed"


def verify(phone: str, code: str) -> tuple[bool, str]:
    result = subprocess.run(
        [SIGNAL_CLI, "-a", phone, "verify", code],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True, "Verified successfully"
    return False, result.stderr or "Verification failed"


def link(device_name: str = "comms-cli") -> tuple[bool, str]:
    import io

    import qrcode

    process = subprocess.Popen(
        [SIGNAL_CLI, "link", "-n", device_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    uri = None
    if process.stdout:
        for line in iter(process.stdout.readline, ""):
            line = line.strip()
            if line.startswith("sgnl://") or line.startswith("tsdevice:"):
                uri = line
                break

    if not uri:
        process.terminate()
        stderr = process.stderr.read() if process.stderr else ""
        return False, f"No device URI received. stderr: {stderr}"

    qr = qrcode.QRCode(border=1)
    qr.add_data(uri)
    qr.make()

    f = io.StringIO()
    qr.print_ascii(out=f, invert=True)
    print(f.getvalue())

    try:
        process.wait(timeout=120)
        if process.returncode == 0:
            return True, "Linked successfully"
        return False, (process.stderr.read() if process.stderr else "") or "Link failed"
    except subprocess.TimeoutExpired:
        process.terminate()
        return False, "Timeout waiting for scan"


def receive(phone: str, timeout: int = 1, store: bool = True) -> list[dict]:
    result = subprocess.run(
        [SIGNAL_CLI, "-a", phone, "receive", "-t", str(timeout), "--output=json"],
        capture_output=True,
        text=True,
        timeout=timeout + 10,
    )
    if result.returncode != 0:
        return []

    messages = []
    if not result.stdout.strip():
        return messages

    try:
        envelopes = json.loads(result.stdout)
    except json.JSONDecodeError:
        return messages

    if not isinstance(envelopes, list):
        return messages

    for envelope in envelopes:
        if not isinstance(envelope, dict):
            continue

        sync_msg = envelope.get("syncMessage", {})
        data_msg = envelope.get("dataMessage", {})
        source = envelope.get("source") or envelope.get("sourceNumber", "")
        source_name = envelope.get("sourceName", "")
        timestamp = envelope.get("timestamp", 0)

        body = data_msg.get("message") or sync_msg.get("message")
        if not body or not source:
            continue

        group_info = data_msg.get("groupInfo")
        group_id = group_info.get("groupId") if group_info else None

        messages.append(
            {
                "id": str(timestamp),
                "from": source,
                "from_name": source_name,
                "body": body,
                "timestamp": timestamp,
                "group": group_id,
            }
        )

    if store and messages:
        _store_messages(phone, messages)

    return messages


def send(phone: str, recipient: str, message: str) -> tuple[bool, str]:
    result = subprocess.run(
        [SIGNAL_CLI, "-a", phone, "send", "-m", message, recipient],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode == 0:
        return True, "Sent"
    return False, result.stderr or "Send failed"


def send_group(phone: str, group_id: str, message: str) -> tuple[bool, str]:
    result = subprocess.run(
        [SIGNAL_CLI, "-a", phone, "send", "-m", message, "-g", group_id],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode == 0:
        return True, "Sent to group"
    return False, result.stderr or "Send failed"


def list_groups(phone: str) -> list[dict]:
    result = _run(["listGroups"], account=phone)
    if not result or not isinstance(result, list):
        return []
    return [{"id": g.get("id", ""), "name": g.get("name", "")} for g in result]


def list_contacts(phone: str) -> list[dict]:
    result = _run(["listContacts"], account=phone)
    if not result or not isinstance(result, list):
        return []
    return [
        {"number": c.get("number", ""), "name": c.get("name", "")}
        for c in result
        if c.get("number")
    ]


def test_connection(phone: str) -> tuple[bool, str]:
    if not is_registered(phone):
        return False, "Account not registered"
    result = _run(["getUserStatus", phone], account=phone)
    if result is None:
        return False, "Failed to get user status"
    return True, "Connected"
