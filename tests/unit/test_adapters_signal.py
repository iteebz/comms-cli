from unittest.mock import MagicMock, patch

from comms.adapters.messaging import signal


@patch("subprocess.run")
def test_list_accounts_empty(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="")
    accounts = signal.list_accounts()
    assert accounts == []


@patch("subprocess.run")
def test_list_accounts_success(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0, stdout="Number: +1234567890\nNumber: +9876543210\n"
    )
    accounts = signal.list_accounts()
    assert accounts == ["+1234567890", "+9876543210"]


@patch("subprocess.run")
def test_list_accounts_failure(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stdout="")
    accounts = signal.list_accounts()
    assert accounts == []


@patch("comms.adapters.messaging.signal.list_accounts")
def test_is_registered_true(mock_list):
    mock_list.return_value = ["+1234567890"]
    assert signal.is_registered("+1234567890") is True


@patch("comms.adapters.messaging.signal.list_accounts")
def test_is_registered_false(mock_list):
    mock_list.return_value = ["+1234567890"]
    assert signal.is_registered("+9999999999") is False


@patch("subprocess.run")
def test_register_success(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    success, msg = signal.register("+1234567890")
    assert success is True
    assert "Verification code sent" in msg


@patch("subprocess.run")
def test_register_failure(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stderr="Invalid number")
    success, msg = signal.register("+1234567890")
    assert success is False
    assert "Invalid number" in msg


@patch("subprocess.run")
def test_verify_success(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    success, msg = signal.verify("+1234567890", "123456")
    assert success is True
    assert "Verified successfully" in msg


@patch("subprocess.run")
def test_verify_failure(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stderr="Invalid code")
    success, msg = signal.verify("+1234567890", "000000")
    assert success is False
    assert "Invalid code" in msg


@patch("subprocess.run")
def test_send_success(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    success, msg = signal.send("+1234567890", "+9999999999", "test message")
    assert success is True
    assert msg == "Sent"
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert "-m" in args
    assert "test message" in args


@patch("subprocess.run")
def test_send_failure(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stderr="Network error")
    success, msg = signal.send("+1234567890", "+9999999999", "test")
    assert success is False
    assert "Network error" in msg


@patch("subprocess.run")
def test_send_group_success(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    success, msg = signal.send_group("+1234567890", "group123", "hello group")
    assert success is True
    assert "Sent to group" in msg


@patch("subprocess.run")
def test_receive_no_messages(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    messages = signal.receive("+1234567890", timeout=1, store=False)
    assert messages == []


@patch("subprocess.run")
@patch("comms.adapters.messaging.signal._store_messages")
def test_receive_valid_message(mock_store, mock_run):
    output = """
Envelope from: "Alice" +1111111111
Timestamp: 1234567890
Body: Hello world
"""
    mock_run.return_value = MagicMock(returncode=0, stdout=output, stderr="")
    messages = signal.receive("+1234567890", timeout=1, store=True)
    assert len(messages) == 1
    assert messages[0]["from"] == "+1111111111"
    assert messages[0]["from_name"] == "Alice"
    assert messages[0]["body"] == "Hello world"
    assert messages[0]["timestamp"] == 1234567890
    mock_store.assert_called_once()


@patch("subprocess.run")
def test_receive_multiple_messages(mock_run):
    output = """
Envelope from: "Alice" +1111111111
Timestamp: 1234567890
Body: First message

Envelope from: "Bob" +2222222222
Timestamp: 1234567891
Body: Second message
"""
    mock_run.return_value = MagicMock(returncode=0, stdout=output, stderr="")
    messages = signal.receive("+1234567890", timeout=1, store=False)
    assert len(messages) == 2
    assert messages[0]["from"] == "+1111111111"
    assert messages[1]["from"] == "+2222222222"


@patch("subprocess.run")
def test_receive_timeout(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
    messages = signal.receive("+1234567890", timeout=1, store=False)
    assert messages == []


@patch("comms.adapters.messaging.signal._run")
def test_list_groups_success(mock_run):
    mock_run.return_value = [{"id": "group1", "name": "Test Group"}]
    groups = signal.list_groups("+1234567890")
    assert len(groups) == 1
    assert groups[0]["id"] == "group1"


@patch("comms.adapters.messaging.signal._run")
def test_list_groups_empty(mock_run):
    mock_run.return_value = []
    groups = signal.list_groups("+1234567890")
    assert groups == []


@patch("comms.adapters.messaging.signal._run")
def test_list_contacts_success(mock_run):
    mock_run.return_value = [
        {"number": "+1111111111", "name": "Alice"},
        {"number": "+2222222222", "name": "Bob"},
    ]
    contacts = signal.list_contacts("+1234567890")
    assert len(contacts) == 2
    assert contacts[0]["number"] == "+1111111111"


@patch("comms.adapters.messaging.signal._run")
def test_list_contacts_filters_empty_numbers(mock_run):
    mock_run.return_value = [
        {"number": "+1111111111", "name": "Alice"},
        {"number": "", "name": "NoNumber"},
    ]
    contacts = signal.list_contacts("+1234567890")
    assert len(contacts) == 1


@patch("comms.adapters.messaging.signal.is_registered")
@patch("comms.adapters.messaging.signal._run")
def test_test_connection_success(mock_run, mock_registered):
    mock_registered.return_value = True
    mock_run.return_value = {"status": "ok"}
    success, msg = signal.test_connection("+1234567890")
    assert success is True
    assert "Connected" in msg


@patch("comms.adapters.messaging.signal.is_registered")
def test_test_connection_not_registered(mock_registered):
    mock_registered.return_value = False
    success, msg = signal.test_connection("+1234567890")
    assert success is False
    assert "not registered" in msg


@patch("comms.adapters.messaging.signal.is_registered")
@patch("comms.adapters.messaging.signal._run")
def test_test_connection_failure(mock_run, mock_registered):
    mock_registered.return_value = True
    mock_run.return_value = None
    success, msg = signal.test_connection("+1234567890")
    assert success is False
    assert "Failed" in msg


@patch("comms.adapters.messaging.signal.get_message")
@patch("comms.adapters.messaging.signal.send")
@patch("comms.adapters.messaging.signal.mark_read")
def test_reply_success(mock_mark, mock_send, mock_get):
    mock_get.return_value = {"id": "msg123", "sender_phone": "+1111111111"}
    mock_send.return_value = (True, "Sent")
    success, result, msg = signal.reply("+1234567890", "msg123", "reply text")
    assert success is True
    mock_send.assert_called_once_with("+1234567890", "+1111111111", "reply text")
    mock_mark.assert_called_once_with("msg123")


@patch("comms.adapters.messaging.signal.get_message")
def test_reply_message_not_found(mock_get):
    mock_get.return_value = None
    success, result, msg = signal.reply("+1234567890", "invalid", "reply")
    assert success is False
    assert "not found" in result
