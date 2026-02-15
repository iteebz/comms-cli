import json

import pytest

from comms import config as comms_config
from comms import db, learning


@pytest.fixture()
def initialized_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(comms_config, "DB_PATH", db_path)
    monkeypatch.setattr(comms_config, "BACKUP_DIR", tmp_path / "backups")
    db.init(db_path)
    return db_path


def _insert_decision(proposed_action: str, user_decision: str, metadata: dict | None = None):
    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO audit_log (action, entity_type, entity_id, metadata, proposed_action, user_decision)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "decision",
                "draft",
                "d1",
                json.dumps(metadata or {}),
                proposed_action,
                user_decision,
            ),
        )


def test_get_decision_stats_and_patterns(initialized_db):
    _insert_decision("send", "approved")
    _insert_decision("send", "approved")
    _insert_decision("send", "rejected")
    _insert_decision("send", "rejected_with_correction", {"correction": "hold"})
    _insert_decision("archive", "rejected_with_correction", {"correction": "snooze"})
    _insert_decision("archive", "rejected_with_correction", {"correction": "snooze"})

    stats = learning.get_decision_stats()
    assert stats["send"].total == 4
    assert stats["send"].approved == 2
    assert stats["send"].rejected == 1
    assert stats["send"].corrected == 1
    assert stats["send"].accuracy == 0.5
    assert stats["send"].corrections == [("send", "hold")]

    patterns = learning.get_correction_patterns()
    assert patterns == [
        {"original": "archive", "corrected": "snooze", "count": 2},
        {"original": "send", "corrected": "hold", "count": 1},
    ]


def test_suggest_auto_approve_threshold_and_samples(initialized_db):
    for _ in range(4):
        _insert_decision("send", "approved")
    _insert_decision("send", "rejected")

    for _ in range(3):
        _insert_decision("archive", "approved")

    suggestions = learning.suggest_auto_approve(threshold=0.75, min_samples=5)
    assert suggestions == ["send"]


def test_should_auto_approve_respects_policy(initialized_db, monkeypatch):
    for _ in range(5):
        _insert_decision("send", "approved")

    monkeypatch.setattr(
        comms_config,
        "get_policy",
        lambda: {
            "auto_approve": {
                "enabled": True,
                "actions": ["send"],
                "threshold": 0.8,
                "min_samples": 5,
            }
        },
    )
    assert learning.should_auto_approve("send")
    assert not learning.should_auto_approve("archive")

    monkeypatch.setattr(comms_config, "get_policy", lambda: {"auto_approve": {"enabled": False}})
    assert not learning.should_auto_approve("send")
