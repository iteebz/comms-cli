from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from comms import services


def test_resolve_email_account_success(monkeypatch):
    monkeypatch.setattr(
        services.accts_module,
        "select_email_account",
        lambda _: ({"id": "acct-1", "email": "me@example.com"}, None),
    )
    assert services._resolve_email_account(None)["email"] == "me@example.com"


def test_resolve_email_account_error(monkeypatch):
    monkeypatch.setattr(services.accts_module, "select_email_account", lambda _: (None, "bad"))
    with pytest.raises(ValueError, match="bad"):
        services._resolve_email_account(None)


@pytest.mark.parametrize(
    ("provider", "expected"),
    [("gmail", services.gmail), ("outlook", services.outlook), ("resend", services.resend)],
)
def test_get_email_adapter(provider, expected):
    assert services._get_email_adapter(provider) is expected


def test_get_email_adapter_unsupported():
    with pytest.raises(ValueError, match="not supported"):
        services._get_email_adapter("nope")


def test_compose_email_draft(monkeypatch):
    monkeypatch.setattr(
        services,
        "_resolve_email_account",
        lambda _: {"id": "acct-1", "email": "me@example.com"},
    )
    create = Mock(return_value="draft-1")
    monkeypatch.setattr(services.drafts, "create_draft", create)
    draft_id, from_addr = services.compose_email_draft(
        to_addr="you@example.com",
        subject=None,
        body="hello",
        cc_addr="cc@example.com",
        email=None,
    )
    assert draft_id == "draft-1"
    assert from_addr == "me@example.com"
    create.assert_called_once()


def test_extract_email():
    assert services._extract_email("Name <x@example.com>") == "x@example.com"
    assert services._extract_email("  x@example.com  ") == "x@example.com"


def test_build_reply_recipients_not_reply_all():
    to_addr, cc_addr = services._build_reply_recipients(
        [{"from": "a@example.com"}], "me@example.com", False
    )
    assert to_addr == "a@example.com"
    assert cc_addr is None


def test_build_reply_recipients_reply_all():
    msgs = [
        {"from": "Me <me@example.com>", "to": "A <a@example.com>", "cc": "B <b@example.com>"},
        {
            "from": "Sender <sender@example.com>",
            "to": "Me <me@example.com>, C <c@example.com>",
            "cc": "",
        },
    ]
    to_addr, cc_addr = services._build_reply_recipients(msgs, "me@example.com", True)
    assert to_addr == "Sender <sender@example.com>"
    assert cc_addr == "a@example.com, b@example.com, c@example.com"


def test_reply_to_thread_not_found(monkeypatch):
    monkeypatch.setattr(
        services,
        "_resolve_email_account",
        lambda _: {"id": "acct-1", "email": "me@example.com", "provider": "gmail"},
    )
    monkeypatch.setattr(
        services,
        "_get_email_adapter",
        lambda _: SimpleNamespace(fetch_thread_messages=lambda *_: []),
    )
    with pytest.raises(ValueError, match="Thread not found"):
        services.reply_to_thread("t-1", "body", None)


def test_reply_to_thread_success(monkeypatch):
    monkeypatch.setattr(
        services,
        "_resolve_email_account",
        lambda _: {"id": "acct-1", "email": "me@example.com", "provider": "gmail"},
    )
    monkeypatch.setattr(
        services,
        "_get_email_adapter",
        lambda _: SimpleNamespace(
            fetch_thread_messages=lambda *_: [
                {"subject": "Topic", "from": "a@example.com", "to": "me@example.com", "cc": ""}
            ]
        ),
    )
    create = Mock(return_value="draft-1")
    monkeypatch.setattr(services.drafts, "create_draft", create)
    result = services.reply_to_thread("t-1", "body", None, reply_all=True)
    assert result == ("draft-1", "a@example.com", "Re: Topic", None)
    create.assert_called_once()


