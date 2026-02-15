from contextlib import contextmanager

import pytest

from comms import config as comms_config
from comms import db, proposals


@pytest.fixture()
def initialized_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(comms_config, "DB_PATH", db_path)
    monkeypatch.setattr(comms_config, "BACKUP_DIR", tmp_path / "backups")
    db.init(db_path)
    return db_path


@pytest.mark.parametrize(
    ("entity_type", "action", "ok"),
    [
        ("thread", "archive", True),
        ("thread", "bad", False),
        ("draft", "send", True),
        ("draft", "bad", False),
        ("signal_message", "ignore", True),
        ("signal_message", "bad", False),
    ],
)
def test_validate_action(entity_type, action, ok):
    valid, _ = proposals._validate_action(entity_type, action)
    assert valid is ok


def test_validate_action_unknown_entity():
    valid, msg = proposals._validate_action("wat", "x")
    assert not valid
    assert "Unknown entity_type" in msg


def test_validate_entity_thread_account_error(monkeypatch):
    monkeypatch.setattr(proposals.accts_module, "select_email_account", lambda _: (None, "missing"))
    valid, msg = proposals._validate_entity("thread", "t1", None)
    assert not valid
    assert msg == "missing"


def test_validate_entity_thread_provider_not_supported(monkeypatch):
    monkeypatch.setattr(
        proposals.accts_module,
        "select_email_account",
        lambda _: ({"provider": "resend", "email": "x@example.com"}, None),
    )
    valid, msg = proposals._validate_entity("thread", "t1", None)
    assert not valid
    assert "not supported" in msg


def test_validate_entity_thread_not_found(monkeypatch):
    monkeypatch.setattr(
        proposals.accts_module,
        "select_email_account",
        lambda _: ({"provider": "gmail", "email": "x@example.com"}, None),
    )
    monkeypatch.setattr(proposals.gmail, "fetch_thread_messages", lambda *_: [])
    valid, msg = proposals._validate_entity("thread", "t1", None)
    assert not valid
    assert "not found" in msg


def test_validate_entity_thread_success_and_exception(monkeypatch):
    monkeypatch.setattr(
        proposals.accts_module,
        "select_email_account",
        lambda _: ({"provider": "outlook", "email": "x@example.com"}, None),
    )
    monkeypatch.setattr(proposals.outlook, "fetch_thread_messages", lambda *_: [{"id": "m1"}])
    valid, _ = proposals._validate_entity("thread", "t1", None)
    assert valid

    def boom(*_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(proposals.outlook, "fetch_thread_messages", boom)
    valid, msg = proposals._validate_entity("thread", "t1", None)
    assert not valid
    assert "Failed to validate thread" in msg


def test_validate_entity_draft(monkeypatch):
    monkeypatch.setattr("comms.drafts.get_draft", lambda _: None)
    valid, msg = proposals._validate_entity("draft", "d1", None)
    assert not valid
    assert msg == "Draft d1 not found"
    monkeypatch.setattr("comms.drafts.get_draft", lambda _: object())
    valid, _ = proposals._validate_entity("draft", "d1", None)
    assert valid


def test_validate_entity_signal(monkeypatch):
    monkeypatch.setattr(proposals.signal, "get_message", lambda _: None)
    valid, msg = proposals._validate_entity("signal_message", "s1", None)
    assert not valid
    assert msg == "Signal message s1 not found"
    monkeypatch.setattr(proposals.signal, "get_message", lambda _: {"id": "s1"})
    valid, _ = proposals._validate_entity("signal_message", "s1", None)
    assert valid


def test_validate_entity_unknown():
    valid, msg = proposals._validate_entity("wat", "x", None)
    assert not valid
    assert "Unknown entity_type" in msg


def test_create_proposal_validation_failures(monkeypatch):
    monkeypatch.setattr(proposals, "_validate_action", lambda *_: (False, "bad action"))
    pid, msg, auto = proposals.create_proposal("thread", "t1", "archive")
    assert pid is None and msg == "bad action" and not auto

    monkeypatch.setattr(proposals, "_validate_action", lambda *_: (True, ""))
    monkeypatch.setattr(proposals, "_validate_entity", lambda *_: (False, "bad entity"))
    pid, msg, auto = proposals.create_proposal("thread", "t1", "archive")
    assert pid is None and msg == "bad entity" and not auto


def test_create_proposal_auto_and_pending(initialized_db, monkeypatch):
    monkeypatch.setattr(proposals, "_validate_action", lambda *_: (True, ""))
    monkeypatch.setattr(proposals, "_validate_entity", lambda *_: (True, ""))
    logs = []
    monkeypatch.setattr(
        proposals.audit,
        "log_decision",
        lambda **kwargs: logs.append(kwargs),
    )
    monkeypatch.setattr("comms.learning.should_auto_approve", lambda _a: True)
    pid, msg, auto = proposals.create_proposal("thread", "t1", "archive", "why")
    assert pid and msg == "" and auto
    row = proposals.get_proposal(pid)
    assert row is not None
    assert row["status"] == "approved"
    assert logs

    monkeypatch.setattr("comms.learning.should_auto_approve", lambda _a: False)
    pid2, _, auto2 = proposals.create_proposal("thread", "t2", "archive", skip_validation=True)
    assert pid2 and not auto2
    assert proposals.get_proposal(pid2)["status"] == "pending"


def test_list_proposals_and_get_approved(initialized_db, monkeypatch):
    monkeypatch.setattr(proposals, "_validate_action", lambda *_: (True, ""))
    monkeypatch.setattr(proposals, "_validate_entity", lambda *_: (True, ""))
    monkeypatch.setattr(proposals.audit, "log_decision", lambda **_kwargs: None)
    monkeypatch.setattr("comms.learning.should_auto_approve", lambda _a: False)
    pid_pending, _, _ = proposals.create_proposal("thread", "t1", "archive")
    monkeypatch.setattr("comms.learning.should_auto_approve", lambda _a: True)
    pid_approved, _, _ = proposals.create_proposal("thread", "t2", "archive")
    assert any(p["id"] == pid_pending for p in proposals.list_proposals("pending"))
    assert any(p["id"] == pid_approved for p in proposals.get_approved_proposals())


def test_resolve_proposal_id(initialized_db):
    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO proposals (id, entity_type, entity_id, proposed_action, proposed_at, status)
            VALUES ('abc11111', 'thread', 't1', 'archive', '2026-01-01T00:00:00', 'pending')
            """
        )
    assert proposals._resolve_proposal_id("abc") == "abc11111"

    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO proposals (id, entity_type, entity_id, proposed_action, proposed_at, status)
            VALUES ('abc22222', 'thread', 't2', 'archive', '2026-01-02T00:00:00', 'pending')
            """
        )
    assert proposals._resolve_proposal_id("abc") is None


