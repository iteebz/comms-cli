import uuid

from . import accounts as accts_module
from . import audit
from .adapters.email import gmail
from .adapters.messaging import signal
from .db import get_db, now_iso

VALID_THREAD_ACTIONS = {"archive", "delete", "flag", "unflag", "unarchive", "undelete"}
VALID_DRAFT_ACTIONS = {"approve", "send", "delete"}
VALID_SIGNAL_ACTIONS = {"mark_read", "ignore"}


def _validate_entity(entity_type: str, entity_id: str, email: str | None) -> tuple[bool, str]:
    if entity_type == "thread":
        account, error = accts_module.select_email_account(email)
        if not account:
            return False, error or "No email account found"

        try:
            if account["provider"] == "gmail":
                messages = gmail.fetch_thread_messages(entity_id, email)
                if not messages:
                    return False, f"Thread {entity_id} not found"
                return True, ""
            return False, f"Provider {account['provider']} not supported for validation"
        except Exception as e:
            return False, f"Failed to validate thread: {e}"

    elif entity_type == "draft":
        from . import drafts

        draft = drafts.get_draft(entity_id)
        if not draft:
            return False, f"Draft {entity_id} not found"
        return True, ""

    elif entity_type == "signal_message":
        msg = signal.get_message(entity_id)
        if not msg:
            return False, f"Signal message {entity_id} not found"
        return True, ""

    else:
        return False, f"Unknown entity_type: {entity_type}"


def _validate_action(entity_type: str, proposed_action: str) -> tuple[bool, str]:
    if entity_type == "thread":
        if proposed_action not in VALID_THREAD_ACTIONS:
            return (
                False,
                f"Invalid action '{proposed_action}' for thread. Valid: {VALID_THREAD_ACTIONS}",
            )
        return True, ""

    if entity_type == "draft":
        if proposed_action not in VALID_DRAFT_ACTIONS:
            return (
                False,
                f"Invalid action '{proposed_action}' for draft. Valid: {VALID_DRAFT_ACTIONS}",
            )
        return True, ""

    if entity_type == "signal_message":
        if proposed_action not in VALID_SIGNAL_ACTIONS:
            return (
                False,
                f"Invalid action '{proposed_action}' for signal_message. Valid: {VALID_SIGNAL_ACTIONS}",
            )
        return True, ""

    return False, f"Unknown entity_type: {entity_type}"


def create_proposal(
    entity_type: str,
    entity_id: str,
    proposed_action: str,
    agent_reasoning: str | None = None,
    email: str | None = None,
    skip_validation: bool = False,
) -> tuple[str | None, str]:
    if not skip_validation:
        valid_action, msg = _validate_action(entity_type, proposed_action)
        if not valid_action:
            return None, msg

        valid_entity, msg = _validate_entity(entity_type, entity_id, email)
        if not valid_entity:
            return None, msg

    proposal_id = str(uuid.uuid4())

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO proposals (id, entity_type, entity_id, proposed_action, agent_reasoning, email, proposed_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal_id,
                entity_type,
                entity_id,
                proposed_action,
                agent_reasoning,
                email,
                now_iso(),
                "pending",
            ),
        )

    return proposal_id, ""


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
            (now_iso(), user_reasoning, full_id),
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


def reject_proposal(
    proposal_id: str, user_reasoning: str | None = None, correction: str | None = None
) -> bool:
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
            SET status = 'rejected', rejected_at = ?, user_reasoning = ?, correction = ?
            WHERE id = ?
            """,
            (now_iso(), user_reasoning, correction, full_id),
        )

    decision_type = "rejected_with_correction" if correction else "rejected"
    metadata = {
        "proposal_id": proposal_id,
        "agent_reasoning": proposal["agent_reasoning"],
    }
    if correction:
        metadata["correction"] = correction

    audit.log_decision(
        proposed_action=proposal["proposed_action"],
        entity_type=proposal["entity_type"],
        entity_id=proposal["entity_id"],
        user_decision=decision_type,
        reasoning=user_reasoning,
        metadata=metadata,
    )

    return True


def mark_executed(proposal_id: str) -> bool:
    with get_db() as conn:
        conn.execute(
            "UPDATE proposals SET status = 'executed', executed_at = ? WHERE id = ?",
            (now_iso(), proposal_id),
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
