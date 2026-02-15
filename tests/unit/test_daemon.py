import signal
from unittest.mock import patch

import pytest

from comms import daemon


@pytest.fixture
def temp_daemon(tmp_path, monkeypatch):
    pid_file = tmp_path / "daemon.pid"
    log_file = tmp_path / "daemon.log"
    monkeypatch.setattr(daemon, "PID_FILE", pid_file)
    monkeypatch.setattr(daemon, "LOG_FILE", log_file)
    return {"pid_file": pid_file, "log_file": log_file}


@pytest.mark.parametrize(
    "file_content,expected",
    [
        (None, None),
        ("12345", 12345),
        ("not_a_number", None),
    ],
)
def test_get_pid(temp_daemon, file_content, expected):
    if file_content is not None:
        temp_daemon["pid_file"].write_text(file_content)
    assert daemon.get_pid() == expected


def test_is_running_no_pid(temp_daemon):
    assert daemon.is_running() is False


@patch("os.kill")
def test_is_running_alive(mock_kill, temp_daemon):
    temp_daemon["pid_file"].write_text("12345")
    mock_kill.return_value = None
    assert daemon.is_running() is True
    mock_kill.assert_called_once_with(12345, 0)


@patch("os.kill")
def test_is_running_dead(mock_kill, temp_daemon):
    temp_daemon["pid_file"].write_text("12345")
    mock_kill.side_effect = ProcessLookupError()
    assert daemon.is_running() is False
    assert not temp_daemon["pid_file"].exists()


@patch("comms.daemon._get_signal_phones")
def test_start_no_accounts(mock_phones, temp_daemon):
    mock_phones.return_value = []
    success, msg = daemon.start()
    assert success is False
    assert "No Signal accounts" in msg


@patch("comms.daemon._get_signal_phones")
@patch("os.fork")
def test_start_already_running(mock_fork, mock_phones, temp_daemon):
    mock_phones.return_value = ["+1234567890"]
    temp_daemon["pid_file"].write_text("99999")
    with patch("comms.daemon.is_running", return_value=True):
        success, msg = daemon.start()
    assert success is False
    assert "Already running" in msg


@patch("comms.daemon._get_signal_phones")
@patch("comms.daemon.run")
def test_start_foreground(mock_run, mock_phones, temp_daemon):
    mock_phones.return_value = ["+1234567890"]
    success, msg = daemon.start(foreground=True)
    assert success is True
    mock_run.assert_called_once_with(5)


@patch("comms.daemon._get_signal_phones")
@patch("os.fork")
@patch("time.sleep")
def test_start_background_success(mock_sleep, mock_fork, mock_phones, temp_daemon):
    mock_phones.return_value = ["+1234567890"]
    mock_fork.return_value = 12345
    temp_daemon["pid_file"].write_text("12345")
    with patch("comms.daemon.is_running", side_effect=[False, True]):
        success, msg = daemon.start()
    assert success is True
    assert "12345" in msg


def test_stop_not_running(temp_daemon):
    success, msg = daemon.stop()
    assert success is False
    assert "Not running" in msg


@patch("os.kill")
@patch("comms.daemon.is_running")
@patch("time.sleep")
def test_stop_graceful(mock_sleep, mock_is_running, mock_kill, temp_daemon):
    temp_daemon["pid_file"].write_text("12345")
    mock_is_running.side_effect = [True, False]
    success, msg = daemon.stop()
    assert success is True
    assert "Stopped" in msg
    mock_kill.assert_called_once_with(12345, signal.SIGTERM)


@patch("os.kill")
@patch("comms.daemon.is_running")
@patch("time.sleep")
def test_stop_force_kill(mock_sleep, mock_is_running, mock_kill, temp_daemon):
    temp_daemon["pid_file"].write_text("12345")
    mock_is_running.return_value = True
    success, msg = daemon.stop()
    assert success is True
    assert "Killed" in msg
    assert mock_kill.call_count == 2


@patch("os.kill")
def test_stop_already_dead(mock_kill, temp_daemon):
    temp_daemon["pid_file"].write_text("12345")
    mock_kill.side_effect = ProcessLookupError()
    success, msg = daemon.stop()
    assert success is True
    assert "Was not running" in msg
    assert not temp_daemon["pid_file"].exists()


@patch("comms.daemon._get_signal_phones")
def test_status_not_running(mock_phones, temp_daemon):
    mock_phones.return_value = ["+1234567890"]
    result = daemon.status()
    assert result["running"] is False
    assert result["pid"] is None
    assert result["accounts"] == ["+1234567890"]


@patch("comms.daemon._get_signal_phones")
@patch("comms.daemon.is_running")
def test_status_running(mock_is_running, mock_phones, temp_daemon):
    mock_phones.return_value = ["+1234567890"]
    mock_is_running.return_value = True
    temp_daemon["pid_file"].write_text("12345")
    temp_daemon["log_file"].write_text("line1\nline2\nline3\nline4\nline5\nline6")
    result = daemon.status()
    assert result["running"] is True
    assert result["pid"] == 12345
    assert len(result["last_log"]) == 5


@patch("comms.adapters.messaging.signal.receive")
@patch("comms.agent.handle_incoming")
@patch("comms.adapters.messaging.signal.send")
@patch("comms.config.get_agent_config")
def test_poll_once_agent_disabled(mock_config, mock_send, mock_handle, mock_receive, temp_daemon):
    mock_config.return_value = {"enabled": False}
    mock_receive.return_value = [{"body": "test", "sender_phone": "+9999999999"}]
    count = daemon._poll_once(["+1234567890"], timeout=1)
    assert count == 1
    mock_handle.assert_not_called()


@patch("comms.adapters.messaging.signal.receive")
@patch("comms.agent.handle_incoming")
@patch("comms.adapters.messaging.signal.send")
@patch("comms.config.get_agent_config")
def test_poll_once_agent_responds(mock_config, mock_send, mock_handle, mock_receive, temp_daemon):
    mock_config.return_value = {"enabled": True, "nlp": False}
    mock_receive.return_value = [{"body": "!ping", "sender_phone": "+9999999999"}]
    mock_handle.return_value = "pong"
    count = daemon._poll_once(["+1234567890"], timeout=1)
    assert count == 1
    mock_handle.assert_called_once()
    mock_send.assert_called_once_with("+1234567890", "+9999999999", "pong")


@patch("comms.adapters.messaging.signal.receive")
@patch("comms.config.get_agent_config")
def test_poll_once_error_logged(mock_config, mock_receive, temp_daemon):
    mock_config.return_value = {"enabled": False}
    mock_receive.side_effect = Exception("timeout")
    count = daemon._poll_once(["+1234567890"], timeout=1)
    assert count == 0
    log_content = temp_daemon["log_file"].read_text()
    assert "Error: timeout" in log_content


@patch("comms.accounts.list_accounts")
def test_get_signal_phones(mock_list):
    mock_list.return_value = [
        {"email": "+1234567890", "provider": "signal"},
        {"email": "user@gmail.com", "provider": "gmail"},
    ]
    phones = daemon._get_signal_phones()
    assert phones == ["+1234567890"]
