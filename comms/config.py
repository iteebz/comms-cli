from pathlib import Path

import yaml

COMMS_DIR = Path.home() / ".comms"
DB_PATH = COMMS_DIR / "store.db"
CONFIG_PATH = COMMS_DIR / "config.yaml"
RULES_PATH = COMMS_DIR / "rules.md"
BACKUP_DIR = Path.home() / ".comms_backups"


class Config:
    _instance: "Config | None" = None
    _data: dict = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._data = {}
            cls._instance._load()
        return cls._instance

    def _load(self):
        if not CONFIG_PATH.exists():
            self._data = {}
            return
        try:
            with open(CONFIG_PATH) as f:
                self._data = yaml.safe_load(f) or {}
        except Exception:
            self._data = {}

    def _save(self):
        COMMS_DIR.mkdir(exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            yaml.dump(self._data, f, default_flow_style=False, allow_unicode=True)

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        self._data[key] = value
        self._save()


_config = Config()


def get_accounts(service_type: str | None = None) -> dict | list:
    accounts: dict = _config.get("accounts", {}) or {}
    if service_type:
        return accounts.get(service_type, [])
    return accounts


def add_account(service_type: str, account_data: dict) -> None:
    accounts: dict = _config.get("accounts", {}) or {}
    if service_type not in accounts:
        accounts[service_type] = []
    accounts[service_type].append(account_data)
    _config.set("accounts", accounts)


def get_policy() -> dict:
    return (
        _config.get(
            "policy",
            {
                "allowed_recipients": [],
                "allowed_domains": [],
                "require_approval": True,
                "max_daily_sends": 50,
                "auto_approve": {
                    "enabled": False,
                    "threshold": 0.95,
                    "min_samples": 10,
                    "actions": [],
                },
            },
        )
        or {}
    )


def set_policy(policy):
    _config.set("policy", policy)


def get_agent_config() -> dict:
    return (
        _config.get(
            "agent",
            {
                "enabled": True,
                "nlp": False,
            },
        )
        or {}
    )


def set_agent_config(config):
    _config.set("agent", config)
