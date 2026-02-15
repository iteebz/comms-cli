from unittest.mock import MagicMock, patch

import pytest

from comms import agent


@pytest.fixture
def temp_comms_dir(tmp_path, monkeypatch):
    from comms import config

    comms_dir = tmp_path / ".comms"
    monkeypatch.setattr(config, "COMMS_DIR", comms_dir)
    monkeypatch.setattr(agent, "COMMS_DIR", comms_dir)
    monkeypatch.setattr(agent, "AUTHORIZED_FILE", comms_dir / "authorized_senders.txt")
    return comms_dir


def test_get_authorized_senders_empty(temp_comms_dir):
    senders = agent.get_authorized_senders()
    assert senders == set()


def test_add_authorized_sender(temp_comms_dir):
    agent.add_authorized_sender("+1234567890")
    senders = agent.get_authorized_senders()
    assert "+1234567890" in senders


def test_add_duplicate_sender(temp_comms_dir):
    agent.add_authorized_sender("+1234567890")
    agent.add_authorized_sender("+1234567890")
    senders = agent.get_authorized_senders()
    assert len(senders) == 1


def test_remove_authorized_sender(temp_comms_dir):
    agent.add_authorized_sender("+1234567890")
    removed = agent.remove_authorized_sender("+1234567890")
    assert removed is True
    senders = agent.get_authorized_senders()
    assert "+1234567890" not in senders


def test_remove_nonexistent_sender(temp_comms_dir):
    removed = agent.remove_authorized_sender("+9999999999")
    assert removed is False


def test_is_command_exclamation():
    assert agent.is_command("!inbox") is True
    assert agent.is_command("! status") is True


def test_is_command_prefix():
    assert agent.is_command("comms inbox") is True
    assert agent.is_command("COMMS status") is True


def test_is_command_not():
    assert agent.is_command("just a message") is False
    assert agent.is_command("") is False


def test_parse_command_exclamation():
    cmd = agent.parse_command("!inbox")
    assert cmd is not None
    assert cmd.action == "inbox"
    assert cmd.args == []


def test_parse_command_with_args():
    cmd = agent.parse_command("!archive thread123")
    assert cmd is not None
    assert cmd.action == "archive"
    assert cmd.args == ["thread123"]


def test_parse_command_prefix():
    cmd = agent.parse_command("comms status")
    assert cmd is not None
    assert cmd.action == "status"


def test_parse_command_invalid():
    cmd = agent.parse_command("not a command")
    assert cmd is None


def test_parse_command_empty():
    cmd = agent.parse_command("!")
    assert cmd is None


def test_execute_command_help():
    cmd = agent.Command(action="help", args=[], raw="help")
    result = agent.execute_command(cmd)
    assert result.success is True
    assert "inbox" in result.message


def test_execute_command_ping():
    cmd = agent.Command(action="ping", args=[], raw="ping")
    result = agent.execute_command(cmd)
    assert result.success is True
    assert result.message == "pong"


def test_execute_command_unknown():
    cmd = agent.Command(action="unknown", args=[], raw="unknown")
    result = agent.execute_command(cmd)
    assert result.success is False
    assert "Unknown command" in result.message


@patch("comms.agent._run_comms_command")
def test_execute_command_mapped(mock_run):
    mock_run.return_value = (True, "inbox output")
    cmd = agent.Command(action="inbox", args=[], raw="inbox")
    result = agent.execute_command(cmd)
    assert result.success is True
    assert result.message == "inbox output"
    mock_run.assert_called_once_with("comms inbox -n 5")


@patch("comms.agent._run_comms_command")
def test_execute_command_archive_with_id(mock_run):
    mock_run.return_value = (True, "")
    cmd = agent.Command(action="archive", args=["thread123"], raw="archive thread123")
    result = agent.execute_command(cmd)
    assert result.success is True
    assert "thread123" in result.message


@patch("comms.agent._run_comms_command")
def test_execute_command_draft_reply(mock_run):
    mock_run.return_value = (True, "draft created")
    cmd = agent.Command(action="draft", args=["thread456"], raw="draft thread456")
    result = agent.execute_command(cmd)
    assert result.success is True
    assert result.executed == "draft-reply thread456"


def test_process_message_unauthorized(temp_comms_dir):
    agent.add_authorized_sender("+1111111111")
    result = agent.process_message("+9999999999", "+9999999999", "!inbox")
    assert result is None


def test_process_message_authorized(temp_comms_dir):
    agent.add_authorized_sender("+1234567890")
    result = agent.process_message("+1234567890", "+1234567890", "!ping")
    assert result is not None
    assert result.message == "pong"


def test_process_message_no_allowlist(temp_comms_dir):
    result = agent.process_message("+1234567890", "+1234567890", "!ping")
    assert result is not None


def test_process_message_not_command(temp_comms_dir):
    result = agent.process_message("+1234567890", "+1234567890", "just a message")
    assert result is None


@patch("comms.agent.process_message")
def test_handle_incoming(mock_process):
    mock_process.return_value = agent.CommandResult(success=True, message="pong", executed="ping")
    message = {"sender_phone": "+1234567890", "body": "!ping"}
    response = agent.handle_incoming("+9999999999", message)
    assert response == "pong"


@patch("comms.agent.process_message")
def test_handle_incoming_no_result(mock_process):
    mock_process.return_value = None
    message = {"sender_phone": "+1234567890", "body": "not a command"}
    response = agent.handle_incoming("+9999999999", message)
    assert response is None


@patch("subprocess.run")
def test_parse_natural_language_success(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout='{"action": "inbox", "args": []}')
    cmd = agent.parse_natural_language("show me my inbox")
    assert cmd is not None
    assert cmd.action == "inbox"


@patch("subprocess.run")
def test_parse_natural_language_markdown_wrapped(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0, stdout='```json\n{"action": "status", "args": []}\n```'
    )
    cmd = agent.parse_natural_language("what's the status?")
    assert cmd is not None
    assert cmd.action == "status"


@patch("subprocess.run")
def test_parse_natural_language_not_command(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout='{"action": null}')
    cmd = agent.parse_natural_language("random message")
    assert cmd is None


@patch("subprocess.run")
def test_parse_natural_language_invalid_json(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="not json")
    cmd = agent.parse_natural_language("show inbox")
    assert cmd is None


@patch("subprocess.run")
def test_parse_natural_language_subprocess_error(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
    cmd = agent.parse_natural_language("show inbox")
    assert cmd is None
