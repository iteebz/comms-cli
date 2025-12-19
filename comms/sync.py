import hashlib

from . import accounts, audit
from .adapters.email import gmail, outlook, proton
from .db import get_db


def sync_account(account_id: str) -> int:
    account = accounts.get_account_by_id(account_id)
    if not account:
        return 0

    provider = account["provider"]
    email = account["email"]

    if provider == "gmail":
        threads = gmail.fetch_threads(account_id, email)
    elif provider == "proton":
        threads = proton.fetch_threads(account_id, email)
    elif provider == "outlook":
        threads = outlook.fetch_threads(account_id, email)
    else:
        return 0

    count = 0
    with get_db() as conn:
        for thread in threads:
            thread_hash = hashlib.sha256(
                f"{thread['id']}{thread['last_message_at']}".encode()
            ).hexdigest()[:16]

            existing = conn.execute(
                "SELECT id, last_seen_hash FROM threads WHERE id = ?", (thread["id"],)
            ).fetchone()

            if existing:
                if existing["last_seen_hash"] == thread_hash:
                    continue

                conn.execute(
                    """
                    UPDATE threads
                    SET subject = ?, participants = ?, last_message_at = ?,
                        needs_reply = ?, last_seen_hash = ?
                    WHERE id = ?
                    """,
                    (
                        thread["subject"],
                        thread["participants"],
                        thread["last_message_at"],
                        thread["needs_reply"],
                        thread_hash,
                        thread["id"],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO threads (id, account_id, provider, subject, participants,
                                        last_message_at, needs_reply, last_seen_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        thread["id"],
                        account_id,
                        provider,
                        thread["subject"],
                        thread["participants"],
                        thread["last_message_at"],
                        thread["needs_reply"],
                        thread_hash,
                    ),
                )
                count += 1

    audit.log("sync", "account", account_id, {"threads_synced": count})
    return count


def sync_all_accounts() -> dict[str, int]:
    results = {}
    for account in accounts.list_accounts("email"):
        count = sync_account(account["id"])
        results[account["email"]] = count
    return results
