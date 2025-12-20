import pytest

from comms import config as comms_config
from comms import db, drafts, policy


@pytest.fixture()
def initialized_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(comms_config, "DB_PATH", db_path)
    monkeypatch.setattr(comms_config, "BACKUP_DIR", tmp_path / "backups")
    db.init(db_path)
    return db_path


def test_draft_lifecycle(initialized_db):
    draft_id = drafts.create_draft(
        to_addr="person@example.com",
        subject="hello",
        body="body",
    )

    draft = drafts.get_draft(draft_id)
    assert draft is not None
    assert draft.approved_at is None
    assert draft.sent_at is None

    drafts.approve_draft(draft_id)
    approved = drafts.get_draft(draft_id)
    assert approved is not None
    assert approved.approved_at is not None

    drafts.mark_sent(draft_id)
    sent = drafts.get_draft(draft_id)
    assert sent is not None
    assert sent.sent_at is not None


def test_resolve_draft_id_prefix(initialized_db):
    draft_id = drafts.create_draft(
        to_addr="person@example.com",
        subject="hello",
        body="body",
    )

    resolved = drafts.resolve_draft_id(draft_id[:8])
    assert resolved == draft_id
    assert drafts.resolve_draft_id("zzzzzzzz") is None


def test_validate_send_requires_approval(initialized_db, monkeypatch):
    draft_id = drafts.create_draft(
        to_addr="person@example.com",
        subject="hello",
        body="body",
    )

    monkeypatch.setattr(
        policy,
        "get_policy",
        lambda: {
            "allowed_recipients": [],
            "allowed_domains": [],
            "require_approval": True,
            "max_daily_sends": 50,
        },
    )

    ok, errors = policy.validate_send(draft_id, "person@example.com")
    assert not ok
    assert "draft requires approval before sending" in errors


def test_validate_send_allowlist(initialized_db, monkeypatch):
    draft_id = drafts.create_draft(
        to_addr="person@example.com",
        subject="hello",
        body="body",
    )

    monkeypatch.setattr(
        policy,
        "get_policy",
        lambda: {
            "allowed_recipients": ["allowed@example.com"],
            "allowed_domains": [],
            "require_approval": False,
            "max_daily_sends": 50,
        },
    )

    ok, errors = policy.validate_send(draft_id, "person@example.com")
    assert not ok
    assert "recipient 'person@example.com' not in allowlist" in errors


def test_validate_send_daily_limit(initialized_db, monkeypatch):
    sent_id = drafts.create_draft(
        to_addr="person@example.com",
        subject="hello",
        body="body",
    )
    drafts.mark_sent(sent_id)

    draft_id = drafts.create_draft(
        to_addr="person@example.com",
        subject="hello",
        body="body",
    )

    monkeypatch.setattr(
        policy,
        "get_policy",
        lambda: {
            "allowed_recipients": [],
            "allowed_domains": [],
            "require_approval": False,
            "max_daily_sends": 1,
        },
    )

    ok, errors = policy.validate_send(draft_id, "person@example.com")
    assert not ok
    assert errors and errors[0].startswith("daily send limit reached")
