
import sqlite3
from config import DATABASE_PATH


def get_connection():
    conn = sqlite3.connect(
        DATABASE_PATH,
        timeout=30,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")

    return conn


def init_db():
    conn = get_connection()

    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            principal TEXT NOT NULL,
            context_id TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            task_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            principal TEXT NOT NULL,
            message_id TEXT NOT NULL,
            message_hash TEXT NOT NULL,
            task_id TEXT NOT NULL,
            PRIMARY KEY (principal, message_id),
            FOREIGN KEY(task_id) REFERENCES tasks(id)
        );

        CREATE TABLE IF NOT EXISTS proposals (
            task_id TEXT NOT NULL,
            package_id TEXT NOT NULL,
            action_id TEXT NOT NULL,
            action TEXT NOT NULL,
            proposal_json TEXT NOT NULL,
            PRIMARY KEY (task_id, package_id),
            UNIQUE (task_id, action_id),
            FOREIGN KEY(task_id) REFERENCES tasks(id)
        );

        CREATE TABLE IF NOT EXISTS receipts (
            task_id TEXT NOT NULL,
            package_id TEXT NOT NULL,
            action_id TEXT NOT NULL,
            receipt_nonce TEXT NOT NULL UNIQUE,
            receipt_json TEXT NOT NULL,
            PRIMARY KEY (task_id, package_id),
            FOREIGN KEY(task_id) REFERENCES tasks(id)
        );

        CREATE TABLE IF NOT EXISTS decision_cache (
            package_hash TEXT PRIMARY KEY,
            decision_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS continuation_messages (
            principal TEXT NOT NULL,
            message_id TEXT NOT NULL,
            message_hash TEXT NOT NULL,
            task_id TEXT NOT NULL,
            response_json TEXT NOT NULL,
            PRIMARY KEY (principal, message_id),
            FOREIGN KEY(task_id) REFERENCES tasks(id)
        );
        """)

        conn.commit()

    finally:
        conn.close()
