from unittest.mock import patch

import pytest

from comms import accounts


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    from comms import config, db

    db_path = tmp_path / "comms.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backups")
    db.init(db_path)
    return db_path


@patch("comms.accounts.config_add_account")
def test_add_email_account(mock_config, temp_db):
    account_id = accounts.add_email_account("gmail", "test@gmail.com")
    assert len(account_id) == 36
    mock_config.assert_called_once_with(
        "email", {"provider": "gmail", "email": "test@gmail.com", "id": account_id}
    )
    account = accounts.get_account_by_id(account_id)
    assert account["service_type"] == "email"
    assert account["provider"] == "gmail"
    assert account["email"] == "test@gmail.com"
    assert account["enabled"] == 1


@patch("comms.accounts.config_add_account")
def test_add_messaging_account(mock_config, temp_db):
    account_id = accounts.add_messaging_account("signal", "+1234567890")
    assert len(account_id) == 36
    mock_config.assert_called_once_with(
        "messaging", {"provider": "signal", "identifier": "+1234567890", "id": account_id}
    )
    account = accounts.get_account_by_id(account_id)
    assert account["service_type"] == "messaging"
    assert account["provider"] == "signal"
    assert account["email"] == "+1234567890"
    assert account["enabled"] == 1


def test_get_account_by_id_exists(temp_db):
    account_id = "test-uuid-123"
    from comms.db import get_db

    with get_db() as conn:
        conn.execute(
            "INSERT INTO accounts (id, service_type, provider, email, enabled) VALUES (?, ?, ?, ?, ?)",
            (account_id, "email", "gmail", "test@gmail.com", 1),
        )
    account = accounts.get_account_by_id(account_id)
    assert account["id"] == account_id
    assert account["email"] == "test@gmail.com"


def test_get_account_by_id_not_found(temp_db):
    account = accounts.get_account_by_id("nonexistent")
    assert account is None


def test_list_accounts_all(temp_db):
    from comms.db import get_db

    with get_db() as conn:
        conn.execute(
            "INSERT INTO accounts (id, service_type, provider, email, enabled) VALUES (?, ?, ?, ?, ?)",
            ("id1", "email", "gmail", "a@gmail.com", 1),
        )
        conn.execute(
            "INSERT INTO accounts (id, service_type, provider, email, enabled) VALUES (?, ?, ?, ?, ?)",
            ("id2", "messaging", "signal", "+123", 1),
        )
    result = accounts.list_accounts()
    assert len(result) == 2
    assert result[0]["service_type"] in ("email", "messaging")


def test_list_accounts_filtered(temp_db):
    from comms.db import get_db

    with get_db() as conn:
        conn.execute(
            "INSERT INTO accounts (id, service_type, provider, email, enabled) VALUES (?, ?, ?, ?, ?)",
            ("id1", "email", "gmail", "a@gmail.com", 1),
        )
        conn.execute(
            "INSERT INTO accounts (id, service_type, provider, email, enabled) VALUES (?, ?, ?, ?, ?)",
            ("id2", "messaging", "signal", "+123", 1),
        )
    result = accounts.list_accounts("email")
    assert len(result) == 1
    assert result[0]["service_type"] == "email"


def test_list_accounts_empty(temp_db):
    result = accounts.list_accounts()
    assert result == []


def test_select_email_account_no_accounts(temp_db):
    account, error = accounts.select_email_account(None)
    assert account is None
    assert "No email accounts linked" in error


def test_select_email_account_single_default(temp_db):
    from comms.db import get_db

    with get_db() as conn:
        conn.execute(
            "INSERT INTO accounts (id, service_type, provider, email, enabled) VALUES (?, ?, ?, ?, ?)",
            ("id1", "email", "gmail", "a@gmail.com", 1),
        )
    account, error = accounts.select_email_account(None)
    assert account["email"] == "a@gmail.com"
    assert error is None


def test_select_email_account_multiple_no_email_specified(temp_db):
    from comms.db import get_db

    with get_db() as conn:
        conn.execute(
            "INSERT INTO accounts (id, service_type, provider, email, enabled) VALUES (?, ?, ?, ?, ?)",
            ("id1", "email", "gmail", "a@gmail.com", 1),
        )
        conn.execute(
            "INSERT INTO accounts (id, service_type, provider, email, enabled) VALUES (?, ?, ?, ?, ?)",
            ("id2", "email", "outlook", "b@outlook.com", 1),
        )
    account, error = accounts.select_email_account(None)
    assert account is None
    assert "Multiple accounts found" in error


def test_select_email_account_found(temp_db):
    from comms.db import get_db

    with get_db() as conn:
        conn.execute(
            "INSERT INTO accounts (id, service_type, provider, email, enabled) VALUES (?, ?, ?, ?, ?)",
            ("id1", "email", "gmail", "a@gmail.com", 1),
        )
        conn.execute(
            "INSERT INTO accounts (id, service_type, provider, email, enabled) VALUES (?, ?, ?, ?, ?)",
            ("id2", "email", "outlook", "b@outlook.com", 1),
        )
    account, error = accounts.select_email_account("b@outlook.com")
    assert account["email"] == "b@outlook.com"
    assert error is None


def test_select_email_account_not_found(temp_db):
    from comms.db import get_db

    with get_db() as conn:
        conn.execute(
            "INSERT INTO accounts (id, service_type, provider, email, enabled) VALUES (?, ?, ?, ?, ?)",
            ("id1", "email", "gmail", "a@gmail.com", 1),
        )
    account, error = accounts.select_email_account("missing@gmail.com")
    assert account is None
    assert "Account not found" in error


def test_remove_account_exists(temp_db):
    from comms.db import get_db

    with get_db() as conn:
        conn.execute(
            "INSERT INTO accounts (id, service_type, provider, email, enabled) VALUES (?, ?, ?, ?, ?)",
            ("id1", "email", "gmail", "a@gmail.com", 1),
        )
    result = accounts.remove_account("id1")
    assert result is True
    assert accounts.get_account_by_id("id1") is None


def test_remove_account_not_found(temp_db):
    result = accounts.remove_account("nonexistent")
    assert result is False