def test_send_draft_failures(monkeypatch):
    monkeypatch.setattr(services.drafts, "get_draft", lambda _: None)
    with pytest.raises(ValueError, match="not found"):
        services.send_draft("d-1")

    monkeypatch.setattr(
        services.drafts,
        "get_draft",
        lambda _: SimpleNamespace(sent_at=True, from_account_id="a", from_addr="x", to_addr="y"),
    )
    with pytest.raises(ValueError, match="already sent"):
        services.send_draft("d-1")

    monkeypatch.setattr(
        services.drafts,
        "get_draft",
        lambda _: SimpleNamespace(sent_at=None, from_account_id=None, from_addr=None, to_addr="y"),
    )
    with pytest.raises(ValueError, match="missing source account info"):
        services.send_draft("d-1")


def test_send_draft_validation_and_account_failures(monkeypatch):
    draft = SimpleNamespace(
        sent_at=None, from_account_id="acct-1", from_addr="me@example.com", to_addr="x"
    )
    monkeypatch.setattr(services.drafts, "get_draft", lambda _: draft)
    monkeypatch.setattr(services.policy, "validate_send", lambda *_: (False, ["blocked", "nope"]))
    with pytest.raises(ValueError, match="blocked; nope"):
        services.send_draft("d-1")

    monkeypatch.setattr(services.policy, "validate_send", lambda *_: (True, []))
    monkeypatch.setattr(services.accts_module, "get_account_by_id", lambda _: None)
    with pytest.raises(ValueError, match="Account not found"):
        services.send_draft("d-1")


def test_send_draft_send_failure(monkeypatch):
    draft = SimpleNamespace(
        sent_at=None, from_account_id="acct-1", from_addr="me@example.com", to_addr="x"
    )
    monkeypatch.setattr(services.drafts, "get_draft", lambda _: draft)
    monkeypatch.setattr(services.policy, "validate_send", lambda *_: (True, []))
    monkeypatch.setattr(
        services.accts_module,
        "get_account_by_id",
        lambda _: {"id": "acct-1", "provider": "gmail"},
    )
    monkeypatch.setattr(
        services,
        "_get_email_adapter",
        lambda _: SimpleNamespace(send_message=lambda *_: False),
    )
    with pytest.raises(ValueError, match="Failed to send"):
        services.send_draft("d-1")


def test_send_draft_success(monkeypatch):
    draft = SimpleNamespace(
        sent_at=None, from_account_id="acct-1", from_addr="me@example.com", to_addr="x"
    )
    monkeypatch.setattr(services.drafts, "get_draft", lambda _: draft)
    monkeypatch.setattr(services.policy, "validate_send", lambda *_: (True, []))
    monkeypatch.setattr(
        services.accts_module,
        "get_account_by_id",
        lambda _: {"id": "acct-1", "provider": "gmail"},
    )
    monkeypatch.setattr(
        services,
        "_get_email_adapter",
        lambda _: SimpleNamespace(send_message=lambda *_: True),
    )
    mark = Mock()
    monkeypatch.setattr(services.drafts, "mark_sent", mark)
    monkeypatch.setattr("comms.senders.record_action", Mock())
    services.send_draft("d-1")
    mark.assert_called_once_with("d-1")


def test_list_threads_skips_unsupported_provider(monkeypatch):
    monkeypatch.setattr(
        services.accts_module,
        "list_accounts",
        lambda _: [
            {"provider": "gmail", "email": "g@example.com"},
            {"provider": "unknown", "email": "u@example.com"},
        ],
    )
    monkeypatch.setattr(
        services,
        "_get_email_adapter",
        lambda provider: (
            SimpleNamespace(list_threads=lambda *_args, **_kwargs: [{"id": f"{provider}-1"}])
            if provider == "gmail"
            else (_ for _ in ()).throw(ValueError("unsupported"))
        ),
    )
    result = services.list_threads("inbox")
    assert len(result) == 1
    assert result[0]["threads"][0]["id"] == "gmail-1"


def test_get_unified_inbox_combines_and_sorts(monkeypatch):
    monkeypatch.setattr(
        services.accts_module,
        "list_accounts",
        lambda kind: (
            [{"provider": "gmail", "email": "g@example.com"}]
            if kind == "email"
            else [{"provider": "signal", "email": "+1555"}]
        ),
    )
    monkeypatch.setattr(
        services,
        "_get_email_adapter",
        lambda _: SimpleNamespace(
            list_threads=lambda *_args, **_kwargs: [
                {
                    "id": "t1",
                    "from": "sender@example.com",
                    "subject": "subject",
                    "snippet": "body",
                    "timestamp": 2,
                    "labels": ["UNREAD"],
                }
            ]
        ),
    )
    monkeypatch.setattr(
        services.signal,
        "get_messages",
        lambda **_kwargs: [{"id": "s1", "sender_name": "S", "body": "m", "timestamp": 3}],
    )
    items = services.get_unified_inbox(limit=2)
    assert [i.item_id for i in items] == ["s1", "t1"]