def test_approve_proposal(initialized_db, monkeypatch):
    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO proposals (id, entity_type, entity_id, proposed_action, proposed_at, status, agent_reasoning)
            VALUES ('ppp11111', 'thread', 't1', 'archive', '2026-01-01T00:00:00', 'pending', 'agent')
            """
        )
    logs = []
    monkeypatch.setattr(proposals.audit, "log_decision", lambda **kwargs: logs.append(kwargs))
    assert proposals.approve_proposal("ppp111", "ok")
    assert proposals.get_proposal("ppp11111")["status"] == "approved"
    assert logs
    assert not proposals.approve_proposal("does-not-exist")


def test_reject_proposal(initialized_db, monkeypatch):
    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO proposals (id, entity_type, entity_id, proposed_action, proposed_at, status, agent_reasoning)
            VALUES ('rrr11111', 'thread', 't1', 'archive', '2026-01-01T00:00:00', 'pending', 'agent')
            """
        )
    logs = []
    monkeypatch.setattr(proposals.audit, "log_decision", lambda **kwargs: logs.append(kwargs))
    assert proposals.reject_proposal("rrr11111", "no", correction="do-x")
    assert proposals.get_proposal("rrr11111")["status"] == "rejected"
    assert logs[0]["user_decision"] == "rejected_with_correction"
    assert not proposals.reject_proposal("missing")


def test_mark_executed(initialized_db, monkeypatch):
    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO proposals (id, entity_type, entity_id, proposed_action, proposed_at, status)
            VALUES ('eee11111', 'thread', 't1', 'archive', '2026-01-01T00:00:00', 'approved')
            """
        )
    logs = []
    monkeypatch.setattr(proposals.audit, "log", lambda **kwargs: logs.append(kwargs))
    assert proposals.mark_executed("eee11111")
    assert proposals.get_proposal("eee11111")["status"] == "executed"
    assert logs


def test_mark_executed_without_existing_proposal(monkeypatch):
    @contextmanager
    def fake_db():
        class Conn:
            def execute(self, *_args, **_kwargs):
                return None

        yield Conn()

    monkeypatch.setattr(proposals, "get_db", fake_db)
    monkeypatch.setattr(proposals, "get_proposal", lambda _pid: None)
    called = []
    monkeypatch.setattr(proposals.audit, "log", lambda **_kwargs: called.append(True))
    assert proposals.mark_executed("none")
    assert not called
