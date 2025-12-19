from . import accounts, audit
from .adapters.email import gmail, outlook, proton
from .db import get_db


def sync_account(account_id: str, since_days: int = 7) -> int:
    account = accounts.get_account_by_id(account_id)
    if not account:
        return 0

    provider = account["provider"]
    email = account["email"]

    if provider == "proton":
        messages = proton.fetch_messages(account_id, email, since_days)
    elif provider == "gmail":
        messages = gmail.fetch_messages(account_id, email, since_days)
    elif provider == "outlook":
        messages = outlook.fetch_messages(account_id, email, since_days)
    else:
        return 0

    count = 0
    with get_db() as conn:
        for msg in messages:
            existing = conn.execute("SELECT id FROM messages WHERE id = ?", (msg.id,)).fetchone()
            if existing:
                continue

            thread_exists = conn.execute(
                "SELECT id FROM threads WHERE id = ?", (msg.thread_id,)
            ).fetchone()
            if not thread_exists:
                conn.execute(
                    """
                    INSERT INTO threads (id, account_id, provider, subject, participants, last_message_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        msg.thread_id,
                        msg.account_id,
                        msg.provider,
                        msg.subject,
                        f"{msg.from_addr},{msg.to_addr}",
                        msg.timestamp,
                    ),
                )

            conn.execute(
                """
                INSERT INTO messages (id, thread_id, account_id, provider, from_addr, to_addr,
                                     subject, body, body_html, headers, status, timestamp, synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg.id,
                    msg.thread_id,
                    msg.account_id,
                    msg.provider,
                    msg.from_addr,
                    msg.to_addr,
                    msg.subject,
                    msg.body,
                    msg.body_html,
                    msg.headers,
                    msg.status,
                    msg.timestamp,
                    msg.synced_at,
                ),
            )
            count += 1

    audit.log("sync", "account", account_id, {"messages_synced": count})
    return count


def sync_all_accounts(since_days: int = 7) -> dict[str, int]:
    results = {}
    for account in accounts.list_accounts("email"):
        count = sync_account(account["id"], since_days)
        results[account["email"]] = count
    return results
