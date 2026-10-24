
import json
from datetime import datetime, timezone

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

from config import APP_NAME, APP_VERSION, BASE_URL
from database import init_db, get_connection
from auth import authenticate
from protocol import validate_protocol

from decision_engine import generate_proposals
from receipt_handler import process_results

from task_manager import (
    create_task,
    get_task,
    list_tasks,
    find_existing_message,
    canonical_json,
)


app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION
)


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def a2a_response(data, status_code=200):
    return JSONResponse(
        status_code=status_code,
        content=data,
        media_type="application/a2a+json"
    )


def error_response(code, message, status_code):
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message
            }
        },
        media_type="application/a2a+json"
    )


# --------------------------------------------------
# Startup
# --------------------------------------------------

@app.on_event("startup")
def startup():
    init_db()


# --------------------------------------------------
# Agent Card
# --------------------------------------------------

@app.get("/.well-known/agent-card.json")
def agent_card():

    return {
        "name": APP_NAME,
        "description": (
            "Evidence-based invoice action agent."
        ),
        "version": APP_VERSION,

        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": True
        },

        "supportedInterfaces": [
            {
                "url": BASE_URL,
                "protocolBinding": "HTTP+JSON",
                "protocolVersion": "1.0"
            }
        ],

        "defaultInputModes": [
            "application/a2a+json",
            "application/vnd.ga5.invoice-claim-batch+json"
        ],

        "defaultOutputModes": [
            "application/a2a+json",
            "application/vnd.ga5.invoice-action-proposals+json",
            "application/vnd.ga5.invoice-action-receipts+json"
        ],

        "skills": [
            {
                "id": "invoice_action_agent",
                "name": "Invoice Action Agent",
                "description": (
                    "Analyze invoice documents and propose "
                    "evidence-backed actions."
                ),
                "tags": [
                    "invoice",
                    "payment",
                    "approval",
                    "evidence"
                ]
            }
        ]
    }


# --------------------------------------------------
# Health
# --------------------------------------------------

@app.get("/a2a/health")
def health():

    return {
        "status": "ok"
    }


# --------------------------------------------------
# Send Message
# --------------------------------------------------

@app.post("/a2a/message:send")
async def send_message(request: Request):

    # Validate protocol headers.
    validate_protocol(request)

    # Authenticate caller.
    principal = authenticate(request)

    # Parse request JSON.
    try:
        body = await request.json()

    except Exception:

        return error_response(
            "INVALID_JSON",
            "Invalid JSON request",
            400
        )

    if not isinstance(body, dict):

        return error_response(
            "INVALID_REQUEST",
            "Request body must be an object",
            400
        )

    message = body.get("message")

    if not isinstance(message, dict):

        return error_response(
            "INVALID_MESSAGE",
            "Missing message object",
            400
        )

    # Validate message ID.
    message_id = message.get("messageId")

    if not isinstance(message_id, str) or not message_id:

        return error_response(
            "INVALID_MESSAGE_ID",
            "Missing message ID",
            400
        )

    # Validate role.
    if message.get("role") != "ROLE_USER":

        return error_response(
            "INVALID_ROLE",
            "Message role must be ROLE_USER",
            400
        )

    # Validate parts.
    parts = message.get("parts")

    if not isinstance(parts, list) or not parts:

        return error_response(
            "INVALID_PARTS",
            "Message must contain parts",
            400
        )

    # --------------------------------------------------
    # Continuation message: process grader results.
    # --------------------------------------------------

    task_id = message.get("taskId")

    if task_id:

        context_id = message.get("contextId")

        if not isinstance(task_id, str) or not task_id:

            return error_response(
                "INVALID_TASK_ID",
                "Invalid task ID",
                400
            )

        if not isinstance(context_id, str) or not context_id:

            return error_response(
                "INVALID_CONTEXT_ID",
                "Invalid context ID",
                400
            )

        # Verify task ownership before processing results.
        task = get_task(
            task_id,
            principal
        )

        if task is None:

            return error_response(
                "TASK_NOT_FOUND",
                "Task not found",
                404
            )

        if task.get("contextId") != context_id:

            return error_response(
                "CONTEXT_MISMATCH",
                "Context does not match Task",
                409
            )

        # Process accepted/rejected invoice decisions.
        result = process_results(
            task_id=task_id,
            principal=principal,
            context_id=context_id,
            message=message
        )

        if result.get("error"):

            return error_response(
                result["error"],
                result.get("message", "Result processing failed"),
                result.get("status_code", 400)
            )

        return a2a_response({
            "task": result
        })

    # --------------------------------------------------
    # Initial invoice batch message.
    # --------------------------------------------------

    # Check idempotency BEFORE AI generation.
    existing = find_existing_message(
        principal=principal,
        message_id=message_id,
        message=message
    )

    if existing is not None:

        if existing.get("error") == "IDEMPOTENCY_CONFLICT":

            return error_response(
                "IDEMPOTENCY_CONFLICT",
                "Message ID reused with different content",
                409
            )

        return a2a_response({
            "task": existing
        })

    # Locate invoice batch part.
    invoice_part = None

    for part in parts:

        if not isinstance(part, dict):
            continue

        if (
            part.get("mediaType")
            == "application/vnd.ga5.invoice-claim-batch+json"
        ):

            invoice_part = part
            break

    if invoice_part is None:

        return error_response(
            "MISSING_INVOICE_BATCH",
            "Missing invoice batch",
            400
        )

    # Extract batch.
    batch = invoice_part.get("data")

    if not isinstance(batch, dict):

        return error_response(
            "INVALID_INVOICE_BATCH",
            "Invoice batch must be an object",
            400
        )

    batch_id = batch.get("batchId")

    if not isinstance(batch_id, str) or not batch_id:

        return error_response(
            "INVALID_BATCH_ID",
            "Missing batch ID",
            400
        )

    packages = batch.get("packages")

    if not isinstance(packages, list):

        return error_response(
            "INVALID_PACKAGES",
            "Packages must be a list",
            400
        )

    # Assignment requires exactly 12 packages.
    if len(packages) != 12:

        return error_response(
            "INVALID_PACKAGE_COUNT",
            "Invoice batch must contain exactly 12 packages",
            400
        )

    # --------------------------------------------------
    # AI proposal generation.
    # --------------------------------------------------

    try:

        proposals = generate_proposals(batch)

    except Exception as exc:

        print(
            "Invoice decision error:",
            str(exc)
        )

        raise HTTPException(
            status_code=500,
            detail="Invoice decision failed"
        )

    # --------------------------------------------------
    # Persist task and proposals.
    # --------------------------------------------------

    task = create_task(
        principal=principal,
        message_id=message_id,
        message=message,
        batch_id=batch_id,
        proposals=proposals
    )

    if task.get("error") == "IDEMPOTENCY_CONFLICT":

        return error_response(
            "IDEMPOTENCY_CONFLICT",
            "Message ID reused with different content",
            409
        )

    return a2a_response({
        "task": task
    })


