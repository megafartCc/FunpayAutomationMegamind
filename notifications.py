import sqlite3
from datetime import datetime
from typing import Optional, List, Dict

from config import DATABASE_PATH
from logger import logger


def _ensure_table(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            owner TEXT DEFAULT NULL,
            account_id INTEGER DEFAULT NULL
        )
        """
    )
    conn.commit()
    cursor.close()


def send_message_to_admin(
    message: str,
    level: str = "info",
    owner: Optional[str] = None,
    account_id: Optional[int] = None,
) -> None:
    logger.info(message)
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        _ensure_table(conn)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO notifications (created_at, level, message, owner, account_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (datetime.utcnow().isoformat(), level, message, owner, account_id),
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as exc:
        logger.error(f"Failed to store admin notification: {exc}")


def list_notifications(limit: int = 50) -> List[Dict]:
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        _ensure_table(conn)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, created_at, level, message, owner, account_id
            FROM notifications
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return [
            {
                "id": row[0],
                "created_at": row[1],
                "level": row[2],
                "message": row[3],
                "owner": row[4],
                "account_id": row[5],
            }
            for row in rows
        ]
    except Exception as exc:
        logger.error(f"Failed to read notifications: {exc}")
        return []
