from unittest.mock import MagicMock, Mock, patch

import pytest

from comms.adapters.email import gmail


@pytest.fixture
def mock_creds():
    creds = Mock()
    creds.valid = True
    creds.expired = False
    creds.refresh_token = None
    return creds


@pytest.fixture
def mock_service():
    return MagicMock()


@patch("comms.adapters.email.gmail._get_token")
@patch("comms.adapters.email.gmail.Credentials.from_authorized_user_info")
def test_get_credentials_cached_valid(mock_from_info, mock_get_token, mock_creds):
    mock_get_token.return_value = {"token": "abc123"}
    mock_from_info.return_value = mock_creds
    creds, email = gmail._get_credentials("test@example.com")
    assert creds == mock_creds
    assert email == "test@example.com"


@patch("comms.adapters.email.gmail._get_token")
@patch("comms.adapters.email.gmail.Credentials.from_authorized_user_info")
@patch("comms.adapters.email.gmail._set_token")
def test_get_credentials_refresh_expired(mock_set, mock_from_info, mock_get_token):
    mock_get_token.return_value = {"token": "abc123", "refresh_token": "refresh"}
    expired_creds = Mock()
    expired_creds.valid = False
    expired_creds.expired = True
    expired_creds.refresh_token = "refresh"
    expired_creds.to_json.return_value = '{"token": "new"}'
    mock_from_info.return_value = expired_creds
    creds, email = gmail._get_credentials("test@example.com")
    expired_creds.refresh.assert_called_once()
    mock_set.assert_called_once()


@patch("comms.adapters.email.gmail._get_credentials")
@patch("comms.adapters.email.gmail.build")
def test_test_connection_success(mock_build, mock_get_creds, mock_creds, mock_service):
    mock_get_creds.return_value = (mock_creds, "test@example.com")
    mock_build.return_value = mock_service
    mock_service.users().getProfile().execute.return_value = {"emailAddress": "test@example.com"}
    success, msg = gmail.test_connection("acc123", "test@example.com")
    assert success is True
    assert "Connected successfully" in msg


@patch("comms.adapters.email.gmail._get_credentials")
@patch("comms.adapters.email.gmail.build")
def test_test_connection_failure(mock_build, mock_get_creds, mock_creds):
    mock_get_creds.return_value = (mock_creds, "test@example.com")
    mock_build.side_effect = Exception("Auth failed")
    success, msg = gmail.test_connection("acc123", "test@example.com")
    assert success is False
    assert "Connection failed" in msg


@patch("comms.adapters.email.gmail._get_credentials")
@patch("comms.adapters.email.gmail.build")
def test_count_inbox_threads(mock_build, mock_get_creds, mock_creds, mock_service):
    mock_get_creds.return_value = (mock_creds, "test@example.com")
    mock_build.return_value = mock_service
    mock_service.users().labels().get().execute.return_value = {"threadsTotal": 42}
    count = gmail.count_inbox_threads("test@example.com")
    assert count == 42


@patch("comms.adapters.email.gmail._get_credentials")
@patch("comms.adapters.email.gmail.build")
def test_list_threads_empty(mock_build, mock_get_creds, mock_creds, mock_service):
    mock_get_creds.return_value = (mock_creds, "test@example.com")
    mock_build.return_value = mock_service
    mock_service.users().threads().list().execute.return_value = {"threads": []}
    threads = gmail.list_threads("test@example.com")
    assert threads == []


@patch("comms.adapters.email.gmail._get_credentials")
@patch("comms.adapters.email.gmail.build")
def test_list_threads_with_results(mock_build, mock_get_creds, mock_creds, mock_service):
    mock_get_creds.return_value = (mock_creds, "test@example.com")
    mock_build.return_value = mock_service
    mock_service.users().threads().list().execute.return_value = {
        "threads": [{"id": "thread1", "snippet": "test"}]
    }
    mock_service.users().threads().get().execute.return_value = {
        "messages": [
            {
                "payload": {
                    "headers": [
                        {"name": "From", "value": "sender@example.com"},
                        {"name": "Subject", "value": "Test Subject"},
                        {"name": "Date", "value": "Mon, 1 Jan 2024"},
                    ]
                }
            }
        ]
    }
    threads = gmail.list_threads("test@example.com", max_results=10)
    assert len(threads) == 1
    assert threads[0]["id"] == "thread1"
    assert threads[0]["from"] == "sender@example.com"


