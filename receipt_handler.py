
import json

from database import get_connection
from task_manager import canonical_json, message_hash


RESULT_MEDIA_TYPE = (
    "application/vnd.ga5.invoice-action-results+json"
)

RECEIPT_MEDIA_TYPE = (
    "application/vnd.ga5.invoice-action-receipts+json"
)

PROPOSAL_MEDIA_TYPE = (
    "application/vnd.ga5.invoice-action-proposals+json"
)


def error_result(error, status_code=400):
    return {
        "error": error,
        "status_code": status_code
    }


def process_results(
    task_id,
    principal,
    context_id,
    message
):
    """
    Process a grader result continuation.

    Guarantees:
    - Task ownership is checked.
    - Context and batch IDs are checked.
    - Result message retries are idempotent.
    - Accepted results must match stored proposals.
    - Rejected results are never executed.
    - Receipt insertion and Task completion are transactional.
    """

    message_id = message.get("messageId")

    if not isinstance(message_id, str) or not message_id:
        return error_result(
            "Missing continuation message ID",
            400
        )

    # Hash the complete continuation message.
    digest = message_hash(message)

    parts = message.get("parts", [])

    if not isinstance(parts, list):
        return error_result(
            "Invalid message parts",
            400
        )

    result_part = None

    for part in parts:

        if not isinstance(part, dict):
            continue

        if part.get("mediaType") == RESULT_MEDIA_TYPE:
            result_part = part
            break

    if result_part is None:
        return error_result(
            "Missing result payload",
            400
        )

    result_data = result_part.get("data")

    if not isinstance(result_data, dict):
        return error_result(
            "Invalid result payload",
            400
        )

    batch_id = result_data.get("batchId")

    results = result_data.get("results")

    if not isinstance(results, list):
        return error_result(
            "Invalid results",
            400
        )

    conn = get_connection()

    try:

        # Serialize receipt processing and cancellation.
        conn.execute("BEGIN IMMEDIATE")

        # --------------------------------------------------
        # 1. Continuation idempotency.
        # --------------------------------------------------

        cached = conn.execute("""
            SELECT message_hash, response_json
            FROM continuation_messages
            WHERE principal = ?
              AND message_id = ?
        """, (
            principal,
            message_id
        )).fetchone()

        if cached:

            if cached["message_hash"] != digest:

                conn.rollback()

                return error_result(
                    "IDEMPOTENCY_CONFLICT",
                    409
                )

            original_response = json.loads(
                cached["response_json"]
            )

            conn.commit()

            return original_response

        # --------------------------------------------------
        # 2. Load Task and verify ownership.
        # --------------------------------------------------

        row = conn.execute("""
            SELECT task_json,
                   batch_id,
                   context_id,
                   state
            FROM tasks
            WHERE id = ?
              AND principal = ?
        """, (
            task_id,
            principal
        )).fetchone()

        if row is None:

            conn.rollback()

            return error_result(
                "Task not found",
                404
            )

        task = json.loads(
            row["task_json"]
        )

        if row["context_id"] != context_id:

            conn.rollback()

            return error_result(
                "Context mismatch",
                409
            )

        if row["batch_id"] != batch_id:

            conn.rollback()

            return error_result(
                "Batch mismatch",
                409
            )

        # --------------------------------------------------
        # 3. Only INPUT_REQUIRED tasks may receive results.
        # --------------------------------------------------

        if row["state"] != "TASK_STATE_INPUT_REQUIRED":

            conn.rollback()

            return error_result(
                "Task is not awaiting results",
                409
            )

        # --------------------------------------------------
        # 4. Find stored proposal artifact.
        # --------------------------------------------------

        proposal_data = None

        for artifact in task.get("artifacts", []):

            for part in artifact.get("parts", []):

                if (
                    part.get("mediaType")
                    == PROPOSAL_MEDIA_TYPE
                ):

                    proposal_data = part.get("data")
                    break

            if proposal_data is not None:
                break

        if not isinstance(proposal_data, dict):

            conn.rollback()

            return error_result(
                "Stored proposal missing",
                500
            )

        if proposal_data.get("batchId") != batch_id:

            conn.rollback()

            return error_result(
                "Proposal batch mismatch",
                409
            )

        proposals = proposal_data.get(
            "proposals",
            []
        )

        if not isinstance(proposals, list):

            conn.rollback()

            return error_result(
                "Invalid stored proposals",
                500
            )

        proposal_map = {}

        for proposal in proposals:

            if not isinstance(proposal, dict):

                conn.rollback()

                return error_result(
                    "Invalid stored proposal",
                    500
                )

            package_id = proposal.get("packageId")

            if (
                not isinstance(package_id, str)
                or not package_id
                or package_id in proposal_map
            ):

                conn.rollback()

                return error_result(
                    "Invalid or duplicate stored package",
                    500
                )

            proposal_map[package_id] = proposal

        # --------------------------------------------------
        # 5. Validate all grader results.
        # --------------------------------------------------

        seen_packages = set()

        accepted_executions = []

        for result in results:

            if not isinstance(result, dict):

                conn.rollback()

                return error_result(
                    "Invalid result entry",
                    400
                )

            package_id = result.get("packageId")

            if (
                not isinstance(package_id, str)
                or not package_id
            ):

                conn.rollback()

                return error_result(
                    "Missing package ID",
                    400
                )

            if package_id in seen_packages:

                conn.rollback()

                return error_result(
                    "Duplicate result",
                    409
                )

            seen_packages.add(package_id)

            proposal = proposal_map.get(package_id)

            if proposal is None:

                conn.rollback()

                return error_result(
                    "Unknown package",
                    409
                )

            # Action ID must match the stored proposal.
            if (
                result.get("actionId")
                != proposal.get("actionId")
            ):

                conn.rollback()

                return error_result(
                    "Action ID mismatch",
                    409
                )

            # Action must match the stored proposal.
            if (
                result.get("action")
                != proposal.get("action")
            ):

                conn.rollback()

                return error_result(
                    "Action mismatch",
                    409
                )

            outcome = result.get("outcome")

            if outcome not in (
                "ACCEPTED",
                "REJECTED"
            ):

                conn.rollback()

                return error_result(
                    "Invalid outcome",
                    400
                )

            nonce = result.get("receiptNonce")

            if (
                not isinstance(nonce, str)
                or not nonce
            ):

                conn.rollback()

                return error_result(
                    "Missing receipt nonce",
                    400
                )

            # --------------------------------------------------
            # Rejected proposals are not executed.
            # --------------------------------------------------

            if outcome == "REJECTED":
                continue

            # --------------------------------------------------
            # Accepted proposals.
            # --------------------------------------------------

            execution = {
                "packageId": proposal["packageId"],
                "actionId": proposal["actionId"],
                "action": proposal["action"],
                "receiptNonce": nonce,
                "facts": proposal["facts"],
                "evidenceRefs": proposal["evidenceRefs"]
            }

            accepted_executions.append(execution)

        # Require one result for each stored proposal.
        if seen_packages != set(proposal_map):

            conn.rollback()

            return error_result(
                "Incomplete results",
                409
            )

        # --------------------------------------------------
        # 6. Store accepted receipts only.
        # --------------------------------------------------

        for execution in accepted_executions:

            conn.execute("""
                INSERT INTO receipts (
                    task_id,
                    package_id,
                    action_id,
                    receipt_nonce,
                    receipt_json
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                task_id,
                execution["packageId"],
                execution["actionId"],
                execution["receiptNonce"],
                canonical_json(execution)
            ))

        # --------------------------------------------------
        # 7. Append receipt artifact.
        # --------------------------------------------------

        receipt_artifact = {
            "artifactId": "invoice-action-receipts",
            "parts": [
                {
                    "mediaType": RECEIPT_MEDIA_TYPE,
                    "data": {
                        "batchId": batch_id,
                        "executions": accepted_executions
                    }
                }
            ]
        }

        task.setdefault(
            "artifacts", []
        ).append(receipt_artifact)

        # --------------------------------------------------
        # 8. Append continuation to history.
        # --------------------------------------------------

        task.setdefault(
            "history", []
        ).append(message)

        # --------------------------------------------------
        # 9. Mark Task completed.
        # --------------------------------------------------

        task["status"] = {
            "state": "TASK_STATE_COMPLETED"
        }

        task_json = canonical_json(task)

        update = conn.execute("""
            UPDATE tasks
            SET state = ?,
                updated_at = CURRENT_TIMESTAMP,
                task_json = ?
            WHERE id = ?
              AND principal = ?
              AND state = ?
        """, (
            "TASK_STATE_COMPLETED",
            task_json,
            task_id,
            principal,
            "TASK_STATE_INPUT_REQUIRED"
        ))

        if update.rowcount != 1:

            conn.rollback()

            return error_result(
                "Task state changed",
                409
            )

        # --------------------------------------------------
        # 10. Save continuation replay response.
        # --------------------------------------------------

        conn.execute("""
            INSERT INTO continuation_messages (
                principal,
                message_id,
                message_hash,
                task_id,
                response_json
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            principal,
            message_id,
            digest,
            task_id,
            canonical_json(task)
        ))

        # Commit receipts, Task completion, and replay record
        # together. A retry cannot process them twice.
        conn.commit()

        return task

    except Exception:

        conn.rollback()

        raise

    finally:

        conn.close()
