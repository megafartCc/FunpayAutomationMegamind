from datetime import datetime
from threading import Lock
from typing import Optional, List, Dict

from backend.config import MYSQLDATABASE, MYSQLHOST, MYSQLPASSWORD, MYSQLPORT, MYSQLUSER
from backend.logger import logger

try:
    import mysql.connector as mysql_connector
except Exception:
    mysql_connector = None


def _get_conn():
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


_TABLE_LOCK = Lock()
_TABLE_READY = False


def _ensure_table(conn) -> None:
    global _TABLE_READY
    if _TABLE_READY:
        return
    with _TABLE_LOCK:
        if _TABLE_READY:
            return
    cursor = conn.cursor()
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
    conn.commit()
    cursor.close()
    _TABLE_READY = True


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
        placeholders = "%s, %s, %s, %s, %s"
        cursor.execute(
            f"""
            INSERT INTO notifications (created_at, level, message, owner, account_id)
            VALUES ({placeholders})
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
        limit_placeholder = "%s"
        cursor.execute(
            f"""
            SELECT id, created_at, level, message, owner, account_id
            FROM notifications
            ORDER BY created_at DESC
            LIMIT {limit_placeholder}
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