@pytest.mark.parametrize(
    "operation,func",
    [
        ("archive", gmail.archive_thread),
        ("delete", gmail.delete_thread),
        ("flag", gmail.flag_thread),
        ("unflag", gmail.unflag_thread),
        ("unarchive", gmail.unarchive_thread),
        ("undelete", gmail.undelete_thread),
    ],
)
@patch("comms.adapters.email.gmail._get_credentials")
@patch("comms.adapters.email.gmail.build")
def test_thread_operations_success(
    mock_build, mock_get_creds, mock_creds, mock_service, operation, func
):
    mock_get_creds.return_value = (mock_creds, "test@example.com")
    mock_build.return_value = mock_service
    result = func("thread1", "test@example.com")
    assert result is True


@pytest.mark.parametrize(
    "operation,func",
    [
        ("archive", gmail.archive_thread),
        ("delete", gmail.delete_thread),
        ("flag", gmail.flag_thread),
        ("unflag", gmail.unflag_thread),
        ("unarchive", gmail.unarchive_thread),
        ("undelete", gmail.undelete_thread),
    ],
)
@patch("comms.adapters.email.gmail._get_credentials")
@patch("comms.adapters.email.gmail.build")
def test_thread_operations_failure(
    mock_build, mock_get_creds, mock_creds, mock_service, operation, func
):
    mock_get_creds.return_value = (mock_creds, "test@example.com")
    mock_build.return_value = mock_service
    mock_service.users().threads().modify().execute.side_effect = Exception("API error")
    mock_service.users().threads().trash().execute.side_effect = Exception("API error")
    mock_service.users().threads().untrash().execute.side_effect = Exception("API error")
    result = func("thread1", "test@example.com")
    assert result is False


@patch("comms.adapters.email.gmail._get_credentials")
@patch("comms.adapters.email.gmail.build")
def test_fetch_thread_messages(mock_build, mock_get_creds, mock_creds, mock_service):
    mock_get_creds.return_value = (mock_creds, "test@example.com")
    mock_build.return_value = mock_service
    mock_service.users().threads().get().execute.return_value = {
        "messages": [
            {
                "payload": {
                    "headers": [
                        {"name": "From", "value": "sender@example.com"},
                        {"name": "To", "value": "test@example.com"},
                        {"name": "Subject", "value": "Hello"},
                        {"name": "Date", "value": "Mon, 1 Jan 2024"},
                    ],
                    "body": {"data": "SGVsbG8gd29ybGQ="},
                }
            }
        ]
    }
    messages = gmail.fetch_thread_messages("thread1", "test@example.com")
    assert len(messages) == 1
    assert messages[0]["from"] == "sender@example.com"
    assert messages[0]["subject"] == "Hello"


@pytest.mark.parametrize(
    "encoded,expected",
    [
        ("SGVsbG8gd29ybGQ=", "Hello world"),
        (None, ""),
        ("!!!invalid!!!", ""),
    ],
)
def test_decode_body(encoded, expected):
    assert gmail._decode_body(encoded) == expected


def test_extract_body_plain_text():
    payload = {"parts": [{"mimeType": "text/plain", "body": {"data": "SGVsbG8="}}]}
    result = gmail._extract_body(payload)
    assert result == "Hello"


def test_extract_body_multipart():
    payload = {
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "parts": [{"mimeType": "text/plain", "body": {"data": "SGVsbG8="}}],
            }
        ]
    }
    result = gmail._extract_body(payload)
    assert result == "Hello"


def test_extract_body_direct():
    payload = {"body": {"data": "SGVsbG8="}}
    result = gmail._extract_body(payload)
    assert result == "Hello"


def test_headers_map_lowercase():
    headers = [
        {"name": "From", "value": "test@example.com"},
        {"name": "Subject", "value": "Test"},
    ]
    result = gmail._headers_map(headers, lower=True)
    assert result["from"] == "test@example.com"
    assert result["subject"] == "Test"


def test_headers_map_preserve_case():
    headers = [
        {"name": "From", "value": "test@example.com"},
    ]
    result = gmail._headers_map(headers, lower=False)
    assert result["From"] == "test@example.com"
