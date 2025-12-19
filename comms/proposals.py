import uuid
from datetime import datetime

from . import audit
from .db import get_db


def create_proposal(
    entity_type: str,
    entity_id: str,
    proposed_action: str,
    agent_reasoning: str | None = None,
) -> str:
    proposal_id = str(uuid.uuid4())

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO proposals (id, entity_type, entity_id, proposed_action, agent_reasoning, proposed_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal_id,
                entity_type,
                entity_id,
                proposed_action,
                agent_reasoning,
                datetime.now(),
                "pending",
            ),
        )

    return proposal_id


def get_proposal(proposal_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
        if not row:
            return None
        return dict(row)


def list_proposals(status: str | None = None) -> list[dict]:
    with get_db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM proposals WHERE status = ? ORDER BY proposed_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM proposals ORDER BY proposed_at DESC").fetchall()

        return [dict(row) for row in rows]


def _resolve_proposal_id(proposal_id_prefix: str) -> str | None:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id FROM proposals WHERE id LIKE ? ORDER BY proposed_at DESC",
            (f"{proposal_id_prefix}%",),
        ).fetchall()

        if len(rows) == 1:
            return rows[0]["id"]
        return None


def approve_proposal(proposal_id: str, user_reasoning: str | None = None) -> bool:
    full_id = _resolve_proposal_id(proposal_id) or proposal_id

    with get_db() as conn:
        row = conn.execute("SELECT * FROM proposals WHERE id = ?", (full_id,)).fetchone()
        if not row:
            return False

        proposal = dict(row)
        if proposal["status"] != "pending":
            return False

        conn.execute(
            """
            UPDATE proposals
            SET status = 'approved', approved_at = ?, approved_by = 'user', user_reasoning = ?
            WHERE id = ?
            """,
            (datetime.now(), user_reasoning, full_id),
        )

    audit.log_decision(
        proposed_action=proposal["proposed_action"],
        entity_type=proposal["entity_type"],
        entity_id=proposal["entity_id"],
        user_decision="approved",
        reasoning=user_reasoning,
        metadata={"proposal_id": proposal_id, "agent_reasoning": proposal["agent_reasoning"]},
    )

    return True


def reject_proposal(proposal_id: str, user_reasoning: str | None = None) -> bool:
    full_id = _resolve_proposal_id(proposal_id) or proposal_id

    with get_db() as conn:
        row = conn.execute("SELECT * FROM proposals WHERE id = ?", (full_id,)).fetchone()
        if not row:
            return False

        proposal = dict(row)
        if proposal["status"] != "pending":
            return False

        conn.execute(
            """
            UPDATE proposals
            SET status = 'rejected', rejected_at = ?, user_reasoning = ?
            WHERE id = ?
            """,
            (datetime.now(), user_reasoning, full_id),
        )

    audit.log_decision(
        proposed_action=proposal["proposed_action"],
        entity_type=proposal["entity_type"],
        entity_id=proposal["entity_id"],
        user_decision="rejected",
        reasoning=user_reasoning,
        metadata={"proposal_id": proposal_id, "agent_reasoning": proposal["agent_reasoning"]},
    )

    return True


def mark_executed(proposal_id: str) -> bool:
    with get_db() as conn:
        conn.execute(
            "UPDATE proposals SET status = 'executed', executed_at = ? WHERE id = ?",
            (datetime.now(), proposal_id),
        )

    proposal = get_proposal(proposal_id)
    if proposal:
        audit.log(
            action="execute",
            entity_type=proposal["entity_type"],
            entity_id=proposal["entity_id"],
            metadata={"proposal_id": proposal_id, "action": proposal["proposed_action"]},
        )

    return True


def get_approved_proposals() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM proposals WHERE status = 'approved' ORDER BY approved_at ASC"
        ).fetchall()
        return [dict(row) for row in rows]
