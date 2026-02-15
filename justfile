default:
    @just --list

install:
    @uv sync

ci:
    @uv run ruff format .
    @uv run ruff check . --fix
    @uv run ruff check .
    @uv run pyright
    @uv run pytest tests -q

lint:
    @uv run ruff check .

format:
    @uv run ruff format .

fix:
    @uv run ruff check . --fix

test:
    @uv run pytest tests

cov:
    @uv run pytest tests --cov --cov-report=term-missing:skip-covered

cov-accounts:
    @uv run pytest tests/unit/test_accounts.py --cov=comms.accounts --cov-fail-under=80 --cov-report=term-missing:skip-covered

clean:
    @rm -rf build/ dist/ *.egg-info .pytest_cache .ruff_cache __pycache__ .venv
    @find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

commits:
    @git --no-pager log --pretty=format:"%h | %ar | %s"

health:
    @uv run python -m comms.health
