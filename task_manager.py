
import json
import hashlib
import uuid
from datetime import datetime, timezone

from database import get_connection


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def canonical_json(data):
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False
    )


def message_hash(message):
    return hashlib.sha256(
        canonical_json(message).encode("utf-8")
    ).hexdigest()


def find_existing_message(principal, message_id, message):
    """
    Check idempotency BEFORE calling the AI.

    Same ID + same message returns the stored Task.
    Same ID + different message returns conflict.
    """

    digest = message_hash(message)

    conn = get_connection()

    try:
        row = conn.execute("""
            SELECT message_hash, task_id
            FROM messages
            WHERE principal = ?
              AND message_id = ?
        """, (principal, message_id)).fetchone()

        if not row:
            return None

        if row["message_hash"] != digest:
            return {
                "error": "IDEMPOTENCY_CONFLICT",
                "status_code": 409
            }

        task_row = conn.execute("""
            SELECT task_json
            FROM tasks
            WHERE id = ?
              AND principal = ?
        """, (
            row["task_id"],
            principal
        )).fetchone()

        if not task_row:
            raise RuntimeError(
                "Idempotency record has no Task"
            )

        return json.loads(task_row["task_json"])

    finally:
        conn.close()


def create_task(
    principal,
    message_id,
    message,
    batch_id,
    proposals
):
    """
    Create and persist a Task.

    The caller must check find_existing_message()
    before performing expensive AI work.
    """

    digest = message_hash(message)

    conn = get_connection()

    try:
        conn.execute("BEGIN IMMEDIATE")

        existing = conn.execute("""
            SELECT message_hash, task_id
            FROM messages
            WHERE principal = ?
              AND message_id = ?
        """, (principal, message_id)).fetchone()

        if existing:

            if existing["message_hash"] != digest:
                conn.rollback()

                return {
                    "error": "IDEMPOTENCY_CONFLICT",
                    "status_code": 409
                }

            row = conn.execute("""
                SELECT task_json
                FROM tasks
                WHERE id = ?
                  AND principal = ?
            """, (
                existing["task_id"],
                principal
            )).fetchone()

            if not row:
                raise RuntimeError(
                    "Stored message has no Task"
                )

            conn.commit()
            return json.loads(row["task_json"])

        task_id = str(uuid.uuid4())
        context_id = str(uuid.uuid4())
        created = now_iso()

        task = {
            "id": task_id,
            "contextId": context_id,
            "status": {
                "state": "TASK_STATE_INPUT_REQUIRED"
            },
            "history": [message],
            "artifacts": [
                {
                    "artifactId": "invoice-proposals",
                    "parts": [
                        {
                            "mediaType": (
                                "application/vnd.ga5."
                                "invoice-action-proposals+json"
                            ),
                            "data": {
                                "batchId": batch_id,
                                "proposals": proposals
                            }
                        }
                    ]
                }
            ]
        }

        task_json = canonical_json(task)

        conn.execute("""
            INSERT INTO tasks (
                id,
                principal,
                context_id,
                batch_id,
                state,
                created_at,
                updated_at,
                task_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task_id,
            principal,
            context_id,
            batch_id,
            "TASK_STATE_INPUT_REQUIRED",
            created,
            created,
            task_json
        ))

        conn.execute("""
            INSERT INTO messages (
                principal,
                message_id,
                message_hash,
                task_id
            )
            VALUES (?, ?, ?, ?)
        """, (
            principal,
            message_id,
            digest,
            task_id
        ))

        for proposal in proposals:

            package_id = proposal["packageId"]
            action_id = proposal["actionId"]
            action = proposal["action"]

            conn.execute("""
                INSERT INTO proposals (
                    task_id,
                    package_id,
                    action_id,
                    action,
                    proposal_json
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                task_id,
                package_id,
                action_id,
                action,
                canonical_json(proposal)
            ))

        conn.commit()

        return task

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def get_task(task_id, principal):
    conn = get_connection()

    try:
        row = conn.execute("""
            SELECT task_json
            FROM tasks
            WHERE id = ?
              AND principal = ?
        """, (
            task_id,
            principal
        )).fetchone()

        if not row:
            return None

        return json.loads(row["task_json"])

    finally:
        conn.close()


def list_tasks(principal):
    conn = get_connection()

    try:
        rows = conn.execute("""
            SELECT task_json
            FROM tasks
            WHERE principal = ?
            ORDER BY created_at DESC
        """, (principal,)).fetchall()

        return [
            json.loads(row["task_json"])
            for row in rows
        ]

    finally:
        conn.close()