# --------------------------------------------------
# List Tasks
# --------------------------------------------------

@app.get("/a2a/tasks")
def get_tasks(request: Request):

    validate_protocol(request)

    principal = authenticate(request)

    tasks = list_tasks(principal)

    return a2a_response({
        "tasks": tasks
    })


# --------------------------------------------------
# Read Task
# --------------------------------------------------

@app.get("/a2a/tasks/{task_id}")
def read_task(
    task_id: str,
    request: Request
):

    validate_protocol(request)

    principal = authenticate(request)

    task = get_task(
        task_id,
        principal
    )

    if task is None:

        return error_response(
            "TASK_NOT_FOUND",
            "Task not found",
            404
        )

    return a2a_response({
        "task": task
    })


# --------------------------------------------------
# Cancel Task
# --------------------------------------------------

@app.post("/a2a/tasks/{task_id}:cancel")
async def cancel_task(
    task_id: str,
    request: Request
):

    validate_protocol(request)

    principal = authenticate(request)

    conn = get_connection()

    try:

        # Serialize cancellation against other writes.
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute("""
            SELECT task_json, state
            FROM tasks
            WHERE id = ?
              AND principal = ?
        """, (
            task_id,
            principal
        )).fetchone()

        if row is None:

            conn.rollback()

            return error_response(
                "TASK_NOT_FOUND",
                "Task not found",
                404
            )

        task = json.loads(
            row["task_json"]
        )

        state = task.get(
            "status", {}
        ).get(
            "state"
        )

        # Do not modify terminal tasks.
        if state in (
            "TASK_STATE_COMPLETED",
            "TASK_STATE_CANCELED",
            "TASK_STATE_FAILED"
        ):

            conn.rollback()

            return a2a_response({
                "task": task
            })

        # Update status.
        task.setdefault(
            "status", {}
        )

        task["status"]["state"] = (
            "TASK_STATE_CANCELED"
        )

        task["status"]["message"] = {
            "role": "ROLE_AGENT",
            "parts": [
                {
                    "type": "text",
                    "text": "Task canceled"
                }
            ]
        }

        # Update task history.
        task.setdefault(
            "history", []
        )

        task["history"].append({
            "role": "ROLE_AGENT",
            "parts": [
                {
                    "type": "text",
                    "text": "Task canceled"
                }
            ]
        })

        updated = now_iso()

        conn.execute("""
            UPDATE tasks
            SET state = ?,
                updated_at = ?,
                task_json = ?
            WHERE id = ?
              AND principal = ?
        """, (
            "TASK_STATE_CANCELED",
            updated,
            canonical_json(task),
            task_id,
            principal
        ))

        conn.commit()

        return a2a_response({
            "task": task
        })

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()
