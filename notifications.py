import sqlite3
from datetime import datetime
from typing import Optional, List, Dict

from config import (
    DATABASE_ENGINE,
    MYSQLDATABASE,
    MYSQLHOST,
    MYSQLPASSWORD,
    MYSQLPORT,
    MYSQLUSER,
)
from logger import logger

try:
    import mysql.connector as mysql_connector
except Exception:
    mysql_connector = None


def _get_conn():
    if DATABASE_ENGINE == "mysql":
        if mysql_connector is None:
            raise RuntimeError("mysql-connector-python is required for MySQL support.")
        return mysql_connector.connect(
            host=MYSQLHOST,
            port=MYSQLPORT,
            user=MYSQLUSER,
            password=MYSQLPASSWORD,
            database=MYSQLDATABASE,
            autocommit=True,
            use_pure=True,
        )
    # fallback to in-memory sqlite if misconfigured
    return sqlite3.connect(":memory:")


def _ensure_table(conn) -> None:
    cursor = conn.cursor()
    if DATABASE_ENGINE == "mysql":
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id INT AUTO_INCREMENT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                level VARCHAR(32) NOT NULL,
                message TEXT NOT NULL,
                owner VARCHAR(255) DEFAULT NULL,
                account_id INT DEFAULT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    else:
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
        conn = _get_conn()
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
        conn = _get_conn()
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
