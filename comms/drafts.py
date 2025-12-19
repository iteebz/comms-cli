import uuid
from datetime import datetime

from . import audit
from .db import get_db
from .models import Draft


def create_draft(
    to_addr: str,
    subject: str,
    body: str,
    thread_id: str | None = None,
    message_id: str | None = None,
    cc_addr: str | None = None,
    claude_reasoning: str | None = None,
) -> str:
    draft_id = str(uuid.uuid4())

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO drafts (id, thread_id, message_id, to_addr, cc_addr, subject, body, claude_reasoning)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (draft_id, thread_id, message_id, to_addr, cc_addr, subject, body, claude_reasoning),
        )

    audit.log(
        "create",
        "draft",
        draft_id,
        {
            "to": to_addr,
            "subject": subject,
            "auto_generated": claude_reasoning is not None,
        },
    )

    return draft_id


def get_draft(draft_id: str) -> Draft | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()

        if not row:
            return None

        return Draft(
            id=row["id"],
            thread_id=row["thread_id"],
            message_id=row["message_id"],
            to_addr=row["to_addr"],
            cc_addr=row["cc_addr"],
            subject=row["subject"],
            body=row["body"],
            claude_reasoning=row["claude_reasoning"],
            created_at=datetime.fromisoformat(row["created_at"]),
            approved_at=datetime.fromisoformat(row["approved_at"]) if row["approved_at"] else None,
            sent_at=datetime.fromisoformat(row["sent_at"]) if row["sent_at"] else None,
        )


def approve_draft(draft_id: str) -> None:
    with get_db() as conn:
        conn.execute("UPDATE drafts SET approved_at = ? WHERE id = ?", (datetime.now(), draft_id))

    audit.log("approve", "draft", draft_id)


def mark_sent(draft_id: str) -> None:
    with get_db() as conn:
        conn.execute("UPDATE drafts SET sent_at = ? WHERE id = ?", (datetime.now(), draft_id))

    audit.log("send", "draft", draft_id)


def list_pending_drafts() -> list[Draft]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM drafts
            WHERE approved_at IS NULL AND sent_at IS NULL
            ORDER BY created_at DESC
            """
        ).fetchall()

        return [
            Draft(
                id=row["id"],
                thread_id=row["thread_id"],
                message_id=row["message_id"],
                to_addr=row["to_addr"],
                cc_addr=row["cc_addr"],
                subject=row["subject"],
                body=row["body"],
                claude_reasoning=row["claude_reasoning"],
                created_at=datetime.fromisoformat(row["created_at"]),
                approved_at=None,
                sent_at=None,
            )
            for row in rows
        ]
