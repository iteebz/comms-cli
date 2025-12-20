import os
import signal
import sys
import time

from .adapters.messaging import signal as signal_adapter
from .config import COMMS_DIR

PID_FILE = COMMS_DIR / "daemon.pid"
LOG_FILE = COMMS_DIR / "daemon.log"


def _log(msg: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"{timestamp} {msg}\n")


def _get_signal_phones() -> list[str]:
    from . import accounts as accts_module

    accounts = accts_module.list_accounts("messaging")
    return [a["email"] for a in accounts if a["provider"] == "signal"]


def _poll_once(phones: list[str], timeout: int = 1, agent_mode: bool = True) -> int:
    from . import agent

    total = 0
    for phone in phones:
        try:
            msgs = signal_adapter.receive(phone, timeout=timeout, store=True)
            if msgs:
                total += len(msgs)
                for m in msgs:
                    sender = m.get("from_name", m.get("sender_phone", "Unknown"))
                    _log(f"[{phone}] {sender}: {m['body'][:50]}")

                    if agent_mode:
                        response = agent.handle_incoming(phone, m)
                        if response:
                            sender_phone = m.get("sender_phone", "")
                            if sender_phone:
                                signal_adapter.send(phone, sender_phone, response)
                                _log(f"[{phone}] -> {sender_phone}: {response[:50]}")
        except Exception as e:
            _log(f"[{phone}] Error: {e}")
    return total


def run(interval: int = 5) -> None:
    phones = _get_signal_phones()
    if not phones:
        print("No Signal accounts linked")
        sys.exit(1)

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    running = True

    def handle_signal(signum, frame):
        nonlocal running
        running = False
        _log("Shutdown signal received")

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    _log(f"Daemon started, polling {len(phones)} account(s) every {interval}s")
    print(f"Daemon started (PID {os.getpid()})")

    while running:
        _poll_once(phones, timeout=1)
        time.sleep(interval)

    PID_FILE.unlink(missing_ok=True)
    _log("Daemon stopped")


def start(interval: int = 5, foreground: bool = False) -> tuple[bool, str]:
    if is_running():
        return False, f"Already running (PID {get_pid()})"

    phones = _get_signal_phones()
    if not phones:
        return False, "No Signal accounts linked"

    if foreground:
        run(interval)
        return True, "Stopped"

    pid = os.fork()
    if pid > 0:
        time.sleep(0.5)
        if is_running():
            return True, f"Started (PID {pid})"
        return False, "Failed to start"

    os.setsid()
    os.umask(0)

    sys.stdin = open(os.devnull)  # noqa: SIM115
    sys.stdout = open(os.devnull, "w")  # noqa: SIM115
    sys.stderr = open(os.devnull, "w")  # noqa: SIM115

    run(interval)
    sys.exit(0)


def stop() -> tuple[bool, str]:
    pid = get_pid()
    if not pid:
        return False, "Not running"

    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(10):
            time.sleep(0.5)
            if not is_running():
                return True, "Stopped"
        os.kill(pid, signal.SIGKILL)
        PID_FILE.unlink(missing_ok=True)
        return True, "Killed"
    except ProcessLookupError:
        PID_FILE.unlink(missing_ok=True)
        return True, "Was not running"


def get_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text().strip())
    except (ValueError, FileNotFoundError):
        return None


def is_running() -> bool:
    pid = get_pid()
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        PID_FILE.unlink(missing_ok=True)
        return False


def status() -> dict:
    pid = get_pid()
    running = is_running()
    phones = _get_signal_phones()

    result = {
        "running": running,
        "pid": pid if running else None,
        "accounts": phones,
        "log_file": str(LOG_FILE),
    }

    if LOG_FILE.exists():
        lines = LOG_FILE.read_text().strip().split("\n")
        result["last_log"] = lines[-5:] if len(lines) > 5 else lines

    return result