def test_fetch_thread_success_and_not_found(monkeypatch):
    monkeypatch.setattr(
        services,
        "_resolve_email_account",
        lambda _: {"email": "me@example.com", "provider": "gmail"},
    )
    monkeypatch.setattr(
        services,
        "_get_email_adapter",
        lambda _: SimpleNamespace(fetch_thread_messages=lambda *_: [{"id": "m1"}]),
    )
    assert services.fetch_thread("t1", None) == [{"id": "m1"}]
    monkeypatch.setattr(
        services,
        "_get_email_adapter",
        lambda _: SimpleNamespace(fetch_thread_messages=lambda *_: []),
    )
    with pytest.raises(ValueError, match="Thread not found"):
        services.fetch_thread("t1", None)


def test_resolve_thread_id(monkeypatch):
    monkeypatch.setattr(
        services,
        "_resolve_email_account",
        lambda _: {"email": "me@example.com", "provider": "gmail"},
    )
    monkeypatch.setattr(
        services,
        "_get_email_adapter",
        lambda _: SimpleNamespace(
            list_threads=lambda *_args, **kwargs: (
                [{"id": "abc-123"}] if kwargs["label"] == "inbox" else [{"id": "def-456"}]
            )
        ),
    )
    assert services.resolve_thread_id("0123456789abcdef", None) == "0123456789abcdef"
    assert services.resolve_thread_id("abc", None) == "abc-123"
    assert services.resolve_thread_id("zzz", None) is None


def test_thread_action_paths(monkeypatch):
    monkeypatch.setattr(
        services,
        "_resolve_email_account",
        lambda _: {"email": "me@example.com", "provider": "gmail"},
    )
    rec = Mock()
    monkeypatch.setattr("comms.senders.record_action", rec)
    adapter = SimpleNamespace(
        fetch_thread_messages=lambda *_: [{"from": "sender@example.com"}],
        archive_thread=lambda *_: True,
        delete_thread=lambda *_: True,
        flag_thread=lambda *_: False,
        unflag_thread=lambda *_: True,
        unarchive_thread=lambda *_: True,
        undelete_thread=lambda *_: True,
    )
    monkeypatch.setattr(services, "_get_email_adapter", lambda _: adapter)

    services.thread_action("archive", "t1", None)
    rec.assert_called_once()
    with pytest.raises(ValueError, match="Failed to flag thread"):
        services.thread_action("flag", "t1", None)
    with pytest.raises(ValueError, match="Unknown action"):
        services.thread_action("bad", "t1", None)


def test_execute_approved_proposals(monkeypatch):
    monkeypatch.setattr(
        services.proposals,
        "get_approved_proposals",
        lambda: [
            {"id": "p1", "proposed_action": "archive", "entity_type": "thread", "entity_id": "t1"},
            {
                "id": "p2",
                "proposed_action": "mark_read",
                "entity_type": "signal_message",
                "entity_id": "s1",
                "email": None,
            },
            {"id": "p3", "proposed_action": "archive", "entity_type": "weird", "entity_id": "x"},
        ],
    )
    monkeypatch.setattr(services, "_resolve_email_account", lambda _: {"email": "me@example.com"})
    thread_action = Mock()
    mark_executed = Mock()
    monkeypatch.setattr(services, "thread_action", thread_action)
    monkeypatch.setattr(services.proposals, "mark_executed", mark_executed)
    monkeypatch.setattr(services.signal, "mark_read", Mock())

    results = services.execute_approved_proposals()
    assert [r.success for r in results] == [True, True, False]
    assert "Unknown entity type" in (results[2].error or "")
    assert mark_executed.call_count == 2


def test_execute_signal_action():
    services._execute_signal_action("ignore", "m1")
    with pytest.raises(ValueError, match="Unknown signal action"):
        services._execute_signal_action("bad", "m1")
