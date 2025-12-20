from __future__ import annotations

from dataclasses import dataclass

from . import accounts as accts_module
from . import drafts, policy, proposals
from .adapters.email import gmail, outlook
from .adapters.messaging import signal


@dataclass(frozen=True)
class ProposalExecution:
    proposal_id: str
    action: str
    entity_type: str
    entity_id: str
    success: bool
    error: str | None


def _resolve_email_account(email: str | None) -> dict:
    account, error = accts_module.select_email_account(email)
    if account:
        return account
    raise ValueError(error or "No email account found")


def _get_email_adapter(provider: str):
    if provider == "gmail":
        return gmail
    if provider == "outlook":
        return outlook
    raise ValueError(f"Provider {provider} not supported")


def compose_email_draft(
    to_addr: str,
    subject: str | None,
    body: str,
    cc_addr: str | None,
    email: str | None,
) -> tuple[str, str]:
    account = _resolve_email_account(email)
    from_addr = account["email"]

    draft_id = drafts.create_draft(
        to_addr=to_addr,
        subject=subject or "(no subject)",
        body=body,
        cc_addr=cc_addr,
        from_account_id=account["id"],
        from_addr=from_addr,
    )

    return draft_id, from_addr


def reply_to_thread(
    thread_id: str,
    body: str,
    email: str | None,
) -> tuple[str, str, str]:
    account = _resolve_email_account(email)
    adapter = _get_email_adapter(account["provider"])
    from_addr = account["email"]

    messages = adapter.fetch_thread_messages(thread_id, from_addr)
    if not messages:
        raise ValueError(f"Thread not found: {thread_id}")

    original_subject = messages[0]["subject"]
    reply_subject = (
        original_subject if original_subject.startswith("Re: ") else f"Re: {original_subject}"
    )
    original_from = messages[-1]["from"]

    draft_id = drafts.create_draft(
        to_addr=original_from,
        subject=reply_subject,
        body=body,
        thread_id=thread_id,
        from_account_id=account["id"],
        from_addr=from_addr,
    )

    return draft_id, original_from, reply_subject


def send_draft(draft_id: str) -> None:
    d = drafts.get_draft(draft_id)
    if not d:
        raise ValueError(f"Draft {draft_id} not found")
    if d.sent_at:
        raise ValueError("Draft already sent")
    if not d.from_account_id or not d.from_addr:
        raise ValueError("Draft missing source account info")

    ok, errors = policy.validate_send(draft_id, d.to_addr)
    if not ok:
        raise ValueError("; ".join(errors))

    account = accts_module.get_account_by_id(d.from_account_id)
    if not account:
        raise ValueError(f"Account not found: {d.from_account_id}")

    adapter = _get_email_adapter(account["provider"])
    success = adapter.send_message(account["id"], d.from_addr, d)

    if not success:
        raise ValueError("Failed to send")

    drafts.mark_sent(draft_id)


def list_threads(label: str) -> list[dict]:
    accounts = accts_module.list_accounts("email")
    results = []
    for account in accounts:
        try:
            adapter = _get_email_adapter(account["provider"])
            threads = adapter.list_threads(account["email"], label=label)
            results.append({"account": account, "threads": threads})
        except ValueError:
            continue
    return results


@dataclass
class InboxItem:
    source: str
    source_id: str
    sender: str
    preview: str
    timestamp: int
    unread: bool
    item_id: str


def get_unified_inbox(limit: int = 20) -> list[InboxItem]:
    items: list[InboxItem] = []

    email_accounts = accts_module.list_accounts("email")
    for account in email_accounts:
        try:
            adapter = _get_email_adapter(account["provider"])
            threads = adapter.list_threads(account["email"], label="inbox", max_results=limit)
            for t in threads:
                items.append(
                    InboxItem(
                        source="email",
                        source_id=account["email"],
                        sender=t.get("from", "Unknown"),
                        preview=t.get("snippet", "")[:60],
                        timestamp=t.get("timestamp", 0),
                        unread="UNREAD" in t.get("labels", []),
                        item_id=t["id"],
                    )
                )
        except ValueError:
            continue

    signal_accounts = accts_module.list_accounts("messaging")
    for account in signal_accounts:
        if account["provider"] == "signal":
            msgs = signal.get_messages(phone=account["email"], limit=limit, unread_only=False)
            for m in msgs:
                items.append(
                    InboxItem(
                        source="signal",
                        source_id=account["email"],
                        sender=m.get("sender_name") or m.get("sender_phone", "Unknown"),
                        preview=m.get("body", "")[:60],
                        timestamp=m.get("timestamp", 0),
                        unread=m.get("read_at") is None,
                        item_id=m.get("id", ""),
                    )
                )

    items.sort(key=lambda x: x.timestamp, reverse=True)
    return items[:limit]


def fetch_thread(thread_id: str, email: str | None) -> list[dict]:
    account = _resolve_email_account(email)
    adapter = _get_email_adapter(account["provider"])
    messages = adapter.fetch_thread_messages(thread_id, account["email"])
    if not messages:
        raise ValueError(f"Thread not found: {thread_id}")
    return messages


def resolve_thread_id(prefix: str, email: str | None) -> str | None:
    account = _resolve_email_account(email)
    adapter = _get_email_adapter(account["provider"])
    if len(prefix) >= 16:
        return prefix

    threads = adapter.list_threads(account["email"], label="inbox", max_results=100)
    threads += adapter.list_threads(account["email"], label="unread", max_results=100)
    for thread in threads:
        if thread["id"].startswith(prefix):
            return thread["id"]
    return None


def thread_action(action: str, thread_id: str, email: str | None) -> None:
    account = _resolve_email_account(email)
    adapter = _get_email_adapter(account["provider"])
    action_fn = _get_thread_action(adapter, action)
    if not action_fn:
        raise ValueError(f"Unknown action: {action}")
    success = action_fn(thread_id, account["email"])
    if not success:
        raise ValueError(f"Failed to {action} thread")


def _get_thread_action(adapter, action: str):
    action_map = {
        "archive": adapter.archive_thread,
        "delete": adapter.delete_thread,
        "flag": adapter.flag_thread,
        "unflag": adapter.unflag_thread,
        "unarchive": adapter.unarchive_thread,
        "undelete": adapter.undelete_thread,
    }
    return action_map.get(action)


def execute_approved_proposals() -> list[ProposalExecution]:
    approved = proposals.get_approved_proposals()
    results: list[ProposalExecution] = []

    for proposal in approved:
        action = proposal["proposed_action"]
        entity_type = proposal["entity_type"]
        entity_id = proposal["entity_id"]
        email = proposal.get("email")

        try:
            if entity_type == "thread":
                if not email:
                    account = _resolve_email_account(None)
                    email = account["email"]
                thread_action(action, entity_id, email)
            elif entity_type == "signal_message":
                _execute_signal_action(action, entity_id)
            else:
                raise ValueError(f"Unknown entity type: {entity_type}")
            proposals.mark_executed(proposal["id"])
            results.append(
                ProposalExecution(
                    proposal_id=proposal["id"],
                    action=action,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    success=True,
                    error=None,
                )
            )
        except ValueError as exc:
            results.append(
                ProposalExecution(
                    proposal_id=proposal["id"],
                    action=action,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    success=False,
                    error=str(exc),
                )
            )

    return results


def _execute_signal_action(action: str, message_id: str) -> None:
    if action in ("mark_read", "ignore"):
        signal.mark_read(message_id)
    else:
        raise ValueError(f"Unknown signal action: {action}")
