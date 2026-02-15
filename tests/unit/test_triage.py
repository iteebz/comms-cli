import json
from unittest.mock import MagicMock, patch

import pytest

from comms import triage
from comms.services import InboxItem


@pytest.fixture
def sample_items():
    return [
        InboxItem(
            item_id="abc12345",
            source="email",
            source_id="thread1",
            sender="newsletter@example.com",
            subject="Weekly Newsletter",
            preview="This week's top stories...",
            unread=True,
            timestamp=1234567890,
        ),
        InboxItem(
            item_id="def67890",
            source="email",
            source_id="thread2",
            sender="urgent@example.com",
            subject="URGENT: Action required",
            preview="Please respond immediately...",
            unread=True,
            timestamp=1234567891,
        ),
    ]


@patch("comms.triage.RULES_PATH")
def test_load_rules_empty(mock_path, tmp_path):
    mock_path.exists.return_value = False
    rules = triage._load_rules()
    assert rules == ""


@patch("comms.triage.RULES_PATH")
def test_load_rules_exists(mock_path, tmp_path):
    rules_file = tmp_path / "rules.txt"
    rules_file.write_text("archive newsletters")
    mock_path.exists.return_value = True
    mock_path.read_text.return_value = "archive newsletters"
    rules = triage._load_rules()
    assert rules == "archive newsletters"


def test_build_prompt_format(sample_items):
    prompt = triage._build_prompt(sample_items, "test rules")
    assert "test rules" in prompt
    assert "archive" in prompt
    assert "delete" in prompt
    assert "flag" in prompt
    assert "abc123" in prompt
    assert "def678" in prompt


def test_parse_response_valid_json(sample_items):
    output = json.dumps(
        [
            {"id": "abc12345", "action": "archive", "reasoning": "Newsletter", "confidence": 0.9},
            {"id": "def67890", "action": "flag", "reasoning": "Urgent", "confidence": 0.95},
        ]
    )
    proposals = triage._parse_response(output, sample_items)
    assert len(proposals) == 2
    assert proposals[0].action == "archive"
    assert proposals[0].confidence == 0.9
    assert proposals[1].action == "flag"


def test_parse_response_markdown_wrapped(sample_items):
    output = (
        "```json\n"
        + json.dumps(
            [{"id": "abc12345", "action": "archive", "reasoning": "test", "confidence": 0.8}]
        )
        + "\n```"
    )
    proposals = triage._parse_response(output, sample_items)
    assert len(proposals) == 1


def test_parse_response_invalid_json(sample_items):
    proposals = triage._parse_response("not json", sample_items)
    assert proposals == []


def test_parse_response_unknown_id(sample_items):
    output = json.dumps(
        [{"id": "unknown", "action": "archive", "reasoning": "test", "confidence": 0.8}]
    )
    proposals = triage._parse_response(output, sample_items)
    assert proposals == []


def test_apply_patterns_skips_signal():
    items = [
        InboxItem(
            item_id="signal1",
            source="signal",
            source_id="msg1",
            sender="+1234567890",
            subject="",
            preview="Signal message",
            unread=True,
            timestamp=1234567890,
        ),
    ]
    pattern_proposals, remaining = triage._apply_patterns(items)
    assert len(pattern_proposals) == 0
    assert len(remaining) == 1


@patch("comms.triage.should_skip_triage")
@patch("comms.triage.detect_urgency")
def test_apply_patterns_auto_archive(mock_urgency, mock_skip, sample_items):
    mock_skip.return_value = MagicMock(
        action="archive", reason="newsletter pattern", confidence=0.85
    )
    mock_urgency.return_value = (0.3, "low urgency")

    pattern_proposals, remaining = triage._apply_patterns(sample_items[:1])
    assert len(pattern_proposals) == 1
    assert pattern_proposals[0].action == "archive"
    assert "newsletter pattern" in pattern_proposals[0].reasoning


@patch("comms.triage.should_skip_triage")
@patch("comms.triage.detect_urgency")
def test_apply_patterns_urgent_override(mock_urgency, mock_skip, sample_items):
    mock_skip.return_value = MagicMock(
        action="archive", reason="newsletter pattern", confidence=0.85
    )
    mock_urgency.return_value = (0.7, "urgent keywords")

    pattern_proposals, remaining = triage._apply_patterns(sample_items[:1])
    assert len(pattern_proposals) == 1
    assert pattern_proposals[0].action == "flag"
    assert "urgent keywords" in pattern_proposals[0].reasoning


