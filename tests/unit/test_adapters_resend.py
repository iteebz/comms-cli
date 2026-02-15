from unittest.mock import patch

from comms.adapters.email import resend


@patch("comms.adapters.email.resend.keyring")
def test_is_configured_no_key(mock_keyring):
    mock_keyring.get_password.return_value = None
    assert not resend.is_configured()


@patch("comms.adapters.email.resend.keyring")
def test_is_configured_with_key(mock_keyring):
    mock_keyring.get_password.return_value = "test_key"
    assert resend.is_configured()


@patch("comms.adapters.email.resend._get_api_key", return_value="test_key")
@patch("httpx.post")
def test_send_message_success(mock_post, mock_key):
    from comms.models import Draft

    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"id": "msg_123"}

    draft = Draft(
        id="d_1",
        thread_id=None,
        message_id=None,
        to_addr="to@example.com",
        cc_addr=None,
        subject="Test",
        body="Test body",
        claude_reasoning=None,
        from_account_id="acc_1",
        from_addr="from@spacebrr.com",
        created_at=0,
        sent_at=None,
        approved_at=None,
    )

    result = resend.send_message("acc_1", "from@spacebrr.com", draft)
    assert result is True

    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert call_args[0][0] == "https://api.resend.com/emails"
    assert call_args[1]["json"]["from"] == "from@spacebrr.com"
    assert call_args[1]["json"]["to"] == ["to@example.com"]
    assert call_args[1]["json"]["subject"] == "Test"


@patch("comms.adapters.email.resend._get_api_key", return_value="test_key")
@patch("httpx.post")
def test_send_message_no_subject(mock_post, mock_key):
    from comms.models import Draft

    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"id": "msg_123"}

    draft = Draft(
        id="d_1",
        thread_id=None,
        message_id=None,
        to_addr="to@example.com",
        cc_addr=None,
        subject=None,
        body="Test body",
        claude_reasoning=None,
        from_account_id="acc_1",
        from_addr="from@spacebrr.com",
        created_at=0,
        sent_at=None,
        approved_at=None,
    )

    result = resend.send_message("acc_1", "from@spacebrr.com", draft)
    assert result is True

    call_args = mock_post.call_args
    assert call_args[1]["json"]["subject"] == "(no subject)"


@patch("comms.adapters.email.resend._get_api_key", return_value=None)
def test_send_message_no_api_key(mock_key):
    from comms.models import Draft

    draft = Draft(
        id="d_1",
        thread_id=None,
        message_id=None,
        to_addr="to@example.com",
        cc_addr=None,
        subject="Test",
        body="Test body",
        claude_reasoning=None,
        from_account_id="acc_1",
        from_addr="from@spacebrr.com",
        created_at=0,
        sent_at=None,
        approved_at=None,
    )

    result = resend.send_message("acc_1", "from@spacebrr.com", draft)
    assert result is False


@patch("comms.adapters.email.resend._get_api_key", return_value="test_key")
@patch("httpx.post")
def test_send_message_api_error(mock_post, mock_key):
    from comms.models import Draft

    mock_post.return_value.status_code = 400
    mock_post.return_value.text = "Bad request"

    draft = Draft(
        id="d_1",
        thread_id=None,
        message_id=None,
        to_addr="to@example.com",
        cc_addr=None,
        subject="Test",
        body="Test body",
        claude_reasoning=None,
        from_account_id="acc_1",
        from_addr="from@spacebrr.com",
        created_at=0,
        sent_at=None,
        approved_at=None,
    )

    result = resend.send_message("acc_1", "from@spacebrr.com", draft)
    assert result is False
