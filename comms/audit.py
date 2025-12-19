import json
from datetime import datetime

from .db import get_db


def log(action: str, entity_type: str, entity_id: str, metadata: dict | None = None) -> None:
    metadata_json = json.dumps(metadata) if metadata else None

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO audit_log (action, entity_type, entity_id, metadata, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (action, entity_type, entity_id, metadata_json, datetime.now()),
        )


def get_recent_logs(limit: int = 50) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT action, entity_type, entity_id, metadata, timestamp
            FROM audit_log
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return [dict(row) for row in rows]