@patch("comms.triage.get_unified_inbox")
def test_triage_inbox_empty(mock_inbox):
    mock_inbox.return_value = []
    proposals = triage.triage_inbox()
    assert proposals == []


@patch("comms.triage.subprocess.run")
@patch("comms.triage._load_rules", return_value="")
@patch("comms.triage._build_prompt", return_value="prompt")
@patch("comms.triage._apply_patterns")
@patch("comms.triage.is_snoozed", return_value=False)
@patch("comms.triage.mark_resurfaced")
@patch("comms.triage.get_due_snoozes", return_value=[])
@patch("comms.triage.get_unified_inbox")
def test_triage_inbox_returns_pattern_proposals_on_subprocess_failure(
    mock_inbox,
    _mock_due,
    _mock_resurfaced,
    _mock_is_snoozed,
    mock_apply_patterns,
    _mock_build_prompt,
    _mock_load_rules,
    mock_run,
):
    item = InboxItem("id1", "email", "t1", "sender@x.com", "subj", "prev", True, 123)
    expected = triage.TriageProposal(item=item, action="archive", reasoning="auto", confidence=0.9)
    mock_inbox.return_value = [item]
    mock_apply_patterns.return_value = ([expected], [item])
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")

    proposals = triage.triage_inbox()

    assert proposals == [expected]


@patch("comms.triage.subprocess.run")
@patch("comms.triage._load_rules", return_value="")
@patch("comms.triage._build_prompt", return_value="prompt")
@patch("comms.triage._parse_response")
@patch("comms.triage.detect_urgency")
@patch("comms.triage._apply_patterns")
@patch("comms.triage.is_snoozed", return_value=False)
@patch("comms.triage.mark_resurfaced")
@patch("comms.triage.get_due_snoozes", return_value=[])
@patch("comms.triage.get_unified_inbox")
def test_triage_inbox_appends_urgency_note_for_non_flag_actions(
    mock_inbox,
    _mock_due,
    _mock_resurfaced,
    _mock_is_snoozed,
    mock_apply_patterns,
    mock_detect_urgency,
    mock_parse_response,
    _mock_build_prompt,
    _mock_load_rules,
    mock_run,
):
    item = InboxItem("id1", "email", "t1", "sender@x.com", "subj", "prev", True, 123)
    proposal = triage.TriageProposal(item=item, action="archive", reasoning="base", confidence=0.8)
    mock_inbox.return_value = [item]
    mock_apply_patterns.return_value = ([], [item])
    mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
    mock_parse_response.return_value = [proposal]
    mock_detect_urgency.return_value = (0.8, "urgent keywords")

    proposals = triage.triage_inbox()

    assert len(proposals) == 1
    assert "[urgent: urgent keywords]" in proposals[0].reasoning


@patch("comms.proposals.create_proposal")
def test_create_proposals_min_confidence(mock_create):
    mock_create.return_value = ("prop123", None, False)
    proposals_list = [
        triage.TriageProposal(
            item=InboxItem("id1", "email", "t1", "sender@x.com", "subj", "prev", True, 123),
            action="archive",
            reasoning="test",
            confidence=0.5,
        ),
        triage.TriageProposal(
            item=InboxItem("id2", "email", "t2", "sender@x.com", "subj", "prev", True, 123),
            action="archive",
            reasoning="test",
            confidence=0.9,
        ),
    ]
    created = triage.create_proposals_from_triage(proposals_list, min_confidence=0.7)
    assert len(created) == 1


def test_create_proposals_dry_run():
    proposals_list = [
        triage.TriageProposal(
            item=InboxItem("id1", "email", "t1", "sender@x.com", "subj", "prev", True, 123),
            action="archive",
            reasoning="test",
            confidence=0.9,
        ),
    ]
    created = triage.create_proposals_from_triage(proposals_list, dry_run=True)
    assert len(created) == 1
    assert created[0][0] == "dry-run"
