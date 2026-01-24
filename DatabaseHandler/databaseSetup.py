import json
import secrets
import bcrypt
from datetime import datetime, timedelta

from backend.config import DATA_ENCRYPTION_KEY, MYSQLDATABASE, MYSQLHOST, MYSQLPASSWORD, MYSQLPORT, MYSQLUSER
from backend.logger import logger

import mysql.connector as mysql_connector

try:
    from cryptography.fernet import Fernet
except Exception:
    Fernet = None

_ENC_PREFIX = "enc:"


class _NoopConnection:
    def commit(self):
        return None

    def close(self):
        return None


class _CursorWrapper:
    def __init__(self, cursor, formatter, connection=None):
        self._cursor = cursor
        self._formatter = formatter
        self._connection = connection

    def execute(self, sql, params=None):
        if params is None:
            return self._cursor.execute(self._formatter(sql))
        return self._cursor.execute(self._formatter(sql), params)

    def executemany(self, sql, seq_of_params):
        return self._cursor.executemany(self._formatter(sql), seq_of_params)

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return getattr(self._cursor, "lastrowid", None)

    def close(self):
        try:
            return self._cursor.close()
        finally:
            if self._connection is not None:
                self._connection.close()


class MySQLDB:
    def __init__(self):
        self.db_type = "mysql"
        self.conn = _NoopConnection()
        self._fernet = None
        self._fernet_ready = False
        self.create_table()

    def _format_sql(self, sql: str) -> str:
        if self.db_type == "mysql":
            return sql.replace("?", "%s")
        return sql

    def _get_fernet(self):
        if self._fernet_ready:
            return self._fernet
        self._fernet_ready = True
        if not DATA_ENCRYPTION_KEY:
            return None
        if Fernet is None:
            logger.error("DATA_ENCRYPTION_KEY is set but cryptography is not installed.")
            return None
        try:
            self._fernet = Fernet(DATA_ENCRYPTION_KEY.encode("utf-8"))
        except Exception as exc:
            logger.error(f"Invalid DATA_ENCRYPTION_KEY: {exc}")
            self._fernet = None
        return self._fernet

    def _add_column_if_missing(self, table: str, column: str, ddl: str):
        cursor = self._cursor()
        try:
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s AND column_name = %s
                    """,
                    (MYSQLDATABASE, table, column),
                )
                exists = cursor.fetchone()[0] > 0
                if not exists:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
                    self.conn.commit()
            else:
                cursor.execute(f"PRAGMA table_info({table})")
                cols = {row[1] for row in cursor.fetchall()}
                if column not in cols:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
                    self.conn.commit()
        except Exception as exc:
            logger.error(f"Error adding column {column} to {table}: {exc}")
        finally:
            cursor.close()

    def _normalize_mafile(self, mafile_json):
        if mafile_json is None:
            return None
        if isinstance(mafile_json, str):
            return mafile_json
        try:
            return json.dumps(mafile_json)
        except Exception:
            return str(mafile_json)

    def _encrypt_value(self, value: str | None) -> str | None:
        if value is None:
            return None
        f = self._get_fernet()
        if not f:
            return value
        if value.startswith(_ENC_PREFIX):
            return value
        try:
            token = f.encrypt(value.encode("utf-8")).decode("utf-8")
            return f"{_ENC_PREFIX}{token}"
        except Exception as exc:
            logger.error(f"Failed to encrypt sensitive value: {exc}")
            return value

    def _decrypt_value(self, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            try:
                value = value.decode("utf-8")
            except Exception:
                value = str(value)
        if not value.startswith(_ENC_PREFIX):
            return value
        f = self._get_fernet()
        if not f:
            logger.error("Encrypted value found but DATA_ENCRYPTION_KEY is not set.")
            return None
        token = value[len(_ENC_PREFIX):]
        try:
            return f.decrypt(token.encode("utf-8")).decode("utf-8")
        except Exception as exc:
            logger.error(f"Failed to decrypt sensitive value: {exc}")
            return None

    def _cursor(self):
        if self.db_type == "mysql":
            conn = mysql_connector.connect(
                host=MYSQLHOST,
                port=MYSQLPORT,
                user=MYSQLUSER,
                password=MYSQLPASSWORD,
                database=MYSQLDATABASE,
                autocommit=True,
                use_pure=True,
            )
            return _CursorWrapper(conn.cursor(buffered=True), self._format_sql, connection=conn)
        return self.conn.cursor()

    def open_connection(self):
        if self.db_type == "mysql":
            if mysql_connector is None:
                raise RuntimeError("mysql-connector-python is required for MySQL support.")
            conn = mysql_connector.connect(
                host=MYSQLHOST,
                port=MYSQLPORT,
                user=MYSQLUSER,
                password=MYSQLPASSWORD,
                database=MYSQLDATABASE,
                autocommit=True,
                use_pure=True,
            )
            return conn, _CursorWrapper(conn.cursor(buffered=True), self._format_sql, connection=conn)
        raise RuntimeError("SQLite is not supported. Configure MySQL instead.")

    def create_table(self):
        """Create the 'accounts' table if it does not exist."""
        cursor = self._cursor()
        if self.db_type == "mysql":
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    ID INT AUTO_INCREMENT PRIMARY KEY,
                    account_name VARCHAR(255) NOT NULL UNIQUE,
                    path_to_maFile TEXT NOT NULL,
                    mafile_json LONGTEXT NULL,
                    login VARCHAR(255) NOT NULL,
                    password TEXT NOT NULL,
                    rental_duration INT NOT NULL,
                    rental_duration_minutes INT NULL,
                    mmr INT NULL,
                    owner VARCHAR(255) DEFAULT NULL,
                    rental_start DATETIME DEFAULT NULL,
                    account_frozen TINYINT(1) NOT NULL DEFAULT 0,
                    rental_frozen TINYINT(1) NOT NULL DEFAULT 0,
                    rental_frozen_at DATETIME NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS authorized_users (
                    user_id BIGINT PRIMARY KEY,
                    authorized_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS lots (
                    lot_number INT NOT NULL,
                    account_id INT NOT NULL,
                    lot_url TEXT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_id INT NOT NULL DEFAULT 0,
                    key_id INT NOT NULL DEFAULT 0,
                    PRIMARY KEY (lot_number, user_id, key_id),
                    UNIQUE KEY uniq_account_user (account_id, user_id, key_id),
                    FOREIGN KEY (account_id) REFERENCES accounts(ID) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    golden_key TEXT NOT NULL,
                    session_token VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_keys (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    label VARCHAR(255) NOT NULL,
                    golden_key TEXT NOT NULL,
                    is_default TINYINT(1) NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uniq_user_label (user_id, label),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id VARCHAR(128) PRIMARY KEY,
                    user_id INT NOT NULL,
                    expires_at DATETIME NOT NULL,
                    last_seen_at DATETIME NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_sessions_user (user_id),
                    INDEX idx_sessions_expires (expires_at),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    owner VARCHAR(255) NOT NULL,
                    role VARCHAR(16) NOT NULL,
                    message TEXT NOT NULL,
                    user_id INT NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_chat_owner_id (owner, id),
                    INDEX idx_chat_user_owner (user_id, owner)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_summaries (
                    owner VARCHAR(255) NOT NULL,
                    user_id INT NOT NULL DEFAULT 0,
                    summary TEXT NOT NULL,
                    last_message_id BIGINT NOT NULL DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (owner, user_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS order_history (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    order_id VARCHAR(32) NOT NULL,
                    owner VARCHAR(255) NOT NULL,
                    account_name VARCHAR(255) NULL,
                    account_id INT NULL,
                    steam_id VARCHAR(32) NULL,
                    rental_minutes INT NULL,
                    lot_number INT NULL,
                    amount INT DEFAULT 1,
                    price DECIMAL(10,2) NULL,
                    action VARCHAR(32) NOT NULL,
                    user_id INT NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_order_owner_created (owner, created_at),
                    INDEX idx_order_user_owner (user_id, owner),
                    INDEX idx_order_account (account_id),
                    INDEX idx_order_steam (steam_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS blacklist (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    owner VARCHAR(255) NOT NULL,
                    reason TEXT NULL,
                    user_id INT NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY idx_blacklist_owner_user (owner, user_id),
                    INDEX idx_blacklist_owner (owner)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_calls (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL DEFAULT 0,
                    chat_id BIGINT NOT NULL,
                    owner VARCHAR(255) NOT NULL,
                    count INT NOT NULL DEFAULT 0,
                    last_called_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY idx_admin_calls_user_chat (user_id, chat_id),
                    INDEX idx_admin_calls_user_owner (user_id, owner)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        else:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_name TEXT NOT NULL UNIQUE,
                    path_to_maFile TEXT NOT NULL,
                    mafile_json TEXT,
                    login TEXT NOT NULL,
                    password TEXT NOT NULL,
                    rental_duration INTEGER NOT NULL,
                    rental_duration_minutes INTEGER,
                    mmr INTEGER,
                    owner TEXT DEFAULT NULL,
                    rental_start TIMESTAMP DEFAULT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS authorized_users (
                    user_id INTEGER PRIMARY KEY,
                    authorized_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS lots (
                    lot_number INTEGER NOT NULL,
                    account_id INTEGER NOT NULL,
                    lot_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_id INTEGER NOT NULL DEFAULT 0,
                    key_id INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (lot_number, user_id, key_id),
                    UNIQUE(account_id, user_id, key_id),
                    FOREIGN KEY (account_id) REFERENCES accounts(ID) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    golden_key TEXT NOT NULL,
                    session_token TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    golden_key TEXT NOT NULL,
                    is_default INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, label)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    last_seen_at TIMESTAMP NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner TEXT NOT NULL,
                    role TEXT NOT NULL,
                    message TEXT NOT NULL,
                    user_id INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_summaries (
                    owner TEXT NOT NULL,
                    user_id INTEGER NOT NULL DEFAULT 0,
                    summary TEXT NOT NULL,
                    last_message_id INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (owner, user_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS order_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    account_name TEXT,
                    account_id INTEGER,
                    steam_id TEXT,
                    rental_minutes INTEGER,
                    lot_number INTEGER,
                    amount INTEGER DEFAULT 1,
                    price REAL,
                    action TEXT NOT NULL,
                    user_id INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS blacklist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner TEXT NOT NULL,
                    reason TEXT,
                    user_id INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(owner, user_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL DEFAULT 0,
                    chat_id INTEGER NOT NULL,
                    owner TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    last_called_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, chat_id)
                )
                """
            )
        self.conn.commit()
        cursor.close()
        self._ensure_mafile_column()
        self._ensure_rental_duration_minutes_column()
        self._ensure_mmr_column()
        self._ensure_account_freeze_columns()
        self._ensure_lot_url_column()
        self._ensure_users_table()
        self._ensure_user_owner_columns()
        self._ensure_feedback_rewards_table()
        self._ensure_feedback_rewards_user_column()
        self._ensure_blacklist_table()
        self._ensure_blacklist_logs_table()
        self._ensure_admin_calls_table()
        self._ensure_settings_table()
        self._ensure_chat_columns()
        self._ensure_support_tickets_table()
        self._ensure_feedback_rewards_revoked_column()
        self._ensure_funpay_balance_table()
        self._ensure_order_history_columns()
        self._migrate_lots_schema()
        self._ensure_user_keys_default()
        self._ensure_user_keys_proxy_columns()
        self._ensure_key_columns()
        self._ensure_account_name_not_unique()
        self._ensure_account_order_column()

    def _ensure_mafile_column(self):
        cursor = self._cursor()
        try:
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.columns
                    WHERE table_schema = ? AND table_name = 'accounts' AND column_name = 'mafile_json'
                    """,
                    (MYSQLDATABASE,),
                )
                exists = cursor.fetchone()[0] > 0
                if not exists:
                    cursor.execute("ALTER TABLE accounts ADD COLUMN mafile_json LONGTEXT NULL")
                    self.conn.commit()
            else:
                cursor.execute("ALTER TABLE accounts ADD COLUMN mafile_json TEXT")
                self.conn.commit()
        except Exception:
            pass
        finally:
            cursor.close()

    def _ensure_rental_duration_minutes_column(self):
        cursor = self._cursor()
        try:
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.columns
                    WHERE table_schema = ? AND table_name = 'accounts' AND column_name = 'rental_duration_minutes'
                    """,
                    (MYSQLDATABASE,),
                )
                exists = cursor.fetchone()[0] > 0
                if not exists:
                    cursor.execute("ALTER TABLE accounts ADD COLUMN rental_duration_minutes INT NULL")
                    self.conn.commit()
            else:
                cursor.execute("ALTER TABLE accounts ADD COLUMN rental_duration_minutes INTEGER")
                self.conn.commit()
        except Exception:
            pass
        finally:
            cursor.close()

    def _ensure_users_table(self):
        cursor = self._cursor()
        try:
            if self.db_type == "mysql":
                # create if missing
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        username VARCHAR(255) NOT NULL UNIQUE,
                        password_hash VARCHAR(255) NOT NULL,
                        golden_key TEXT NOT NULL,
                        session_token VARCHAR(255),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                # ensure columns exist
                cursor.execute(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = ? AND table_name = 'users'
                    """,
                    (MYSQLDATABASE,),
                )
                cols = {row[0] for row in cursor.fetchall()}
                needed = {
                    "username": "ALTER TABLE users ADD COLUMN username VARCHAR(255) NOT NULL UNIQUE",
                    "password_hash": "ALTER TABLE users ADD COLUMN password_hash VARCHAR(255) NOT NULL",
                    "golden_key": "ALTER TABLE users ADD COLUMN golden_key TEXT NOT NULL",
                    "session_token": "ALTER TABLE users ADD COLUMN session_token VARCHAR(255)",
                    "created_at": "ALTER TABLE users ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                }
                for col, stmt in needed.items():
                    if col not in cols:
                        cursor.execute(stmt)
                self.conn.commit()
            else:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        golden_key TEXT NOT NULL,
                        session_token TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                cursor.execute("PRAGMA table_info(users)")
                cols = {row[1] for row in cursor.fetchall()}
                alter = {
                    "username": "ALTER TABLE users ADD COLUMN username TEXT",
                    "password_hash": "ALTER TABLE users ADD COLUMN password_hash TEXT",
                    "golden_key": "ALTER TABLE users ADD COLUMN golden_key TEXT",
                    "session_token": "ALTER TABLE users ADD COLUMN session_token TEXT",
                    "created_at": "ALTER TABLE users ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                }
                for col, stmt in alter.items():
                    if col not in cols:
                        cursor.execute(stmt)
                self.conn.commit()
        except Exception:
            # best effort; ignore if cannot migrate
            pass
        finally:
            cursor.close()

    def _ensure_lot_url_column(self):
        cursor = self._cursor()
        try:
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.columns
                    WHERE table_schema = ? AND table_name = 'lots' AND column_name = 'lot_url'
                    """,
                    (MYSQLDATABASE,),
                )
                exists = cursor.fetchone()[0] > 0
                if not exists:
                    cursor.execute("ALTER TABLE lots ADD COLUMN lot_url TEXT NULL")
                    self.conn.commit()
            else:
                cursor.execute("ALTER TABLE lots ADD COLUMN lot_url TEXT")
                self.conn.commit()
        except Exception:
            pass
        finally:
            cursor.close()

    def _ensure_mmr_column(self):
        cursor = self._cursor()
        try:
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.columns
                    WHERE table_schema = ? AND table_name = 'accounts' AND column_name = 'mmr'
                    """,
                    (MYSQLDATABASE,),
                )
                exists = cursor.fetchone()[0] > 0
                if not exists:
                    cursor.execute("ALTER TABLE accounts ADD COLUMN mmr INT NULL")
                    self.conn.commit()
            else:
                cursor.execute("ALTER TABLE accounts ADD COLUMN mmr INTEGER")
                self.conn.commit()
        except Exception:
            pass
        finally:
            cursor.close()

    def _ensure_feedback_rewards_table(self):
        cursor = self._cursor()
        try:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback_rewards (
                    order_id VARCHAR(16) PRIMARY KEY,
                    owner VARCHAR(255) NOT NULL,
                    user_id INT NOT NULL DEFAULT 0,
                    rating INT NOT NULL,
                    review_text TEXT DEFAULT NULL,
                    reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    claimed_at TIMESTAMP NULL,
                    account_id INT DEFAULT NULL,
                    revoked_at TIMESTAMP NULL
                )
                """
            )
            self.conn.commit()
        except Exception:
            pass
        finally:
            cursor.close()

    def _ensure_account_freeze_columns(self):
        cursor = self._cursor()
        try:
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = ? AND table_name = 'accounts'
                    """,
                    (MYSQLDATABASE,),
                )
                cols = {row[0] for row in cursor.fetchall()}
                if "account_frozen" not in cols:
                    cursor.execute(
                        "ALTER TABLE accounts ADD COLUMN account_frozen TINYINT(1) NOT NULL DEFAULT 0"
                    )
                if "rental_frozen" not in cols:
                    cursor.execute(
                        "ALTER TABLE accounts ADD COLUMN rental_frozen TINYINT(1) NOT NULL DEFAULT 0"
                    )
                if "rental_frozen_at" not in cols:
                    cursor.execute("ALTER TABLE accounts ADD COLUMN rental_frozen_at DATETIME NULL")
                self.conn.commit()
            else:
                cursor.execute("PRAGMA table_info(accounts)")
                cols = {row[1] for row in cursor.fetchall()}
                if "account_frozen" not in cols:
                    cursor.execute(
                        "ALTER TABLE accounts ADD COLUMN account_frozen INTEGER NOT NULL DEFAULT 0"
                    )
                if "rental_frozen" not in cols:
                    cursor.execute(
                        "ALTER TABLE accounts ADD COLUMN rental_frozen INTEGER NOT NULL DEFAULT 0"
                    )
                if "rental_frozen_at" not in cols:
                    cursor.execute("ALTER TABLE accounts ADD COLUMN rental_frozen_at TIMESTAMP NULL")
                self.conn.commit()
        except Exception:
            pass
        finally:
            cursor.close()

    def _ensure_feedback_rewards_user_column(self):
        cursor = self._cursor()
        try:
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.columns
                    WHERE table_schema = ? AND table_name = 'feedback_rewards' AND column_name = 'user_id'
                    """,
                    (MYSQLDATABASE,),
                )
                exists = cursor.fetchone()[0] > 0
                if not exists:
                    cursor.execute("ALTER TABLE feedback_rewards ADD COLUMN user_id INT NOT NULL DEFAULT 0")
                    self.conn.commit()
            else:
                cursor.execute("PRAGMA table_info(feedback_rewards)")
                cols = {row[1] for row in cursor.fetchall()}
                if "user_id" not in cols:
                    cursor.execute("ALTER TABLE feedback_rewards ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0")
                    self.conn.commit()
        except Exception:
            pass
        finally:
            cursor.close()

    def _ensure_funpay_balance_table(self):
        cursor = self._cursor()
        try:
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS funpay_balance_snapshots (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL DEFAULT 0,
                        total_rub DECIMAL(12,2) NULL,
                        available_rub DECIMAL(12,2) NULL,
                        total_usd DECIMAL(12,2) NULL,
                        total_eur DECIMAL(12,2) NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_balance_user_created (user_id, created_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
            else:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS funpay_balance_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL DEFAULT 0,
                        total_rub REAL,
                        available_rub REAL,
                        total_usd REAL,
                        total_eur REAL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            self.conn.commit()
        except Exception:
            pass
        finally:
            cursor.close()

    def _ensure_user_keys_default(self):
        cursor = self._cursor()
        try:
            cursor.execute("SELECT id, golden_key FROM users")
            rows = cursor.fetchall()
            for row in rows:
                uid = row[0]
                gk = row[1]
                self.ensure_user_keys_for_user(uid, gk)
        except Exception as exc:
            logger.error(f"Error ensuring default user keys: {exc}")
        finally:
            cursor.close()

    def _ensure_user_keys_proxy_columns(self):
        self._add_column_if_missing("user_keys", "proxy_url", "TEXT")
        self._add_column_if_missing("user_keys", "proxy_username", "TEXT")
        self._add_column_if_missing("user_keys", "proxy_password", "TEXT")

    def _ensure_account_order_column(self):
        self._add_column_if_missing("accounts", "rental_order_id", "TEXT")

    def _ensure_key_columns(self):
        self._add_column_if_missing("accounts", "key_id", "INT NULL")
        self._add_column_if_missing("lots", "key_id", "INT NOT NULL DEFAULT 0")
        self._add_column_if_missing("blacklist", "key_id", "INT NULL")
        self._add_column_if_missing("order_history", "key_id", "INT NULL")
        self._add_column_if_missing("admin_calls", "key_id", "INT NULL")
        self._add_column_if_missing("funpay_balance_snapshots", "key_id", "INT NULL")
        self._add_column_if_missing("accounts", "rental_order_id", "TEXT")

    def _ensure_account_name_not_unique(self):
        if self.db_type != "mysql":
            return
        cursor = self._cursor()
        try:
            cursor.execute(
                """
                SELECT INDEX_NAME, NON_UNIQUE
                FROM information_schema.statistics
                WHERE table_schema = %s AND table_name = 'accounts' AND column_name = 'account_name'
                """,
                (MYSQLDATABASE,),
            )
            for index_name, non_unique in cursor.fetchall():
                if index_name == "PRIMARY":
                    continue
                if int(non_unique) == 0:
                    try:
                        cursor.execute(f"ALTER TABLE accounts DROP INDEX {index_name}")
                    except Exception:
                        pass
            self.conn.commit()
        except Exception as exc:
            logger.error(f"Error ensuring account_name is non-unique: {exc}")
        finally:
            cursor.close()

    def _ensure_blacklist_table(self):
        cursor = self._cursor()
        try:
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS blacklist (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        owner VARCHAR(255) NOT NULL,
                        reason TEXT NULL,
                        user_id INT NOT NULL DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY idx_blacklist_owner_user (owner, user_id),
                        INDEX idx_blacklist_owner (owner)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
            else:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS blacklist (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        owner TEXT NOT NULL,
                        reason TEXT,
                        user_id INTEGER NOT NULL DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(owner, user_id)
                    )
                    """
                )
            self.conn.commit()
        except Exception:
            pass
        finally:
            cursor.close()

    def _ensure_blacklist_logs_table(self):
        cursor = self._cursor()
        try:
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS blacklist_logs (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        owner VARCHAR(255) NOT NULL,
                        action VARCHAR(32) NOT NULL,
                        reason TEXT NULL,
                        details TEXT NULL,
                        user_id INT NOT NULL DEFAULT 0,
                        key_id INT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_bl_logs_user (user_id, key_id),
                        INDEX idx_bl_logs_owner (owner, user_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
            else:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS blacklist_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        owner TEXT NOT NULL,
                        action TEXT NOT NULL,
                        reason TEXT NULL,
                        details TEXT NULL,
                        user_id INTEGER NOT NULL DEFAULT 0,
                        key_id INTEGER NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            self.conn.commit()
        except Exception:
            pass
        finally:
            cursor.close()

    def _ensure_admin_calls_table(self):
        cursor = self._cursor()
        try:
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS admin_calls (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL DEFAULT 0,
                        chat_id BIGINT NOT NULL,
                        owner VARCHAR(255) NOT NULL,
                        count INT NOT NULL DEFAULT 0,
                        last_called_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY idx_admin_calls_user_chat (user_id, chat_id),
                        INDEX idx_admin_calls_user_owner (user_id, owner)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
            else:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS admin_calls (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL DEFAULT 0,
                        chat_id INTEGER NOT NULL,
                        owner TEXT NOT NULL,
                        count INTEGER NOT NULL DEFAULT 0,
                        last_called_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(user_id, chat_id)
                    )
                    """
                )
            self.conn.commit()
        except Exception:
            pass
        finally:
            cursor.close()

    def _ensure_settings_table(self):
        cursor = self._cursor()
        try:
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS settings (
                        `key` VARCHAR(255) PRIMARY KEY,
                        `value` TEXT NULL
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
            else:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NULL
                    )
                    """
                )
            self.conn.commit()
        except Exception as exc:
            logger.error(f"Error ensuring settings table: {exc}")
        finally:
            cursor.close()

    def set_setting(self, key: str, value: str | None) -> bool:
        cursor = self._cursor()
        try:
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    INSERT INTO settings (`key`, `value`) VALUES (?, ?)
                    ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)
                    """,
                    (key, value),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO settings (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, value),
                )
            self.conn.commit()
            return True
        except Exception as exc:
            logger.error(f"Error setting setting {key}: {exc}")
            return False
        finally:
            cursor.close()

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        cursor = self._cursor()
        try:
            cursor.execute("SELECT `value` FROM settings WHERE `key` = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row and row[0] is not None else default
        except Exception as exc:
            logger.error(f"Error getting setting {key}: {exc}")
            return default
        finally:
            cursor.close()

    def get_setting_bool(self, key: str, default: bool = False) -> bool:
        val = self.get_setting(key, None)
        if val is None:
            return default
        return str(val).strip().lower() in {"1", "true", "yes", "on"}

    def set_setting_bool(self, key: str, value: bool) -> bool:
        return self.set_setting(key, "1" if value else "0")

    def _ensure_feedback_rewards_revoked_column(self):
        cursor = self._cursor()
        try:
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.columns
                    WHERE table_schema = ? AND table_name = 'feedback_rewards' AND column_name = 'revoked_at'
                    """,
                    (MYSQLDATABASE,),
                )
                exists = cursor.fetchone()[0] > 0
                if not exists:
                    cursor.execute("ALTER TABLE feedback_rewards ADD COLUMN revoked_at TIMESTAMP NULL")
                    self.conn.commit()
            else:
                cursor.execute("ALTER TABLE feedback_rewards ADD COLUMN revoked_at TIMESTAMP")
                self.conn.commit()
        except Exception:
            pass
        finally:
            cursor.close()
    def add_account(
        self,
        account_name,
        path_to_maFile,
        login,
        password,
        duration,
        owner=None,
        mafile_json=None,
        user_id: int | None = None,
        duration_minutes: int | None = None,
        mmr: int | None = None,
        key_id: int | None = None,
    ):
        """Add an account to the database."""
        cursor = None
        try:
            # Проверяем, не существует ли уже аккаунт с таким названием
            existing_account = self.get_account_by_name(account_name, user_id=user_id, key_id=key_id)
            if existing_account:
                logger.error(f"Account with name '{account_name}' already exists!")
                return False
            
            if not path_to_maFile and mafile_json:
                path_to_maFile = ""

            try:
                duration_value = int(duration) if duration is not None else 0
            except Exception:
                duration_value = 0
            if duration_minutes is None:
                total_minutes = duration_value * 60
            else:
                try:
                    total_minutes = int(duration_minutes)
                except Exception:
                    total_minutes = duration_value * 60

            if mafile_json is not None:
                mafile_json = self._normalize_mafile(mafile_json)
            enc_password = self._encrypt_value(password)
            enc_mafile = self._encrypt_value(mafile_json)
            if key_id is None and user_id is not None:
                default_key = self.get_default_key(user_id)
                if default_key and default_key.get("id"):
                    key_id = int(default_key["id"])

            cursor = self._cursor()
            cursor.execute(
                """
                INSERT INTO accounts (
                    account_name, path_to_maFile, mafile_json, login, password, rental_duration, rental_duration_minutes, mmr, owner, user_id, key_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_name,
                    path_to_maFile,
                    enc_mafile,
                    login,
                    enc_password,
                    duration_value,
                    total_minutes,
                    mmr,
                    owner,
                    user_id,
                    key_id,
                ),
            )
            self.conn.commit()
            logger.info(f"Account '{account_name}' added successfully")
            return True
        except Exception as e:
            logger.error(f"Error adding account: {str(e)}")
            return False
        finally:
            if cursor:
                cursor.close()

    def get_unowned_accounts(self):
        """Retrieve all accounts with no owner assigned."""
        cursor = self._cursor()
        cursor.execute(
            """
            SELECT ID, account_name, path_to_maFile, login, password, rental_duration, rental_duration_minutes, mmr
            FROM accounts 
            WHERE owner IS NULL AND (account_frozen = 0 OR account_frozen IS NULL)
            """
        )
        rows = cursor.fetchall()
        cursor.close()
        accounts = [
            {
                "id": row[0],
                "account_name": row[1],
                "path_to_maFile": row[2],
                "login": row[3],
                "password": self._decrypt_value(row[4]),
                "rental_duration": row[5],
                "rental_duration_minutes": row[6],
                "mmr": row[7],
            }
            for row in rows
        ]
        return accounts

    def set_account_owner(
        self,
        account_id: int,
        owner_id: str,
        user_id: int | None = None,
        start_rental: bool = True,
        key_id: int | None = None,
        order_id: str | None = None,
    ) -> bool:
        """
        Set the owner of an account and optionally record the rental start time with a +3 hours offset.
        Also marks all accounts with the same login as 'OTHER_ACCOUNT'.
        """
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            rental_start = None
            if start_rental:
                rental_start = (datetime.utcnow() + timedelta(hours=3)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            order_clause = ", rental_order_id = ?" if order_id is not None else ""
            order_params: tuple = (order_id,) if order_id is not None else ()
            # Update owner and set rental start time
            if user_id in (None, 0):
                if start_rental:
                    cursor.execute(
                        f"""
                        UPDATE accounts 
                        SET owner = ?, rental_start = ?{order_clause}
                        WHERE ID = ? AND owner IS NULL AND (account_frozen = 0 OR account_frozen IS NULL){key_clause}
                        """,
                        (owner_id, rental_start, *order_params, account_id, *key_params),
                    )
                else:
                    cursor.execute(
                        f"""
                        UPDATE accounts 
                        SET owner = ?{order_clause}
                        WHERE ID = ? AND owner IS NULL AND (account_frozen = 0 OR account_frozen IS NULL){key_clause}
                        """,
                        (owner_id, *order_params, account_id, *key_params),
                    )
            else:
                if start_rental:
                    cursor.execute(
                        f"""
                        UPDATE accounts 
                        SET owner = ?, rental_start = ?{order_clause}
                        WHERE ID = ? AND owner IS NULL AND user_id = ?
                          AND (account_frozen = 0 OR account_frozen IS NULL){key_clause}
                        """,
                        (owner_id, rental_start, *order_params, account_id, user_id, *key_params),
                    )
                else:
                    cursor.execute(
                        f"""
                        UPDATE accounts 
                        SET owner = ?{order_clause}
                        WHERE ID = ? AND owner IS NULL AND user_id = ?
                          AND (account_frozen = 0 OR account_frozen IS NULL){key_clause}
                        """,
                        (owner_id, *order_params, account_id, user_id, *key_params),
                    )
            if cursor.rowcount == 0:
                return False
            # Get the login of the updated account
            if user_id in (None, 0):
                cursor.execute(
                    f"""
                    SELECT login 
                    FROM accounts 
                    WHERE ID = ?{key_clause}
                    """,
                    (account_id, *key_params),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT login 
                    FROM accounts 
                    WHERE ID = ? AND user_id = ?{key_clause}
                    """,
                    (account_id, user_id, *key_params),
                )
            login_row = cursor.fetchone()
            if login_row:
                login = login_row[0]
                # Mark all accounts with the same login as 'OTHER_ACCOUNT'
                if user_id in (None, 0):
                    cursor.execute(
                        f"""
                        UPDATE accounts 
                        SET owner = 'OTHER_ACCOUNT'
                        WHERE login = ? AND owner IS NULL{key_clause}
                        """,
                        (login, *key_params),
                    )
                else:
                    cursor.execute(
                        f"""
                        UPDATE accounts 
                        SET owner = 'OTHER_ACCOUNT'
                        WHERE login = ? AND owner IS NULL AND user_id = ?{key_clause}
                        """,
                        (login, user_id, *key_params),
                    )
            if order_id:
                cursor.execute(
                    f"""
                    UPDATE accounts
                    SET rental_order_id = ?
                    WHERE ID = ?{key_clause}
                    """,
                    (order_id, account_id, *key_params),
                )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error setting account owner: {str(e)}")
            return False
        finally:
            cursor.close()

    def get_active_owners(self):
        """Retrieve all unique owner IDs where owner is not NULL."""
        cursor = self._cursor()
        cursor.execute(
            """
            SELECT DISTINCT owner 
            FROM accounts 
            WHERE owner IS NOT NULL
            """
        )
        owners = [row[0] for row in cursor.fetchall()]
        cursor.close()
        return owners

    def get_owner_mafile(
        self, owner_id: str, user_id: int | None = None, key_id: int | None = None
    ) -> list:
        """
        Retrieve the .maFile path and account details from the most recent account
        associated with the given owner ID.
        """
        key_clause, key_params = self._key_filter(key_id, "key_id")
        cursor = self._cursor()
        if user_id in (None, 0):
            cursor.execute(
                f"""
                SELECT ID, account_name, path_to_maFile, mafile_json, login, rental_duration
                FROM accounts 
                WHERE owner = ? AND (account_frozen = 0 OR account_frozen IS NULL)
                  AND (rental_frozen = 0 OR rental_frozen IS NULL){key_clause}
                ORDER BY rental_start DESC
                """,
                (owner_id, *key_params),
            )
        else:
            cursor.execute(
                f"""
                SELECT ID, account_name, path_to_maFile, mafile_json, login, rental_duration
                FROM accounts 
                WHERE owner = ? AND user_id = ? AND (account_frozen = 0 OR account_frozen IS NULL)
                  AND (rental_frozen = 0 OR rental_frozen IS NULL){key_clause}
                ORDER BY rental_start DESC
                """,
                (owner_id, int(user_id), *key_params),
            )
        rows = cursor.fetchall()
        cursor.close()
        return [
            (row[0], row[1], row[2], self._decrypt_value(row[3]), row[4], row[5])
            for row in rows
        ]

    def owner_has_frozen_rental(
        self, owner_id: str, user_id: int | None = None, key_id: int | None = None
    ) -> bool:
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            values: list[Any] = [str(owner_id)]
            where_user = ""
            if user_id not in (None, 0):
                where_user = " AND user_id = ?"
                values.append(int(user_id))
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM accounts
                WHERE owner = ?
                  AND (account_frozen = 1 OR rental_frozen = 1)
                  {where_user}{key_clause}
                """,
                values + key_params,
            )
            return cursor.fetchone()[0] > 0
        except Exception as exc:
            logger.error(f"Error checking frozen rentals for {owner_id}: {exc}")
            return False
        finally:
            cursor.close()

    def update_password_by_owner(self, owner_name: str, new_password: str) -> bool:
        """
        Update the password for the most recent account owned by the specified owner.
        """
        try:
            enc_password = self._encrypt_value(new_password)
            cursor = self._cursor()
            cursor.execute(
                """
                UPDATE accounts 
                SET password = ?
                WHERE owner = ? 
                AND rental_start = (
                    SELECT MAX(rental_start) 
                    FROM accounts 
                    WHERE owner = ?
                )
                """,
                (enc_password, owner_name, owner_name),
            )
            success = cursor.rowcount > 0
            self.conn.commit()
            return success
        except Exception as e:
            logger.error(f"Error updating password: {str(e)}")
            return False
        finally:
            cursor.close()

    def get_active_owners_with_mafiles(self):
        """
        Retrieve all unique owner IDs and their associated maFile paths,
        based on the most recent rental_start for each owner.
        """
        cursor = self._cursor()
        cursor.execute(
            """
            SELECT DISTINCT a.owner, a.path_to_maFile, a.mafile_json
            FROM accounts a
            INNER JOIN (
                SELECT owner, MAX(rental_start) as latest_rental
                FROM accounts
                WHERE owner IS NOT NULL
                GROUP BY owner
            ) b ON a.owner = b.owner AND a.rental_start = b.latest_rental
            """
        )
        owners_data = cursor.fetchall()
        cursor.close()
        return [(row[0], row[1], self._decrypt_value(row[2])) for row in owners_data]

    def get_all_accounts(self, user_id: int | None = None, key_id: int | None = None):
        """Retrieve all accounts from the database."""
        cursor = self._cursor()
        if user_id is None:
            cursor.execute(
                """
                SELECT ID, account_name, path_to_maFile, login, password, rental_duration, rental_duration_minutes, mmr, owner, rental_start, user_id, mafile_json, account_frozen, rental_frozen, rental_frozen_at, key_id
                FROM accounts
                """
            )
        else:
            if key_id is None:
                cursor.execute(
                    """
                    SELECT ID, account_name, path_to_maFile, login, password, rental_duration, rental_duration_minutes, mmr, owner, rental_start, user_id, mafile_json, account_frozen, rental_frozen, rental_frozen_at, key_id
                    FROM accounts
                    WHERE user_id = ?
                    """,
                    (user_id,),
                )
            else:
                key_clause, key_params = self._key_filter(key_id, "key_id")
                cursor.execute(
                    f"""
                    SELECT ID, account_name, path_to_maFile, login, password, rental_duration, rental_duration_minutes, mmr, owner, rental_start, user_id, mafile_json, account_frozen, rental_frozen, rental_frozen_at, key_id
                    FROM accounts
                    WHERE user_id = ?{key_clause}
                    """,
                    (user_id, *key_params),
                )
        rows = cursor.fetchall()
        cursor.close()
        accounts = [
            {
                "id": row[0],
                "account_name": row[1],
                "path_to_maFile": row[2],
                "login": row[3],
                "password": self._decrypt_value(row[4]),
                "rental_duration": row[5],
                "rental_duration_minutes": row[6],
                "mmr": row[7],
                "owner": row[8],
                "rental_start": row[9],
                "user_id": row[10] if len(row) > 10 else None,
                "mafile_json": self._decrypt_value(row[11]) if len(row) > 11 else None,
                "account_frozen": row[12] if len(row) > 12 else 0,
                "rental_frozen": row[13] if len(row) > 13 else 0,
                "rental_frozen_at": row[14] if len(row) > 14 else None,
                "key_id": row[15] if len(row) > 15 else None,
            }
            for row in rows
        ]
        return accounts

    def get_all_accounts_light(self, user_id: int | None = None, key_id: int | None = None):
        cursor = self._cursor()
        if user_id is None:
            cursor.execute(
                """
                SELECT ID, account_name, login, rental_duration, rental_duration_minutes, mmr, owner, rental_start,
                       account_frozen, rental_frozen, rental_frozen_at, key_id
                FROM accounts
                """
            )
        else:
            if key_id is None:
                cursor.execute(
                    """
                    SELECT ID, account_name, login, rental_duration, rental_duration_minutes, mmr, owner, rental_start,
                           account_frozen, rental_frozen, rental_frozen_at, key_id
                    FROM accounts
                    WHERE user_id = ?
                    """,
                    (user_id,),
                )
            else:
                key_clause, key_params = self._key_filter(key_id, "key_id")
                cursor.execute(
                    f"""
                    SELECT ID, account_name, login, rental_duration, rental_duration_minutes, mmr, owner, rental_start,
                           account_frozen, rental_frozen, rental_frozen_at, key_id
                    FROM accounts
                    WHERE user_id = ?{key_clause}
                    """,
                    (user_id, *key_params),
                )
        rows = cursor.fetchall()
        cursor.close()
        return [
            {
                "id": row[0],
                "account_name": row[1],
                "login": row[2],
                "rental_duration": row[3],
                "rental_duration_minutes": row[4],
                "mmr": row[5],
                "owner": row[6],
                "rental_start": row[7],
                "account_frozen": row[8] if len(row) > 8 else 0,
                "rental_frozen": row[9] if len(row) > 9 else 0,
                "rental_frozen_at": row[10] if len(row) > 10 else None,
                "key_id": row[11] if len(row) > 11 else None,
            }
            for row in rows
        ]

    def list_lot_mappings(self, user_id: int | None = None, key_id: int | None = None) -> list:
        cursor = self._cursor()
        if user_id is None:
            cursor.execute(
                """
                SELECT l.lot_number, l.account_id, l.lot_url, a.account_name, a.owner, l.key_id
                FROM lots l
                JOIN accounts a ON a.ID = l.account_id
                ORDER BY l.lot_number
                """
            )
        else:
            if key_id is None:
                cursor.execute(
                    """
                    SELECT l.lot_number, l.account_id, l.lot_url, a.account_name, a.owner, l.key_id
                    FROM lots l
                    JOIN accounts a ON a.ID = l.account_id
                    WHERE l.user_id = ?
                    ORDER BY l.lot_number
                    """,
                    (user_id,),
                )
            else:
                key_clause, key_params = self._key_filter(key_id, "l.key_id")
                cursor.execute(
                    f"""
                    SELECT l.lot_number, l.account_id, l.lot_url, a.account_name, a.owner, l.key_id
                    FROM lots l
                    JOIN accounts a ON a.ID = l.account_id
                    WHERE l.user_id = ?{key_clause}
                    ORDER BY l.lot_number
                    """,
                    (user_id, *key_params),
                )
        rows = cursor.fetchall()
        if self.db_type == "mysql":
            cursor.close()
        return [
            {
                "lot_number": row[0],
                "account_id": row[1],
                "lot_url": row[2],
                "account_name": row[3],
                "owner": row[4],
                "key_id": row[5] if len(row) > 5 else None,
            }
            for row in rows
        ]

    def set_lot_mapping(self, lot_number: int, account_id: int, lot_url: str | None = None, user_id: int | None = None, key_id: int | None = None) -> bool:
        cursor = self._cursor()
        try:
            effective_user_id = user_id if user_id is not None else 0
            if key_id is None:
                if effective_user_id:
                    default_key = self.get_default_key(effective_user_id)
                    effective_key_id = int(default_key["id"]) if default_key and default_key.get("id") else 0
                else:
                    effective_key_id = 0
            else:
                effective_key_id = int(key_id)
            if user_id is None:
                cursor.execute(
                    "SELECT ID FROM accounts WHERE ID = ?",
                    (account_id,),
                )
            else:
                cursor.execute(
                    "SELECT ID FROM accounts WHERE ID = ? AND user_id = ?",
                    (account_id, user_id),
                )
            if cursor.fetchone() is None:
                return False
            # Upsert mapping per user
            cursor.execute(
                "REPLACE INTO lots (lot_number, account_id, lot_url, user_id, key_id) VALUES (?, ?, ?, ?, ?)",
                (lot_number, account_id, lot_url, effective_user_id, effective_key_id),
            )
            self.conn.commit()
            return True
        finally:
            if self.db_type == "mysql":
                cursor.close()

    def delete_lot_mapping(
        self, lot_number: int, user_id: int | None = None, key_id: int | None = None
    ) -> None:
        cursor = self._cursor()
        key_clause, key_params = self._key_filter(key_id, "key_id")
        if user_id in (None, 0):
            cursor.execute(
                f"DELETE FROM lots WHERE lot_number = ?{key_clause}",
                (lot_number, *key_params),
            )
        else:
            cursor.execute(
                f"DELETE FROM lots WHERE lot_number = ? AND user_id = ?{key_clause}",
                (lot_number, user_id, *key_params),
            )
        if self.db_type == "mysql":
            cursor.close()

    def get_lot_mapping(
        self, lot_number: int, user_id: int | None = None, key_id: int | None = None
    ):
        cursor = self._cursor()
        key_clause, key_params = self._key_filter(key_id, "l.key_id")
        if user_id in (None, 0):
            cursor.execute(
                f"""
                SELECT l.lot_number, l.account_id, l.lot_url, a.account_name
                FROM lots l
                JOIN accounts a ON a.ID = l.account_id
                WHERE l.lot_number = ?{key_clause}
                """,
                (lot_number, *key_params),
            )
        else:
            cursor.execute(
                f"""
                SELECT l.lot_number, l.account_id, l.lot_url, a.account_name
                FROM lots l
                JOIN accounts a ON a.ID = l.account_id
                WHERE l.lot_number = ? AND l.user_id = ?{key_clause}
                """,
                (lot_number, user_id, *key_params),
            )
        row = cursor.fetchone()
        if self.db_type == "mysql":
            cursor.close()
        if not row:
            return None
        return {
            "lot_number": row[0],
            "account_id": row[1],
            "lot_url": row[2],
            "account_name": row[3],
        }

    def get_account_by_lot_number(
        self, lot_number: int, user_id: int | None = None, key_id: int | None = None
    ):
        cursor = self._cursor()
        key_clause, key_params = self._key_filter(key_id, "l.key_id")
        if user_id is None:
            cursor.execute(
                f"""
                SELECT a.ID, a.account_name, a.login, a.password, a.rental_duration, a.rental_duration_minutes, a.mmr, a.owner, a.rental_start, a.mafile_json
                FROM lots l
                JOIN accounts a ON a.ID = l.account_id
                WHERE l.lot_number = ?{key_clause}
                """,
                (lot_number, *key_params),
            )
        else:
            cursor.execute(
                f"""
                SELECT a.ID, a.account_name, a.login, a.password, a.rental_duration, a.rental_duration_minutes, a.mmr, a.owner, a.rental_start, a.mafile_json
                FROM lots l
                JOIN accounts a ON a.ID = l.account_id
                WHERE l.lot_number = ? AND l.user_id = ?{key_clause}
                """,
                (lot_number, user_id, *key_params),
            )
        row = cursor.fetchone()
        if self.db_type == "mysql":
            cursor.close()
        if not row:
            return None
        return {
            "id": row[0],
            "account_name": row[1],
            "login": row[2],
            "password": self._decrypt_value(row[3]),
            "rental_duration": row[4],
            "rental_duration_minutes": row[5],
            "mmr": row[6],
            "owner": row[7],
            "rental_start": row[8],
            "mafile_json": self._decrypt_value(row[9]),
        }

    def get_available_lot_accounts(
        self, user_id: int | None = None, key_id: int | None = None
    ) -> list:
        cursor = self._cursor()
        key_clause_accounts, key_params_accounts = self._key_filter(key_id, "a.key_id")
        key_clause_lots, key_params_lots = self._key_filter(key_id, "l.key_id")
        filter_existing = ""
        filter_params: list = []
        if user_id is not None:
            filter_existing = " AND l.key_id IN (SELECT id FROM user_keys WHERE user_id = ?) "
            filter_params.append(user_id)
        if user_id is None:
            cursor.execute(
                f"""
                SELECT a.ID, a.account_name, a.owner, a.rental_start, a.rental_duration,
                        a.rental_duration_minutes, a.mmr, l.lot_number, l.lot_url,
                        a.account_frozen, a.rental_frozen, a.rental_frozen_at
                FROM accounts a
                LEFT JOIN lots l ON l.account_id = a.ID
                WHERE a.owner IS NULL AND (a.account_frozen = 0 OR a.account_frozen IS NULL)
                {key_clause_accounts}{key_clause_lots}
                ORDER BY (l.lot_number IS NULL), l.lot_number
                """
                ,
                (*key_params_accounts, *key_params_lots),
            )
        else:
            cursor.execute(
                f"""
                SELECT a.ID, a.account_name, a.owner, a.rental_start, a.rental_duration,
                        a.rental_duration_minutes, a.mmr, l.lot_number, l.lot_url,
                        a.account_frozen, a.rental_frozen, a.rental_frozen_at
                FROM accounts a
                LEFT JOIN lots l ON l.account_id = a.ID
                WHERE a.owner IS NULL AND a.user_id = ?
                    AND (a.account_frozen = 0 OR a.account_frozen IS NULL)
                    {key_clause_accounts}{key_clause_lots}
                    {filter_existing}
                ORDER BY (l.lot_number IS NULL), l.lot_number
                """,
                (user_id, *key_params_accounts, *key_params_lots, *filter_params),
            )
        rows = cursor.fetchall()
        if self.db_type == "mysql":
            cursor.close()
        return [
              {
                  "id": row[0],
                  "account_name": row[1],
                  "owner": row[2],
                  "rental_start": row[3],
                  "rental_duration": row[4],
                  "rental_duration_minutes": row[5],
                  "mmr": row[6],
                  "lot_number": row[7],
                  "lot_url": row[8],
                  "account_frozen": row[9] if len(row) > 9 else 0,
                  "rental_frozen": row[10] if len(row) > 10 else 0,
                  "rental_frozen_at": row[11] if len(row) > 11 else None,
              }
              for row in rows
          ]

    def get_all_lot_accounts(self, user_id: int | None = None, key_id: int | None = None) -> list:
        cursor = self._cursor()
        key_clause, key_params = self._key_filter(key_id, "l.key_id")
        filter_existing = ""
        filter_params: list = []
        if user_id is not None:
            filter_existing = " AND l.key_id IN (SELECT id FROM user_keys WHERE user_id = ?) "
            filter_params.append(user_id)
        if user_id is None:
            cursor.execute(
                f"""
                SELECT a.ID, a.account_name, a.owner, a.rental_start, a.rental_duration, a.rental_duration_minutes, a.mmr, l.lot_number, l.lot_url, a.account_frozen, a.rental_frozen, a.rental_frozen_at
                FROM lots l
                JOIN accounts a ON a.ID = l.account_id
                WHERE 1=1{key_clause}
                ORDER BY l.lot_number
                """,
                (*key_params,),
            )
        else:
            cursor.execute(
                f"""
                SELECT a.ID, a.account_name, a.owner, a.rental_start, a.rental_duration, a.rental_duration_minutes, a.mmr, l.lot_number, l.lot_url, a.account_frozen, a.rental_frozen, a.rental_frozen_at
                FROM lots l
                JOIN accounts a ON a.ID = l.account_id
                WHERE l.user_id = ?{key_clause}{filter_existing}
                ORDER BY l.lot_number
                """,
                (user_id, *key_params, *filter_params),
            )
        rows = cursor.fetchall()
        if self.db_type == "mysql":
            cursor.close()
        return [
            {
                "id": row[0],
                "account_name": row[1],
                "owner": row[2],
                "rental_start": row[3],
                "rental_duration": row[4],
                "rental_duration_minutes": row[5],
                "mmr": row[6],
                "lot_number": row[7],
                "lot_url": row[8],
            }
            for row in rows
        ]

    def get_lot_accounts_by_mmr_range(
        self,
        target_mmr: int,
        mmr_range: int = 1000,
        user_id: int | None = None,
        key_id: int | None = None,
    ) -> list:
        cursor = self._cursor()
        low = int(target_mmr) - int(mmr_range)
        high = int(target_mmr) + int(mmr_range)
        key_clause_accounts, key_params_accounts = self._key_filter(key_id, "a.key_id")
        key_clause_lots, key_params_lots = self._key_filter(key_id, "l.key_id")
        if user_id is None:
            cursor.execute(
                f"""
                SELECT a.ID, a.account_name, a.mmr, a.owner, a.rental_start,
                        a.rental_duration, a.rental_duration_minutes,
                        l.lot_number, l.lot_url
                FROM accounts a
                LEFT JOIN lots l ON l.account_id = a.ID
                WHERE a.mmr BETWEEN ? AND ? AND (a.account_frozen = 0 OR a.account_frozen IS NULL){key_clause_accounts}{key_clause_lots}
                ORDER BY a.mmr, a.ID
                """,
                (low, high, *key_params_accounts, *key_params_lots),
            )
        else:
            cursor.execute(
                f"""
                SELECT a.ID, a.account_name, a.mmr, a.owner, a.rental_start,
                        a.rental_duration, a.rental_duration_minutes,
                        l.lot_number, l.lot_url
                FROM accounts a
                LEFT JOIN lots l ON l.account_id = a.ID AND l.user_id = ?{key_clause_lots}
                WHERE a.user_id = ? AND a.mmr BETWEEN ? AND ? AND (a.account_frozen = 0 OR a.account_frozen IS NULL){key_clause_accounts}
                ORDER BY a.mmr, a.ID
                """,
                (user_id, *key_params_lots, user_id, low, high, *key_params_accounts),
            )
        rows = cursor.fetchall()
        if self.db_type == "mysql":
            cursor.close()
        return [
            {
                "id": row[0],
                "account_name": row[1],
                "mmr": row[2],
                "owner": row[3],
                "rental_start": row[4],
                "rental_duration": row[5],
                "rental_duration_minutes": row[6],
                "lot_number": row[7],
                "lot_url": row[8],
            }
            for row in rows
        ]

    def delete_account_by_id(
        self, account_id: int, user_id: int | None = None, key_id: int | None = None
    ) -> bool:
        """
        Delete all accounts that share the same login as the account with the given ID.
        """
        try:
            cursor = self._cursor()
            key_clause, key_params = self._key_filter(key_id, "key_id")
            if user_id in (None, 0):
                cursor.execute(
                    f"""
                    SELECT login
                    FROM accounts
                    WHERE ID = ?{key_clause}
                    """,
                    (account_id, *key_params),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT login
                    FROM accounts
                    WHERE ID = ? AND user_id = ?{key_clause}
                    """,
                    (account_id, user_id, *key_params),
                )
            result = cursor.fetchone()
            if not result:
                logger.error(f"No account found with ID {account_id}.")
                return False
            login = result[0]
            if user_id in (None, 0):
                cursor.execute(
                    f"""
                    DELETE FROM accounts
                    WHERE login = ?{key_clause}
                    """,
                    (login, *key_params),
                )
            else:
                cursor.execute(
                    f"""
                    DELETE FROM accounts
                    WHERE login = ? AND user_id = ?{key_clause}
                    """,
                    (login, user_id, *key_params),
                )
            success = cursor.rowcount > 0
            self.conn.commit()
            return success
        except Exception as e:
            logger.error(f"Error deleting accounts: {str(e)}")
            return False
        finally:
            cursor.close()

    def release_account(
        self, account_id: int, user_id: int | None = None, key_id: int | None = None
    ) -> bool:
        """Clear owner and rental start for an account."""
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            if user_id in (None, 0):
                cursor.execute(
                    f"""
                    UPDATE accounts
                    SET owner = NULL, rental_start = NULL, rental_frozen = 0, rental_frozen_at = NULL
                    WHERE ID = ?{key_clause}
                    """,
                    (account_id, *key_params),
                )
            else:
                cursor.execute(
                    f"""
                    UPDATE accounts
                    SET owner = NULL, rental_start = NULL, rental_frozen = 0, rental_frozen_at = NULL
                    WHERE ID = ? AND user_id = ?{key_clause}
                    """,
                    (account_id, user_id, *key_params),
                )
            success = cursor.rowcount > 0
            self.conn.commit()
            return success
        except Exception as e:
            logger.error(f"Error releasing account: {str(e)}")
            return False
        finally:
            if cursor:
                cursor.close()

    def update_account(
        self,
        account_id: int,
        fields: dict,
        user_id: int | None = None,
        key_id: int | None = None,
    ) -> bool:
        """Update editable fields for a single account."""
        allowed_fields = {
            "account_name",
            "path_to_maFile",
            "mafile_json",
            "login",
            "password",
            "rental_duration",
            "rental_duration_minutes",
            "mmr",
            "key_id",
        }
        updates = {key: value for key, value in fields.items() if key in allowed_fields}
        if not updates:
            return False
        if "mafile_json" in updates:
            updates["mafile_json"] = self._encrypt_value(self._normalize_mafile(updates["mafile_json"]))
        if "password" in updates:
            updates["password"] = self._encrypt_value(updates["password"])

        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            set_clause = ", ".join([f"{key} = ?" for key in updates.keys()])
            values = list(updates.values())
            values.append(account_id)
            where_user = ""
            if user_id not in (None, 0):
                where_user = " AND user_id = ?"
                values.append(user_id)
            cursor.execute(
                f"""
                UPDATE accounts
                SET {set_clause}
                WHERE ID = ?{where_user}{key_clause}
                """,
                values + key_params,
            )
            success = cursor.rowcount > 0
            self.conn.commit()
            return success
        except Exception as e:
            logger.error(f"Error updating account: {str(e)}")
            return False
        finally:
            cursor.close()

    def get_total_accounts(self):
        """Retrieve the total number of accounts."""
        try:
            cursor = self._cursor()
            cursor.execute("SELECT COUNT(*) FROM accounts")
            total_accounts = cursor.fetchone()[0]
            return total_accounts
        except Exception as e:
            logger.error(f"Error retrieving total accounts: {str(e)}")
            return 0
        finally:
            cursor.close()

    def get_all_account_names(self, user_id: int | None = None, key_id: int | None = None) -> list:
        """Retrieve all distinct account names."""
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            if user_id is None:
                cursor.execute(
                    f"SELECT account_name FROM accounts WHERE 1=1{key_clause}",
                    (*key_params,),
                )
            else:
                cursor.execute(
                    f"SELECT account_name FROM accounts WHERE user_id = ?{key_clause}",
                    (int(user_id), *key_params),
                )
            account_names = [row[0] for row in cursor.fetchall()]
            return account_names
        except Exception as e:
            logger.error(f"Error retrieving account names: {str(e)}")
            return []
        finally:
            cursor.close()

    def get_unowned_account_names(self, user_id: int | None = None, key_id: int | None = None) -> list:
        """Retrieve account names for accounts with no owner."""
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            if user_id is None:
                cursor.execute(
                    f"""
                    SELECT account_name FROM accounts
                    WHERE owner IS NULL AND (account_frozen = 0 OR account_frozen IS NULL){key_clause}
                    """,
                    (*key_params,),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT account_name FROM accounts
                    WHERE owner IS NULL AND user_id = ? AND (account_frozen = 0 OR account_frozen IS NULL){key_clause}
                    """,
                    (int(user_id), *key_params),
                )
            unowned_account_names = [row[0] for row in cursor.fetchall()]
            return unowned_account_names
        except Exception as e:
            logger.error(f"Error retrieving unowned account names: {str(e)}")
            return []
        finally:
            cursor.close()

    def get_account_by_name(self, account_name: str, user_id: int | None = None, key_id: int | None = None):
        """Get account by its name."""
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            if user_id is None:
                cursor.execute(
                    f"""
                    SELECT ID, account_name, path_to_maFile, login, password, rental_duration, rental_duration_minutes, mmr, owner, rental_start
                    FROM accounts 
                    WHERE account_name = ?{key_clause}
                    """,
                    (account_name, *key_params),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT ID, account_name, path_to_maFile, login, password, rental_duration, rental_duration_minutes, mmr, owner, rental_start
                    FROM accounts 
                    WHERE account_name = ? AND user_id = ?{key_clause}
                    """,
                    (account_name, int(user_id), *key_params),
                )
            row = cursor.fetchone()
            cursor.close()
            
            if row:
                return {
                    "id": row[0],
                    "account_name": row[1],
                    "path_to_maFile": row[2],
                    "login": row[3],
                    "password": self._decrypt_value(row[4]),
                    "rental_duration": row[5],
                    "rental_duration_minutes": row[6],
                    "mmr": row[7],
                    "owner": row[8],
                    "rental_start": row[9]
                }
            return None
        except Exception as e:
            logger.error(f"Error getting account by name: {str(e)}")
            return None

    def get_account_by_id(
        self, account_id: int, user_id: int | None = None, key_id: int | None = None
    ) -> dict:
        """
        Get account details by ID.
        
        Args:
            account_id (int): The ID of the account
            
        Returns:
            dict: Account details or None if not found
        """
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            if user_id is None:
                cursor.execute(
                    f"""
                      SELECT ID, account_name, path_to_maFile, login, password, 
                             rental_duration, rental_duration_minutes, mmr, owner, rental_start, mafile_json,
                             account_frozen, rental_frozen, rental_frozen_at, key_id
                      FROM accounts 
                      WHERE ID = ?{key_clause}
                      """,
                    (account_id, *key_params),
                )
            else:
                cursor.execute(
                    f"""
                      SELECT ID, account_name, path_to_maFile, login, password, 
                             rental_duration, rental_duration_minutes, mmr, owner, rental_start, mafile_json,
                             account_frozen, rental_frozen, rental_frozen_at, key_id
                      FROM accounts 
                      WHERE ID = ? AND user_id = ?{key_clause}
                      """,
                    (account_id, user_id, *key_params),
                )
            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "account_name": row[1],
                    "path_to_maFile": row[2],
                    "login": row[3],
                    "password": self._decrypt_value(row[4]),
                    "rental_duration": row[5],
                    "rental_duration_minutes": row[6],
                    "mmr": row[7],
                    "owner": row[8],
                    "rental_start": row[9],
                    "mafile_json": self._decrypt_value(row[10]),
                    "account_frozen": row[11],
                    "rental_frozen": row[12],
                    "rental_frozen_at": row[13],
                    "key_id": row[14] if len(row) > 14 else None,
                }
            return None
        except Exception as e:
            logger.error(f"Error getting account by ID: {str(e)}")
            return None
        finally:
            cursor.close()

    def get_rental_statistics(self, user_id: int | None = None, key_id: int | None = None) -> dict:
        """
        Get rental statistics for the system.
        
        Returns:
            dict: Statistics including total accounts, active rentals, etc.
        """
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            
            # Total accounts
            if user_id is None:
                cursor.execute(
                    f"SELECT COUNT(*) FROM accounts WHERE 1=1{key_clause}",
                    (*key_params,),
                )
            else:
                cursor.execute(
                    f"SELECT COUNT(*) FROM accounts WHERE user_id = ?{key_clause}",
                    (user_id, *key_params),
                )
            total_accounts = cursor.fetchone()[0]
            
            # Active rentals
            if user_id is None:
                cursor.execute(
                    f"SELECT COUNT(*) FROM accounts WHERE owner IS NOT NULL{key_clause}",
                    (*key_params,),
                )
            else:
                cursor.execute(
                    f"SELECT COUNT(*) FROM accounts WHERE owner IS NOT NULL AND user_id = ?{key_clause}",
                    (user_id, *key_params),
                )
            active_rentals = cursor.fetchone()[0]
            
            # Available accounts
            if user_id is None:
                cursor.execute(
                    f"""
                    SELECT COUNT(*) FROM accounts
                    WHERE owner IS NULL AND (account_frozen = 0 OR account_frozen IS NULL){key_clause}
                    """,
                    (*key_params,),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM accounts
                    WHERE owner IS NULL AND user_id = ?{key_clause}
                      AND (account_frozen = 0 OR account_frozen IS NULL)
                    """,
                    (user_id, *key_params),
                )
            available_accounts = cursor.fetchone()[0]
            
            # Total rental hours
            if user_id is None:
                cursor.execute(
                    f"SELECT SUM(COALESCE(rental_duration_minutes, rental_duration * 60)) FROM accounts WHERE owner IS NOT NULL{key_clause}",
                    (*key_params,),
                )
            else:
                cursor.execute(
                    f"SELECT SUM(COALESCE(rental_duration_minutes, rental_duration * 60)) FROM accounts WHERE owner IS NOT NULL AND user_id = ?{key_clause}",
                    (user_id, *key_params),
                )
            total_minutes = cursor.fetchone()[0] or 0
            total_hours = round(total_minutes / 60, 2)
            
            # Recent rentals (last 24 hours)
            since = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
            if user_id is None:
                cursor.execute(
                    f"""
                    SELECT COUNT(*) FROM accounts 
                    WHERE owner IS NOT NULL 
                    AND rental_start >= ?{key_clause}
                    """,
                    (since, *key_params),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT COUNT(*) FROM accounts 
                    WHERE owner IS NOT NULL 
                    AND rental_start >= ?
                    AND user_id = ?{key_clause}
                    """,
                    (since, user_id, *key_params),
                )
            recent_rentals = cursor.fetchone()[0]
            
            return {
                "total_accounts": total_accounts,
                "active_rentals": active_rentals,
                "available_accounts": available_accounts,
                "total_hours": total_hours,
                "recent_rentals": recent_rentals
            }
        except Exception as e:
            logger.error(f"Error getting rental statistics: {str(e)}")
            return {}
        finally:
            cursor.close()

    def get_user_rental_history(self, owner_id: str) -> list:
        """
        Get rental history for a specific user.
        
        Args:
            owner_id (str): The owner ID to get history for
            
        Returns:
            list: List of rental records
        """
        try:
            cursor = self._cursor()
            cursor.execute(
                """
                SELECT ID, account_name, login, rental_duration, rental_duration_minutes, rental_start
                FROM accounts 
                WHERE owner = ?
                ORDER BY rental_start DESC
                """,
                (owner_id,),
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "account_name": row[1],
                    "login": row[2],
                    "rental_duration": row[3],
                    "rental_duration_minutes": row[4],
                    "rental_start": row[5],
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Error getting user rental history: {str(e)}")
            return []
        finally:
            cursor.close()

    def get_chat_summary(self, owner_id: str, user_id: int | None = None) -> dict | None:
        if not owner_id:
            return None
        try:
            cursor = self._cursor()
            cursor.execute(
                """
                SELECT summary, last_message_id
                FROM chat_summaries
                WHERE owner = ? AND user_id = ?
                """,
                (str(owner_id), int(user_id or 0)),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {"summary": row[0], "last_message_id": int(row[1])}
        except Exception as exc:
            logger.error(f"Error getting chat summary: {exc}")
            return None
        finally:
            cursor.close()

    def upsert_chat_summary(
        self,
        owner_id: str,
        summary: str,
        last_message_id: int,
        user_id: int | None = None,
    ) -> bool:
        if not owner_id:
            return False
        try:
            cursor = self._cursor()
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    INSERT INTO chat_summaries (owner, user_id, summary, last_message_id)
                    VALUES (?, ?, ?, ?)
                    ON DUPLICATE KEY UPDATE
                        summary = VALUES(summary),
                        last_message_id = VALUES(last_message_id),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (str(owner_id), int(user_id or 0), summary, int(last_message_id)),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO chat_summaries (owner, user_id, summary, last_message_id)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(owner, user_id) DO UPDATE SET
                        summary = excluded.summary,
                        last_message_id = excluded.last_message_id,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (str(owner_id), int(user_id or 0), summary, int(last_message_id)),
                )
            return True
        except Exception as exc:
            logger.error(f"Error updating chat summary: {exc}")
            return False
        finally:
            cursor.close()

    def log_order_event(
        self,
        order_id: str,
        owner_id: str,
        action: str,
        account_name: str | None = None,
        lot_number: int | None = None,
        amount: int | None = None,
        price: float | None = None,
        user_id: int | None = None,
        account_id: int | None = None,
        rental_minutes: int | None = None,
        steam_id: str | None = None,
        key_id: int | None = None,
    ) -> bool:
        if not order_id or not owner_id or not action:
            return False
        cursor = None
        try:
            amount_value = None
            if amount is not None:
                try:
                    amount_value = int(amount)
                except (TypeError, ValueError):
                    amount_value = None
            price_value = None
            if price is not None:
                try:
                    price_value = float(price)
                except (TypeError, ValueError):
                    price_value = None
            account_id_value = None
            if account_id is not None:
                try:
                    account_id_value = int(account_id)
                except (TypeError, ValueError):
                    account_id_value = None
            rental_minutes_value = None
            if rental_minutes is not None:
                try:
                    rental_minutes_value = int(rental_minutes)
                except (TypeError, ValueError):
                    rental_minutes_value = None
            steam_id_value = str(steam_id).strip() if steam_id else None

            cursor = self._cursor()
            key_value = int(key_id) if key_id is not None else None
            try:
                cursor.execute(
                    """
                    INSERT INTO order_history (
                        order_id, owner, account_name, account_id, steam_id, rental_minutes,
                        lot_number, amount, price, action, user_id, key_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(order_id),
                        str(owner_id),
                        account_name,
                        account_id_value,
                        steam_id_value,
                        rental_minutes_value,
                        int(lot_number) if lot_number is not None else None,
                        amount_value,
                        price_value,
                        str(action),
                        int(user_id or 0),
                        key_value,
                    ),
                )
                return True
            except Exception as exc:
                logger.warning(f"Order history insert fallback (new columns): {exc}")
                cursor.execute(
                    """
                    INSERT INTO order_history (
                        order_id, owner, account_name, lot_number, amount, price, action, user_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(order_id),
                        str(owner_id),
                        account_name,
                        int(lot_number) if lot_number is not None else None,
                        amount_value,
                        price_value,
                        str(action),
                        int(user_id or 0),
                    ),
                )
                return True
        except Exception as exc:
            logger.error(f"Error logging order event: {exc}")
            return False
        finally:
            try:
                if cursor:
                    cursor.close()
            except Exception:
                pass

    def get_order_history(
        self,
        owner_id: str,
        limit: int = 5,
        user_id: int | None = None,
        key_id: int | None = None,
    ) -> list:
        if not owner_id:
            return []
        try:
            cursor = self._cursor()
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor.execute(
                f"""
                SELECT order_id, account_name, lot_number, amount, price, action, created_at
                FROM order_history
                WHERE owner = ? AND user_id = ?{key_clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (str(owner_id), int(user_id or 0), *key_params, int(limit)),
            )
            rows = cursor.fetchall()
            return [
                {
                    "order_id": row[0],
                    "account_name": row[1],
                    "lot_number": row[2],
                    "amount": row[3],
                    "price": row[4],
                    "action": row[5],
                    "created_at": row[6],
                }
                for row in rows
            ]
        except Exception as exc:
            logger.error(f"Error getting order history: {exc}")
            return []
        finally:
            cursor.close()

    def set_account_frozen(
        self, account_id: int, frozen: bool, user_id: int | None = None, key_id: int | None = None
    ) -> bool:
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            values: list[Any] = [1 if frozen else 0, int(account_id)]
            where_user = ""
            if user_id not in (None, 0):
                where_user = " AND user_id = ?"
                values.append(int(user_id))
            cursor.execute(
                f"""
                UPDATE accounts
                SET account_frozen = ?
                WHERE ID = ?{where_user}{key_clause}
                """,
                values + key_params,
            )
            success = cursor.rowcount > 0
            self.conn.commit()
            return success
        except Exception as exc:
            logger.error(f"Error setting account frozen state: {exc}")
            return False
        finally:
            cursor.close()

    def set_rental_freeze_state(
        self,
        account_id: int,
        frozen: bool,
        *,
        rental_start: datetime | None = None,
        frozen_at: datetime | None = None,
        user_id: int | None = None,
        key_id: int | None = None,
    ) -> bool:
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            sets = ["rental_frozen = ?"]
            values: list[Any] = [1 if frozen else 0]
            if frozen_at is not None:
                sets.append("rental_frozen_at = ?")
                values.append(frozen_at.strftime("%Y-%m-%d %H:%M:%S"))
            elif not frozen:
                sets.append("rental_frozen_at = NULL")
            if rental_start is not None:
                sets.append("rental_start = ?")
                values.append(rental_start.strftime("%Y-%m-%d %H:%M:%S"))
            values.append(int(account_id))
            where_user = ""
            if user_id not in (None, 0):
                where_user = " AND user_id = ?"
                values.append(int(user_id))
            cursor.execute(
                f"""
                UPDATE accounts
                SET {", ".join(sets)}
                WHERE ID = ?{where_user}{key_clause}
                """,
                values + key_params,
            )
            success = cursor.rowcount > 0
            self.conn.commit()
            return success
        except Exception as exc:
            logger.error(f"Error updating rental freeze state: {exc}")
            return False
        finally:
            cursor.close()

    def search_order_history(
        self,
        query: str | None = None,
        limit: int = 100,
        user_id: int | None = None,
        account_ids: list[int] | None = None,
        account_names: list[str] | None = None,
        key_id: int | None = None,
    ) -> list:
        cursor = None
        try:
            cursor = self._cursor()
            limit_value = max(1, min(int(limit or 100), 500))
            where = ["user_id = ?"]
            params: list = [int(user_id or 0)]
            key_clause, key_params = self._key_filter(key_id, "key_id")
            if key_clause:
                where.append(key_clause.replace(" AND ", "", 1))
                params.extend(key_params)

            if account_ids or account_names:
                clauses = []
                if account_ids:
                    cleaned_ids = []
                    for value in account_ids:
                        try:
                            cleaned_ids.append(int(value))
                        except (TypeError, ValueError):
                            continue
                    if cleaned_ids:
                        placeholders = ", ".join(["?"] * len(cleaned_ids))
                        clauses.append(f"account_id IN ({placeholders})")
                        params.extend(cleaned_ids)
                if account_names:
                    cleaned_names = [str(value) for value in account_names if value]
                    if cleaned_names:
                        placeholders = ", ".join(["?"] * len(cleaned_names))
                        clauses.append(f"account_name IN ({placeholders})")
                        params.extend(cleaned_names)
                if clauses:
                    where.append("(" + " OR ".join(clauses) + ")")

            if query:
                like = f"%{query}%"
                lot_cast = "CAST(lot_number AS CHAR)" if self.db_type == "mysql" else "CAST(lot_number AS TEXT)"
                acc_cast = "CAST(account_id AS CHAR)" if self.db_type == "mysql" else "CAST(account_id AS TEXT)"
                where.append(
                    "("
                    "order_id LIKE ? OR owner LIKE ? OR account_name LIKE ? OR action LIKE ? "
                    f"OR {lot_cast} LIKE ? OR {acc_cast} LIKE ? OR steam_id LIKE ?"
                    ")"
                )
                params.extend([like, like, like, like, like, like, like])

            cursor.execute(
                f"""
                SELECT id, order_id, owner, account_id, account_name, lot_number, amount, price, action,
                       user_id, created_at, rental_minutes, steam_id
                FROM order_history
                WHERE {' AND '.join(where)}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (*params, limit_value),
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "order_id": row[1],
                    "owner": row[2],
                    "account_id": row[3],
                    "account_name": row[4],
                    "lot_number": row[5],
                    "amount": row[6],
                    "price": row[7],
                    "action": row[8],
                    "user_id": row[9],
                    "created_at": row[10],
                    "rental_minutes": row[11],
                    "steam_id": row[12],
                }
                for row in rows
            ]
        except Exception as exc:
            logger.error(f"Error searching order history: {exc}")
            return []
        finally:
            if cursor:
                cursor.close()

    def insert_balance_snapshot(
        self,
        user_id: int | None,
        total_rub: float | None,
        available_rub: float | None,
        total_usd: float | None,
        total_eur: float | None,
        key_id: int | None = None,
    ) -> bool:
        cursor = None
        try:
            cursor = self._cursor()
            key_value = int(key_id) if key_id is not None else None
            cursor.execute(
                """
                INSERT INTO funpay_balance_snapshots (
                    user_id, total_rub, available_rub, total_usd, total_eur, key_id
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(user_id or 0),
                    float(total_rub) if total_rub is not None else None,
                    float(available_rub) if available_rub is not None else None,
                    float(total_usd) if total_usd is not None else None,
                    float(total_eur) if total_eur is not None else None,
                    key_value,
                ),
            )
            return True
        except Exception as exc:
            logger.error(f"Error inserting balance snapshot: {exc}")
            return False
        finally:
            if cursor:
                cursor.close()

    def get_latest_balance_snapshot(
        self, user_id: int | None = None, key_id: int | None = None
    ) -> dict | None:
        cursor = None
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            cursor.execute(
                f"""
                SELECT total_rub, available_rub, total_usd, total_eur, created_at
                FROM funpay_balance_snapshots
                WHERE user_id = ?{key_clause}
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (int(user_id or 0), *key_params),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "total_rub": row[0],
                "available_rub": row[1],
                "total_usd": row[2],
                "total_eur": row[3],
                "created_at": row[4],
            }
        except Exception as exc:
            logger.error(f"Error reading balance snapshot: {exc}")
            return None
        finally:
            if cursor:
                cursor.close()

    def get_balance_snapshots(
        self, user_id: int | None = None, days: int = 30, key_id: int | None = None
    ) -> list:
        cursor = None
        try:
            since = (datetime.utcnow() - timedelta(days=max(1, int(days)) - 1)).strftime("%Y-%m-%d %H:%M:%S")
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            cursor.execute(
                f"""
                SELECT total_rub, available_rub, total_usd, total_eur, created_at
                FROM funpay_balance_snapshots
                WHERE user_id = ? AND created_at >= ?{key_clause}
                ORDER BY created_at ASC
                """,
                (int(user_id or 0), since, *key_params),
            )
            rows = cursor.fetchall()
            return [
                {
                    "total_rub": row[0],
                    "available_rub": row[1],
                    "total_usd": row[2],
                    "total_eur": row[3],
                    "created_at": row[4],
                }
                for row in rows
            ]
        except Exception as exc:
            logger.error(f"Error reading balance snapshots: {exc}")
            return []
        finally:
            if cursor:
                cursor.close()

    def get_order_counts_by_day(
        self,
        user_id: int | None,
        actions: list[str] | None = None,
        days: int = 30,
        key_id: int | None = None,
    ) -> dict:
        cursor = None
        if not actions:
            return {}
        try:
            since = (datetime.utcnow() - timedelta(days=max(1, int(days)) - 1)).strftime("%Y-%m-%d %H:%M:%S")
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            placeholders = ", ".join(["?"] * len(actions))
            cursor.execute(
                f"""
                SELECT DATE(created_at) as day, COUNT(*)
                FROM order_history
                WHERE (user_id = ? OR user_id = 0){key_clause} AND action IN ({placeholders}) AND created_at >= ?
                GROUP BY day
                """,
                (int(user_id or 0), *key_params, *actions, since),
            )
            rows = cursor.fetchall()
            return {str(row[0]): int(row[1]) for row in rows}
        except Exception as exc:
            logger.error(f"Error reading order counts: {exc}")
            return {}
        finally:
            if cursor:
                cursor.close()

    def get_review_counts_by_day(
        self,
        user_id: int | None = None,
        days: int = 30,
    ) -> dict:
        cursor = None
        try:
            since = (datetime.utcnow() - timedelta(days=max(1, int(days)) - 1)).strftime("%Y-%m-%d %H:%M:%S")
            cursor = self._cursor()
            cursor.execute(
                """
                SELECT DATE(reviewed_at) as day, COUNT(*)
                FROM feedback_rewards
                WHERE (user_id = ? OR user_id = 0) AND reviewed_at >= ?
                GROUP BY day
                """,
                (int(user_id or 0), since),
            )
            rows = cursor.fetchall()
            return {str(row[0]): int(row[1]) for row in rows}
        except Exception as exc:
            logger.error(f"Error reading review counts: {exc}")
            return {}
        finally:
            if cursor:
                cursor.close()

    def _ensure_order_history_columns(self):
        cursor = self._cursor()
        try:
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = ? AND table_name = 'order_history'
                    """,
                    (MYSQLDATABASE,),
                )
                cols = {row[0] for row in cursor.fetchall()}
                alter = {
                    "account_id": "ALTER TABLE order_history ADD COLUMN account_id INT NULL",
                    "steam_id": "ALTER TABLE order_history ADD COLUMN steam_id VARCHAR(32) NULL",
                    "rental_minutes": "ALTER TABLE order_history ADD COLUMN rental_minutes INT NULL",
                }
                for col, stmt in alter.items():
                    if col not in cols:
                        cursor.execute(stmt)
                self.conn.commit()
            else:
                cursor.execute("PRAGMA table_info(order_history)")
                cols = {row[1] for row in cursor.fetchall()}
                alter = {
                    "account_id": "ALTER TABLE order_history ADD COLUMN account_id INTEGER",
                    "steam_id": "ALTER TABLE order_history ADD COLUMN steam_id TEXT",
                    "rental_minutes": "ALTER TABLE order_history ADD COLUMN rental_minutes INTEGER",
                }
                for col, stmt in alter.items():
                    if col not in cols:
                        cursor.execute(stmt)
                self.conn.commit()
        except Exception:
            pass
        finally:
            cursor.close()

    def start_rental_for_owner(
        self, owner_id: str, user_id: int | None = None, key_id: int | None = None
    ) -> int:
        """
        Set rental_start for all accounts owned by the user that haven't started yet.
        Returns the number of updated rows.
        """
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            rental_start = (datetime.utcnow() + timedelta(hours=3)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            if user_id in (None, 0):
                cursor.execute(
                    f"""
                    UPDATE accounts
                    SET rental_start = ?
                    WHERE owner = ? AND rental_start IS NULL
                      AND (account_frozen = 0 OR account_frozen IS NULL)
                      AND (rental_frozen = 0 OR rental_frozen IS NULL){key_clause}
                    """,
                    (rental_start, owner_id, *key_params),
                )
            else:
                cursor.execute(
                    f"""
                    UPDATE accounts
                    SET rental_start = ?
                    WHERE owner = ? AND rental_start IS NULL AND user_id = ?
                      AND (account_frozen = 0 OR account_frozen IS NULL)
                      AND (rental_frozen = 0 OR rental_frozen IS NULL){key_clause}
                    """,
                    (rental_start, owner_id, user_id, *key_params),
                )
            updated = cursor.rowcount
            self.conn.commit()
            return updated or 0
        except Exception as e:
            logger.error(f"Error starting rental for owner {owner_id}: {str(e)}")
            return 0
        finally:
            cursor.close()

    def list_blacklist(
        self, user_id: int | None = None, query: str | None = None, key_id: int | None = None
    ) -> list:
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            owner_query = None
            if query:
                owner_query = f"%{str(query).strip().lower()}%"
            if owner_query:
                cursor.execute(
                    f"""
                    SELECT id, owner, reason, created_at
                    FROM blacklist
                    WHERE user_id = ? AND owner LIKE ?{key_clause}
                    ORDER BY created_at DESC
                    """,
                    (int(user_id or 0), owner_query, *key_params),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT id, owner, reason, created_at
                    FROM blacklist
                    WHERE user_id = ?{key_clause}
                    ORDER BY created_at DESC
                    """,
                    (int(user_id or 0), *key_params),
                )
            rows = cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "owner": row[1],
                    "reason": row[2],
                    "created_at": row[3],
                }
                for row in rows
            ]
        except Exception as exc:
            logger.error(f"Error listing blacklist: {exc}")
            return []
        finally:
            cursor.close()

    def is_blacklisted(self, owner: str, user_id: int | None = None, key_id: int | None = None) -> bool:
        if not owner:
            return False
        owner_key = str(owner).strip().lower()
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            cursor.execute(
                f"""
                SELECT 1 FROM blacklist WHERE owner = ? AND user_id = ?{key_clause} LIMIT 1
                """,
                (owner_key, int(user_id or 0), *key_params),
            )
            return cursor.fetchone() is not None
        except Exception as exc:
            logger.error(f"Error checking blacklist for {owner}: {exc}")
            return False
        finally:
            cursor.close()

    def add_blacklist_entry(
        self,
        owner: str,
        reason: str | None = None,
        user_id: int | None = None,
        key_id: int | None = None,
    ) -> bool:
        if not owner:
            return False
        owner_key = str(owner).strip().lower()
        reason_value = reason.strip() if isinstance(reason, str) and reason.strip() else None
        try:
            cursor = self._cursor()
            key_value = int(key_id) if key_id is not None else None
            try:
                cursor.execute(
                    """
                    INSERT INTO blacklist (owner, reason, user_id, key_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    (owner_key, reason_value, int(user_id or 0), key_value),
                )
                self.conn.commit()
                return True
            except Exception:
                if reason_value is None:
                    return False
                cursor.execute(
                    """
                    UPDATE blacklist
                    SET reason = ?
                    WHERE owner = ? AND user_id = ?
                    """,
                    (reason_value, owner_key, int(user_id or 0)),
                )
                self.conn.commit()
                return True
        except Exception as exc:
            logger.error(f"Error adding blacklist entry for {owner}: {exc}")
            return False
        finally:
            cursor.close()

    def update_blacklist_entry(
        self,
        entry_id: int,
        owner: str,
        reason: str | None = None,
        user_id: int | None = None,
        key_id: int | None = None,
    ) -> bool:
        if not entry_id or not owner:
            return False
        owner_key = str(owner).strip().lower()
        reason_value = reason.strip() if isinstance(reason, str) and reason.strip() else None
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            cursor.execute(
                f"""
                SELECT id FROM blacklist
                WHERE owner = ? AND user_id = ? AND id != ?{key_clause}
                LIMIT 1
                """,
                (owner_key, int(user_id or 0), int(entry_id), *key_params),
            )
            if cursor.fetchone():
                return False
            cursor.execute(
                f"""
                UPDATE blacklist
                SET owner = ?, reason = ?
                WHERE id = ? AND user_id = ?{key_clause}
                """,
                (owner_key, reason_value, int(entry_id), int(user_id or 0), *key_params),
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as exc:
            logger.error(f"Error updating blacklist entry {entry_id}: {exc}")
            return False
        finally:
            cursor.close()

    def get_chat_messages(self, owner: str, user_id: int | None = None, limit: int = 200) -> list[dict]:
        """
        Return recent chat messages for an owner (buyer) within a user workspace.
        """
        if not owner:
            return []
        try:
            cursor = self._cursor()
            def fetch(for_user_id: int) -> list[tuple]:
                cursor.execute(
                    """
                    SELECT role, message, created_at, key_id
                    FROM chat_messages
                    WHERE LOWER(owner) = LOWER(?) AND user_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (str(owner).strip(), for_user_id, int(limit)),
                )
                return cursor.fetchall()

            rows = fetch(int(user_id or 0))
            # Fallback to global user_id=0 if none found
            if not rows:
                rows = fetch(0)
            # As a last resort, fetch any user (could be another workspace) to surface context
            if not rows:
                cursor.execute(
                    """
                    SELECT role, message, created_at, key_id
                    FROM chat_messages
                    WHERE LOWER(owner) = LOWER(?)
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (str(owner).strip(), int(limit)),
                )
                rows = cursor.fetchall()

            return [
                {
                    "role": row[0],
                    "message": row[1],
                    "created_at": row[2],
                    "key_id": row[3] if len(row) > 3 else None,
                }
                for row in rows
            ]
        except Exception as exc:
            logger.error(f"Error getting chat messages for {owner}: {exc}")
            return []
        finally:
            cursor.close()

    def log_chat_message(
        self,
        owner: str,
        role: str,
        message: str,
        user_id: int | None = None,
        key_id: int | None = None,
    ) -> None:
        if not owner or not role or not message:
            return
        try:
            cursor = self._cursor()
            cursor.execute(
                """
                INSERT INTO chat_messages (owner, role, message, user_id, key_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(owner).strip().lower(), str(role), message, int(user_id or 0), key_id),
            )
            self.conn.commit()
        except Exception as exc:
            logger.error(f"Error logging chat message for {owner}: {exc}")
        finally:
            try:
                cursor.close()
            except Exception:
                pass

    def insert_support_ticket(
        self,
        user_id: int | None,
        key_id: int | None,
        topic: str,
        role: str,
        order_id: str | None,
        comment: str | None,
        ticket_url: str | None,
        status: str,
        source: str | None = None,
    ) -> int | None:
        try:
            cursor = self._cursor()
            cursor.execute(
                """
                INSERT INTO support_tickets (user_id, key_id, topic, role, order_id, comment, ticket_url, status, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (int(user_id or 0), key_id, topic, role, order_id, comment, ticket_url, status, source),
            )
            ticket_id = cursor.lastrowid
            self.conn.commit()
            return ticket_id
        except Exception as exc:
            logger.error(f"Error inserting support ticket: {exc}")
            return None
        finally:
            try:
                cursor.close()
            except Exception:
                pass

    def list_support_tickets(self, user_id: int | None = None, key_id: int | None = None, limit: int = 200) -> list[dict]:
        try:
            cursor = self._cursor()
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor.execute(
                f"""
                SELECT id, topic, role, order_id, comment, ticket_url, status, source, created_at
                FROM support_tickets
                WHERE user_id = ?{key_clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (int(user_id or 0), *key_params, int(limit)),
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "topic": row[1],
                    "role": row[2],
                    "order_id": row[3],
                    "comment": row[4],
                    "ticket_url": row[5],
                    "status": row[6],
                    "source": row[7],
                    "created_at": row[8],
                }
                for row in rows
            ]
        except Exception as exc:
            logger.error(f"Error listing support tickets: {exc}")
            return []
        finally:
            cursor.close()

    def log_blacklist_event(
        self,
        owner: str,
        action: str,
        reason: str | None = None,
        details: str | None = None,
        user_id: int | None = None,
        key_id: int | None = None,
    ) -> None:
        if not owner or not action:
            return
        try:
            cursor = self._cursor()
            key_value = int(key_id) if key_id is not None else None
            cursor.execute(
                """
                INSERT INTO blacklist_logs (owner, action, reason, details, user_id, key_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(owner).strip().lower(), str(action), reason, details, int(user_id or 0), key_value),
            )
            self.conn.commit()
        except Exception as exc:
            logger.error(f"Error logging blacklist event for {owner}: {exc}")
        finally:
            try:
                cursor.close()
            except Exception:
                pass

    def _ensure_chat_columns(self):
        # user_id already added in _ensure_user_owner_columns for some deployments; keep idempotent
        self._add_column_if_missing("chat_messages", "user_id", "INT NOT NULL DEFAULT 0")
        self._add_column_if_missing("chat_messages", "key_id", "INT NULL")

    def _ensure_support_tickets_table(self):
        cursor = self._cursor()
        try:
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS support_tickets (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL DEFAULT 0,
                        key_id INT NULL,
                        topic VARCHAR(64) NOT NULL,
                        role VARCHAR(16) NOT NULL,
                        order_id VARCHAR(64) NULL,
                        comment TEXT NULL,
                        ticket_url TEXT NULL,
                        status VARCHAR(32) NOT NULL DEFAULT 'sent',
                        source VARCHAR(32) NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_support_user (user_id, key_id),
                        INDEX idx_support_order (order_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
            else:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS support_tickets (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL DEFAULT 0,
                        key_id INTEGER NULL,
                        topic TEXT NOT NULL,
                        role TEXT NOT NULL,
                        order_id TEXT NULL,
                        comment TEXT NULL,
                        ticket_url TEXT NULL,
                        status TEXT NOT NULL DEFAULT 'sent',
                        source TEXT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            self.conn.commit()
        except Exception:
            pass
        finally:
            cursor.close()

    def list_blacklist_logs(
        self, user_id: int | None = None, key_id: int | None = None, limit: int = 100
    ) -> list:
        try:
            cursor = self._cursor()
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor.execute(
                f"""
                SELECT owner, action, reason, details, created_at
                FROM blacklist_logs
                WHERE user_id = ?{key_clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (int(user_id or 0), *key_params, int(limit)),
            )
            rows = cursor.fetchall()
            return [
                {
                    "owner": row[0],
                    "action": row[1],
                    "reason": row[2],
                    "details": row[3],
                    "created_at": row[4],
                }
                for row in rows
            ]
        except Exception as exc:
            logger.error(f"Error listing blacklist logs: {exc}")
            return []
        finally:
            cursor.close()

    def get_blacklist_compensation_total(
        self, owner_id: str, user_id: int | None = None, key_id: int | None = None
    ) -> int:
        """
        Sum of 'blacklist_comp' amounts for a buyer within a workspace.
        """
        if not owner_id:
            return 0
        try:
            cursor = self._cursor()
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor.execute(
                f"""
                SELECT COALESCE(SUM(amount), 0)
                FROM order_history
                WHERE owner = ? AND user_id = ? AND action = 'blacklist_comp'{key_clause}
                """,
                (str(owner_id), int(user_id or 0), *key_params),
            )
            row = cursor.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
        except Exception as exc:
            logger.error(f"Error summing blacklist compensation for {owner_id}: {exc}")
            return 0
        finally:
            cursor.close()

    def remove_from_blacklist(
        self,
        owner: str,
        user_id: int | None = None,
        key_id: int | None = None,
    ) -> bool:
        """
        Remove a single owner from the blacklist for a given user/key.
        """
        if not owner:
            return False
        owner_key = str(owner).strip().lower()
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            cursor.execute(
                f"DELETE FROM blacklist WHERE owner = ? AND user_id = ?{key_clause}",
                (owner_key, int(user_id or 0), *key_params),
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as exc:
            logger.error(f"Error removing {owner} from blacklist: {exc}")
            return False
        finally:
            cursor.close()

    def remove_blacklist_entries(
        self, owners: list[str], user_id: int | None = None, key_id: int | None = None
    ) -> int:
        if not owners:
            return 0
        owner_keys = [str(owner).strip().lower() for owner in owners if str(owner).strip()]
        if not owner_keys:
            return 0
        placeholders = ", ".join(["?"] * len(owner_keys))
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            cursor.execute(
                f"DELETE FROM blacklist WHERE user_id = ? AND owner IN ({placeholders}){key_clause}",
                (int(user_id or 0), *owner_keys, *key_params),
            )
            self.conn.commit()
            return max(0, cursor.rowcount)
        except Exception as exc:
            logger.error(f"Error removing blacklist entries: {exc}")
            return 0
        finally:
            cursor.close()

    def log_admin_call(
        self, owner: str, chat_id: int, user_id: int | None = None, key_id: int | None = None
    ) -> bool:
        if not owner or chat_id is None:
            return False
        owner_key = str(owner).strip().lower()
        try:
            cursor = self._cursor()
            uid = int(user_id or 0)
            chat_value = int(chat_id)
            key_value = int(key_id) if key_id is not None else None
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    INSERT INTO admin_calls (user_id, chat_id, owner, count, last_called_at, key_id)
                    VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP, ?)
                    ON DUPLICATE KEY UPDATE
                        owner = VALUES(owner),
                        count = count + 1,
                        last_called_at = CURRENT_TIMESTAMP
                    """,
                    (uid, chat_value, owner_key, key_value),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO admin_calls (user_id, chat_id, owner, count, last_called_at, key_id)
                    VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP, ?)
                    ON CONFLICT(user_id, chat_id) DO UPDATE SET
                        owner = excluded.owner,
                        count = admin_calls.count + 1,
                        last_called_at = CURRENT_TIMESTAMP
                    """,
                    (uid, chat_value, owner_key, key_value),
                )
            self.conn.commit()
            return True
        except Exception as exc:
            logger.error(f"Error logging admin call for {owner}: {exc}")
            return False
        finally:
            cursor.close()

    def get_admin_call_counts(
        self, user_id: int | None = None, key_id: int | None = None
    ) -> dict:
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            cursor.execute(
                f"""
                SELECT chat_id, owner, count, last_called_at
                FROM admin_calls
                WHERE user_id = ?{key_clause}
                """,
                (int(user_id or 0), *key_params),
            )
            rows = cursor.fetchall()
            data = {}
            for row in rows:
                data[int(row[0])] = {
                    "chat_id": int(row[0]),
                    "owner": row[1],
                    "count": int(row[2] or 0),
                    "last_called_at": row[3],
                }
            return data
        except Exception as exc:
            logger.error(f"Error loading admin calls: {exc}")
            return {}
        finally:
            cursor.close()

    def get_admin_call_counts_by_owner(
        self, user_id: int | None = None, key_id: int | None = None
    ) -> dict:
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            cursor.execute(
                f"""
                SELECT owner, count, last_called_at, chat_id
                FROM admin_calls
                WHERE user_id = ?{key_clause}
                """,
                (int(user_id or 0), *key_params),
            )
            rows = cursor.fetchall()
            data = {}
            for row in rows:
                owner_key = str(row[0] or "").strip().lower()
                if not owner_key:
                    continue
                data[owner_key] = {
                    "owner": row[0],
                    "count": int(row[1] or 0),
                    "last_called_at": row[2],
                    "chat_id": row[3],
                }
            return data
        except Exception as exc:
            logger.error(f"Error loading admin calls by owner: {exc}")
            return {}
        finally:
            cursor.close()

    def clear_admin_call(
        self, chat_id: int, user_id: int | None = None, key_id: int | None = None
    ) -> bool:
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            cursor.execute(
                f"""
                DELETE FROM admin_calls
                WHERE user_id = ? AND chat_id = ?{key_clause}
                """,
                (int(user_id or 0), int(chat_id), *key_params),
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as exc:
            logger.error(f"Error clearing admin call for chat {chat_id}: {exc}")
            return False
        finally:
            cursor.close()

    def clear_blacklist(self, user_id: int | None = None, key_id: int | None = None) -> int:
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            cursor.execute(
                f"DELETE FROM blacklist WHERE user_id = ?{key_clause}",
                (int(user_id or 0), *key_params),
            )
            self.conn.commit()
            return max(0, cursor.rowcount)
        except Exception as exc:
            logger.error(f"Error clearing blacklist: {exc}")
            return 0
        finally:
            cursor.close()

    def add_time_to_owner_accounts(
        self,
        owner: str,
        hours: int,
        minutes: int = 0,
        user_id: int | None = None,
        key_id: int | None = None,
    ) -> bool:
        """
        Extract the rental_start timestamp, add the specified number of hours to it,
        and update the rental_start field for all accounts with the same owner.
        """
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            # Retrieve the current rental_start timestamps for the owner
            if user_id in (None, 0):
                cursor.execute(
                    f"""
                    SELECT ID, rental_start
                    FROM accounts
                    WHERE owner = ? AND rental_start IS NOT NULL{key_clause}
                    """,
                    (owner, *key_params),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT ID, rental_start
                    FROM accounts
                    WHERE owner = ? AND rental_start IS NOT NULL AND user_id = ?{key_clause}
                    """,
                    (owner, user_id, *key_params),
                )
            accounts = cursor.fetchall()

            if not accounts:
                logger.info(
                    f"No accounts found for owner {owner} with a valid rental_start."
                )
                return False

            # Update each account with the new timestamp
            for account_id, rental_start in accounts:
                if rental_start:
                    delta = timedelta(hours=hours, minutes=minutes)
                    if isinstance(rental_start, datetime):
                        new_rental_start = rental_start - delta
                    else:
                        new_rental_start = datetime.strptime(
                            rental_start, "%Y-%m-%d %H:%M:%S"
                        ) - delta
                    new_rental_start_str = new_rental_start.strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )

                    # Update the database with the new timestamp
                    cursor.execute(
                        f"""
                        UPDATE accounts
                        SET rental_start = ?
                        WHERE ID = ?{key_clause}
                        """,
                        (new_rental_start_str, account_id, *key_params),
                    )

            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding hours for owner {owner}: {str(e)}")
            return False
        finally:
            cursor.close()

    def get_active_users(self, user_id: int | None = None, include_mafile: bool = True, key_id: int | None = None):
        """
        Retrieve all active users from the database along with their account details.
        An active user is one who has a non-null owner and rental_start time.

        Returns:
            list: A list of dictionaries containing active user details
        """
        try:
            cursor = self._cursor()
            if user_id in (None, 0):
                cursor.execute(
                    """
                    SELECT 
                        ID,
                        account_name,
                        owner,
                        rental_start,
                        rental_duration,
                        rental_duration_minutes,
                        path_to_maFile,
                        login,
                        mafile_json,
                        account_frozen,
                        rental_frozen,
                        rental_frozen_at,
                        key_id
                    FROM accounts 
                    WHERE owner IS NOT NULL 
                    AND owner != 'OTHER_ACCOUNT'
                    ORDER BY rental_start DESC
                    """
                )
            else:
                if key_id is None:
                    cursor.execute(
                        """
                        SELECT 
                            ID,
                            account_name,
                            owner,
                            rental_start,
                            rental_duration,
                            rental_duration_minutes,
                            path_to_maFile,
                            login,
                            mafile_json,
                            account_frozen,
                            rental_frozen,
                            rental_frozen_at,
                            key_id
                        FROM accounts 
                        WHERE owner IS NOT NULL 
                        AND owner != 'OTHER_ACCOUNT'
                        AND user_id = ?
                        ORDER BY rental_start DESC
                        """,
                        (user_id,),
                    )
                else:
                    key_clause, key_params = self._key_filter(key_id, "key_id")
                    cursor.execute(
                        f"""
                        SELECT 
                            ID,
                            account_name,
                            owner,
                            rental_start,
                            rental_duration,
                            rental_duration_minutes,
                            path_to_maFile,
                            login,
                            mafile_json,
                            account_frozen,
                            rental_frozen,
                            rental_frozen_at,
                            key_id,
                            rental_order_id
                        FROM accounts 
                        WHERE owner IS NOT NULL 
                        AND owner != 'OTHER_ACCOUNT'
                        AND user_id = ?{key_clause}
                        ORDER BY rental_start DESC
                        """,
                        (user_id, *key_params),
                    )
            rows = cursor.fetchall()
            active_users = [
                {
                    "id": row[0],
                    "account_name": row[1],
                    "owner": row[2],
                    "rental_start": row[3],
                    "rental_duration": row[4],
                    "rental_duration_minutes": row[5],
                    "path_to_maFile": row[6],
                    "login": row[7],
                    "mafile_json": self._decrypt_value(row[8]) if include_mafile else None,
                    "account_frozen": row[9] if len(row) > 9 else 0,
                    "rental_frozen": row[10] if len(row) > 10 else 0,
                    "rental_frozen_at": row[11] if len(row) > 11 else None,
                    "key_id": row[12] if len(row) > 12 else None,
                    "rental_order_id": row[13] if len(row) > 13 else None,
                }
                for row in rows
            ]
            return active_users
        except Exception as e:
            logger.error(f"Error retrieving active users: {str(e)}")
            return []
        finally:
            cursor.close()

    def upsert_feedback_reward(
        self,
        order_id: str,
        owner: str,
        rating: int,
        review_text: str | None,
        user_id: int | None = None,
    ) -> bool:
        try:
            cursor = self._cursor()
            uid = int(user_id or 0)
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    INSERT INTO feedback_rewards (order_id, owner, user_id, rating, review_text)
                    VALUES (?, ?, ?, ?, ?)
                    ON DUPLICATE KEY UPDATE
                        owner = VALUES(owner),
                        user_id = VALUES(user_id),
                        rating = VALUES(rating),
                        review_text = VALUES(review_text),
                        reviewed_at = CURRENT_TIMESTAMP
                    """,
                    (order_id, owner, uid, int(rating), review_text),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO feedback_rewards (order_id, owner, user_id, rating, review_text, reviewed_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(order_id) DO UPDATE SET
                        owner = excluded.owner,
                        user_id = excluded.user_id,
                        rating = excluded.rating,
                        review_text = excluded.review_text,
                        reviewed_at = excluded.reviewed_at
                    """,
                    (order_id, owner, uid, int(rating), review_text),
                )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error upserting feedback reward: {str(e)}")
            return False
        finally:
            cursor.close()

    def get_unclaimed_feedback_reward(
        self,
        owner: str,
        min_rating: int = 5,
        user_id: int | None = None,
    ) -> dict | None:
        try:
            cursor = self._cursor()
            uid = int(user_id or 0)
            cursor.execute(
                """
                SELECT order_id, rating, review_text, reviewed_at
                FROM feedback_rewards
                WHERE owner = ? AND (user_id = ? OR user_id = 0) AND claimed_at IS NULL AND rating >= ?
                ORDER BY reviewed_at DESC
                LIMIT 1
                """,
                (owner, uid, int(min_rating)),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "order_id": row[0],
                "rating": row[1],
                "review_text": row[2],
                "reviewed_at": row[3],
            }
        except Exception as e:
            logger.error(f"Error reading feedback rewards: {str(e)}")
            return None
        finally:
            cursor.close()

    def mark_feedback_reward_claimed(
        self,
        order_id: str,
        account_id: int | None = None,
        user_id: int | None = None,
    ) -> bool:
        try:
            cursor = self._cursor()
            uid = int(user_id or 0)
            cursor.execute(
                """
                UPDATE feedback_rewards
                SET claimed_at = CURRENT_TIMESTAMP, account_id = ?
                WHERE order_id = ? AND claimed_at IS NULL AND (user_id = ? OR user_id = 0)
                """,
                (account_id, order_id, uid),
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error marking feedback reward claimed: {str(e)}")
            return False
        finally:
            cursor.close()

    def get_feedback_reward(self, order_id: str, user_id: int | None = None) -> dict | None:
        try:
            cursor = self._cursor()
            uid = int(user_id or 0)
            cursor.execute(
                """
                SELECT order_id, owner, rating, review_text, reviewed_at, claimed_at, account_id, revoked_at, user_id
                FROM feedback_rewards
                WHERE order_id = ? AND (user_id = ? OR user_id = 0)
                """,
                (order_id, uid),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "order_id": row[0],
                "owner": row[1],
                "rating": row[2],
                "review_text": row[3],
                "reviewed_at": row[4],
                "claimed_at": row[5],
                "account_id": row[6],
                "revoked_at": row[7],
                "user_id": row[8],
            }
        except Exception as e:
            logger.error(f"Error reading feedback reward: {str(e)}")
            return None
        finally:
            cursor.close()

    def mark_feedback_reward_revoked(self, order_id: str, user_id: int | None = None) -> bool:
        try:
            cursor = self._cursor()
            uid = int(user_id or 0)
            cursor.execute(
                """
                UPDATE feedback_rewards
                SET revoked_at = CURRENT_TIMESTAMP
                WHERE order_id = ? AND revoked_at IS NULL AND (user_id = ? OR user_id = 0)
                """,
                (order_id, uid),
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error marking feedback reward revoked: {str(e)}")
            return False
        finally:
            cursor.close()

    def get_user_accounts_by_name(
        self,
        owner_id: str,
        account_name: str,
        user_id: int | None = None,
        key_id: int | None = None,
    ) -> list:
        """
        Get active accounts of a specific user by account name.
        
        Args:
            owner_id (str): The owner ID
            account_name (str): The name of the account type
            
        Returns:
            list: List of active accounts with the specified name
        """
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            if user_id is None:
                cursor.execute(
                    f"""
                    SELECT ID, account_name, login, password, rental_duration, rental_duration_minutes, rental_start,
                           account_frozen, rental_frozen, rental_frozen_at
                    FROM accounts 
                    WHERE owner = ? AND account_name = ?{key_clause}
                    """,
                    (owner_id, account_name, *key_params),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT ID, account_name, login, password, rental_duration, rental_duration_minutes, rental_start,
                           account_frozen, rental_frozen, rental_frozen_at
                    FROM accounts 
                    WHERE owner = ? AND account_name = ? AND user_id = ?{key_clause}
                    """,
                    (owner_id, account_name, int(user_id), *key_params),
                )
            rows = cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "account_name": row[1],
                    "login": row[2],
                    "password": self._decrypt_value(row[3]),
                    "rental_duration": row[4],
                    "rental_duration_minutes": row[5],
                    "rental_start": row[6],
                    "account_frozen": row[7],
                    "rental_frozen": row[8],
                    "rental_frozen_at": row[9],
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Error getting user accounts by name: {str(e)}")
            return []
        finally:
            cursor.close()

    def get_user_active_accounts(
        self, owner_id: str, user_id: int | None = None, key_id: int | None = None
    ) -> list:
        """
        Get all active accounts of a specific user.
        
        Args:
            owner_id (str): The owner ID
            
        Returns:
            list: List of all active accounts for the user
        """
        try:
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            if user_id in (None, 0):
                cursor.execute(
                    f"""
                    SELECT ID, account_name, login, password, rental_duration, rental_duration_minutes, rental_start,
                           account_frozen, rental_frozen, rental_frozen_at
                    FROM accounts 
                    WHERE owner = ?{key_clause}
                    ORDER BY rental_start DESC
                    """,
                    (owner_id, *key_params),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT ID, account_name, login, password, rental_duration, rental_duration_minutes, rental_start,
                           account_frozen, rental_frozen, rental_frozen_at
                    FROM accounts 
                    WHERE owner = ? AND user_id = ?{key_clause}
                    ORDER BY rental_start DESC
                    """,
                    (owner_id, user_id, *key_params),
                )
            rows = cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "account_name": row[1],
                    "login": row[2],
                    "password": self._decrypt_value(row[3]),
                    "rental_duration": row[4],
                    "rental_duration_minutes": row[5],
                    "rental_start": row[6],
                    "account_frozen": row[7],
                    "rental_frozen": row[8],
                    "rental_frozen_at": row[9],
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Error getting user active accounts: {str(e)}")
            return []
        finally:
            cursor.close()

    def _ensure_user_owner_columns(self):
        cursor = self._cursor()
        try:
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    ALTER TABLE accounts ADD COLUMN user_id INT NULL
                    """
                )
            else:
                cursor.execute("ALTER TABLE accounts ADD COLUMN user_id INTEGER")
            self.conn.commit()
        except Exception:
            pass
        try:
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    ALTER TABLE lots ADD COLUMN user_id INT NULL
                    """
                )
            else:
                cursor.execute("ALTER TABLE lots ADD COLUMN user_id INTEGER")
            self.conn.commit()
        except Exception:
            pass
        finally:
            cursor.close()

    def _migrate_lots_schema(self):
        """Ensure lots table supports per-user mappings with composite keys (MySQL only)."""
        if self.db_type != "mysql":
            return
        cursor = self._cursor()
        try:
            # Add user_id column if missing
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = 'lots' AND column_name = 'user_id'
                """,
                (MYSQLDATABASE,),
            )
            has_user = cursor.fetchone()[0] > 0
            if not has_user:
                cursor.execute("ALTER TABLE lots ADD COLUMN user_id INT NOT NULL DEFAULT 0")

            # Ensure key_id is present and normalized
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = 'lots' AND column_name = 'key_id'
                """,
                (MYSQLDATABASE,),
            )
            has_key = cursor.fetchone()[0] > 0
            if not has_key:
                cursor.execute("ALTER TABLE lots ADD COLUMN key_id INT NOT NULL DEFAULT 0")
            try:
                cursor.execute("UPDATE lots SET key_id = 0 WHERE key_id IS NULL")
            except Exception:
                pass
            try:
                cursor.execute("ALTER TABLE lots MODIFY COLUMN key_id INT NOT NULL DEFAULT 0")
            except Exception:
                pass

            # Ensure primary key is (lot_number, user_id)
            cursor.execute(
                """
                SELECT column_name, SEQ_IN_INDEX
                FROM information_schema.statistics
                WHERE table_schema = %s AND table_name = 'lots' AND index_name = 'PRIMARY'
                ORDER BY SEQ_IN_INDEX
                """,
                (MYSQLDATABASE,),
            )
            pk_cols = [row[0] for row in cursor.fetchall()]
            if pk_cols != ["lot_number", "user_id", "key_id"]:
                cursor.execute("ALTER TABLE lots DROP PRIMARY KEY")
                cursor.execute("ALTER TABLE lots ADD PRIMARY KEY (lot_number, user_id, key_id)")

            # Ensure uniqueness of (account_id, user_id)
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.statistics
                WHERE table_schema = %s AND table_name = 'lots' AND index_name = 'uniq_account_user'
                """,
                (MYSQLDATABASE,),
            )
            has_unique = cursor.fetchone()[0] > 0
            if not has_unique:
                try:
                    cursor.execute("ALTER TABLE lots DROP INDEX account_id")
                except Exception:
                    pass
                cursor.execute("ALTER TABLE lots ADD UNIQUE KEY uniq_account_user (account_id, user_id, key_id)")
        finally:
            cursor.close()

    def update_password_by_login(self, login: str, new_password: str) -> int:
        """
        Update password for all rows sharing the same Steam login.

        Returns number of rows updated.
        """
        try:
            enc_password = self._encrypt_value(new_password)
            cursor = self._cursor()
            cursor.execute(
                """
                UPDATE accounts
                SET password = ?
                WHERE login = ?
                """,
                (enc_password, login),
            )
            updated = cursor.rowcount
            self.conn.commit()
            return int(updated or 0)
        except Exception as e:
            logger.error(f"Error updating password by login: {str(e)}")
            return 0
        finally:
            cursor.close()

    def get_user_active_lot_accounts(
        self, owner_id: str, user_id: int | None = None, key_id: int | None = None
    ) -> list:
        """
        Get all active accounts of a specific user with lot mapping info (if configured).
        """
        try:
            key_clause_accounts, key_params_accounts = self._key_filter(key_id, "a.key_id")
            key_clause_lots, key_params_lots = self._key_filter(key_id, "l.key_id")
            cursor = self._cursor()
            if user_id in (None, 0):
                cursor.execute(
                    f"""
                    SELECT a.ID, a.account_name, a.login, a.password, a.rental_duration, a.rental_duration_minutes, a.rental_start, l.lot_number, l.lot_url, a.account_frozen, a.rental_frozen, a.rental_frozen_at
                    FROM accounts a
                    LEFT JOIN lots l ON l.account_id = a.ID{key_clause_lots}
                    WHERE a.owner = ?{key_clause_accounts}
                    ORDER BY a.rental_start DESC
                    """,
                    (*key_params_lots, owner_id, *key_params_accounts),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT a.ID, a.account_name, a.login, a.password, a.rental_duration, a.rental_duration_minutes, a.rental_start, l.lot_number, l.lot_url, a.account_frozen, a.rental_frozen, a.rental_frozen_at
                    FROM accounts a
                    LEFT JOIN lots l ON l.account_id = a.ID AND l.user_id = ?{key_clause_lots}
                    WHERE a.owner = ? AND a.user_id = ?{key_clause_accounts}
                    ORDER BY a.rental_start DESC
                    """,
                    (user_id, *key_params_lots, owner_id, user_id, *key_params_accounts),
                )
            rows = cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "account_name": row[1],
                    "login": row[2],
                    "password": self._decrypt_value(row[3]),
                    "rental_duration": row[4],
                    "rental_duration_minutes": row[5],
                    "rental_start": row[6],
                    "lot_number": row[7],
                    "lot_url": row[8],
                    "account_frozen": row[9],
                    "rental_frozen": row[10],
                    "rental_frozen_at": row[11],
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Error getting user active lot accounts: {str(e)}")
            return []
        finally:
            cursor.close()

    def close(self):
        """Close the persistent database connection."""
        self.conn.close()

    # ---- User auth helpers ----

    def _hash_password(self, password: str) -> str:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def _verify_password(self, password: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
        except Exception:
            return False

    def create_user(self, username: str, password: str, golden_key: str) -> str | None:
        cursor = self._cursor()
        token = secrets.token_urlsafe(32)
        try:
            cursor.execute(
                """
                INSERT INTO users (username, password_hash, golden_key, session_token)
                VALUES (?, ?, ?, ?)
                """,
                (username, self._hash_password(password), golden_key, token),
            )
            self.conn.commit()
            try:
                cursor.execute(
                    "INSERT INTO user_keys (user_id, label, golden_key, is_default) VALUES ((SELECT id FROM users WHERE username = ?), ?, ?, 1)",
                    (username, "Default", golden_key),
                )
                self.conn.commit()
            except Exception:
                pass
            return token
        except Exception as exc:
            logger.error(f"Error creating user: {exc}")
            return None
        finally:
            cursor.close()

    def get_user_by_username(self, username: str):
        cursor = self._cursor()
        try:
            cursor.execute(
                "SELECT id, username, password_hash, golden_key, session_token FROM users WHERE username = ?",
                (username,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "username": row[1],
                "password_hash": row[2],
                "golden_key": row[3],
                "session_token": row[4],
            }
        finally:
            cursor.close()

    def get_user_by_token(self, token: str):
        cursor = self._cursor()
        try:
            cursor.execute(
                "SELECT id, username, golden_key FROM users WHERE session_token = ?",
                (token,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {"id": row[0], "username": row[1], "golden_key": row[2], "session_token": token}
        finally:
            cursor.close()

    def update_session_token(self, user_id: int, token: str) -> None:
        cursor = self._cursor()
        try:
            cursor.execute("UPDATE users SET session_token = ? WHERE id = ?", (token, user_id))
            self.conn.commit()
        finally:
            cursor.close()

    def update_golden_key(self, user_id: int, golden_key: str) -> bool:
        cursor = self._cursor()
        try:
            cursor.execute("UPDATE users SET golden_key = ? WHERE id = ?", (golden_key, user_id))
            self.conn.commit()
            try:
                cursor.execute(
                    "UPDATE user_keys SET golden_key = ?, is_default = 1 WHERE user_id = ? AND is_default = 1",
                    (golden_key, user_id),
                )
                if cursor.rowcount == 0:
                    cursor.execute(
                        "INSERT INTO user_keys (user_id, label, golden_key, is_default) VALUES (?, ?, ?, 1)",
                        (user_id, "Default", golden_key),
                    )
                self.conn.commit()
            except Exception:
                pass
            return True
        except Exception as exc:
            logger.error(f"Error updating golden key: {exc}")
            return False
        finally:
            cursor.close()

    def list_users_with_keys(self):
        cursor = self._cursor()
        try:
            cursor.execute(
                """
                SELECT u.id, u.username, uk.id as key_id, uk.golden_key,
                       uk.proxy_url, uk.proxy_username, uk.proxy_password
                FROM users u
                JOIN user_keys uk ON uk.user_id = u.id
                WHERE uk.golden_key IS NOT NULL AND uk.golden_key <> ''
                """
            )
            return [
                {
                    "id": row[0],
                    "username": row[1],
                    "key_id": row[2],
                    "golden_key": row[3],
                    "proxy_url": row[4],
                    "proxy_username": row[5],
                    "proxy_password": row[6],
                }
                for row in cursor.fetchall()
            ]
        finally:
            cursor.close()

    def _key_filter(self, key_id: int | None, column: str = "key_id") -> tuple[str, list]:
        if key_id is None:
            return "", []
        return f" AND {column} = ?", [key_id]

    # ---- User keys (multi FunPay tokens) ----

    def ensure_user_keys_for_user(self, user_id: int, golden_key: str | None = None) -> None:
        cursor = self._cursor()
        should_normalize = False
        try:
            cursor.execute("SELECT COUNT(*) FROM user_keys WHERE user_id = ?", (user_id,))
            exists = cursor.fetchone()[0] > 0
            if not exists:
                if not golden_key:
                    cursor.execute("SELECT golden_key FROM users WHERE id = ?", (user_id,))
                    row = cursor.fetchone()
                    golden_key = row[0] if row else ""
                cursor.execute(
                    "INSERT INTO user_keys (user_id, label, golden_key, is_default) VALUES (?, ?, ?, 1)",
                    (user_id, "Default", golden_key or ""),
                )
                self.conn.commit()
            should_normalize = True
        except Exception as exc:
            logger.error(f"Error ensuring default key for user {user_id}: {exc}")
        finally:
            cursor.close()
        if not should_normalize:
            return
        try:
            default_key = self.get_default_key(user_id)
            if default_key and default_key.get("id"):
                self.normalize_legacy_key_data(user_id, int(default_key["id"]))
        except Exception:
            pass

    def list_user_keys(self, user_id: int) -> list:
        cursor = self._cursor()
        try:
            cursor.execute(
                """
                SELECT id, label, is_default, created_at, proxy_url, proxy_username, proxy_password
                FROM user_keys
                WHERE user_id = ?
                ORDER BY is_default DESC, id ASC
                """,
                (user_id,),
            )
            return [
                {
                    "id": row[0],
                    "label": row[1],
                    "is_default": bool(row[2]),
                    "created_at": row[3],
                    "proxy_url": row[4],
                    "proxy_username": row[5],
                    "proxy_password": row[6],
                }
                for row in cursor.fetchall()
            ]
        finally:
            cursor.close()

    def get_user_key(self, user_id: int, key_id: int | None):
        if key_id is None:
            return None
        cursor = self._cursor()
        try:
            cursor.execute(
                """
                SELECT id, label, golden_key, is_default, proxy_url, proxy_username, proxy_password
                FROM user_keys
                WHERE user_id = ? AND id = ?
                """,
                (user_id, key_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "label": row[1],
                "golden_key": row[2],
                "is_default": bool(row[3]),
                "proxy_url": row[4],
                "proxy_username": row[5],
                "proxy_password": row[6],
            }
        finally:
            cursor.close()

    def find_user_key_by_golden_key(self, golden_key: str, exclude_user_id: int | None = None):
        golden_key = (golden_key or "").strip()
        if not golden_key:
            return None
        cursor = self._cursor()
        try:
            if exclude_user_id:
                cursor.execute(
                    """
                    SELECT user_id, id
                    FROM user_keys
                    WHERE golden_key = ? AND golden_key <> '' AND user_id <> ?
                    ORDER BY id ASC
                    LIMIT 1
                    """,
                    (golden_key, exclude_user_id),
                )
            else:
                cursor.execute(
                    """
                    SELECT user_id, id
                    FROM user_keys
                    WHERE golden_key = ? AND golden_key <> ''
                    ORDER BY id ASC
                    LIMIT 1
                    """,
                    (golden_key,),
                )
            row = cursor.fetchone()
            if not row:
                return None
            return {"user_id": row[0], "key_id": row[1]}
        finally:
            cursor.close()

    def clone_key_data(
        self,
        source_user_id: int,
        source_key_id: int | None,
        dest_user_id: int,
        dest_key_id: int,
    ) -> dict:
        cursor = self._cursor()
        counts = {
            "accounts": 0,
            "lots": 0,
            "blacklist": 0,
            "order_history": 0,
            "admin_calls": 0,
            "balance_snapshots": 0,
        }
        try:
            cursor.execute(
                "SELECT COUNT(*) FROM accounts WHERE user_id = ? AND key_id = ?",
                (dest_user_id, dest_key_id),
            )
            if cursor.fetchone()[0] > 0:
                return {"skipped": True, "reason": "destination already has accounts"}

            key_clause, key_params = self._key_filter(source_key_id, "key_id")
            cursor.execute(
                f"""
                SELECT ID, account_name, path_to_maFile, mafile_json, login, password,
                       rental_duration, rental_duration_minutes, mmr, owner, rental_start,
                       account_frozen, rental_frozen, rental_frozen_at
                FROM accounts
                WHERE user_id = ?{key_clause}
                """,
                (source_user_id, *key_params),
            )
            account_rows = cursor.fetchall()
            account_id_map: dict[int, int] = {}
            for row in account_rows:
                (
                    account_id,
                    account_name,
                    path_to_mafile,
                    mafile_json,
                    login,
                    password,
                    rental_duration,
                    rental_duration_minutes,
                    mmr,
                    owner,
                    rental_start,
                    account_frozen,
                    rental_frozen,
                    rental_frozen_at,
                ) = row
                cursor.execute(
                    """
                    INSERT INTO accounts (
                        account_name, path_to_maFile, mafile_json, login, password,
                        rental_duration, rental_duration_minutes, mmr, owner, rental_start,
                        account_frozen, rental_frozen, rental_frozen_at, user_id, key_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        account_name,
                        path_to_mafile,
                        mafile_json,
                        login,
                        password,
                        rental_duration,
                        rental_duration_minutes,
                        mmr,
                        owner,
                        rental_start,
                        account_frozen,
                        rental_frozen,
                        rental_frozen_at,
                        dest_user_id,
                        dest_key_id,
                    ),
                )
                new_id = cursor.lastrowid
                account_id_map[int(account_id)] = int(new_id)
                counts["accounts"] += 1

            cursor.execute(
                f"""
                SELECT lot_number, account_id, lot_url
                FROM lots
                WHERE user_id = ?{key_clause}
                """,
                (source_user_id, *key_params),
            )
            for lot_number, account_id, lot_url in cursor.fetchall():
                new_account_id = account_id_map.get(int(account_id or 0))
                if not new_account_id:
                    continue
                try:
                    cursor.execute(
                        """
                        INSERT INTO lots (lot_number, account_id, lot_url, user_id, key_id)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (lot_number, new_account_id, lot_url, dest_user_id, dest_key_id),
                    )
                    counts["lots"] += 1
                except Exception:
                    continue

            cursor.execute(
                f"""
                SELECT owner, reason, created_at
                FROM blacklist
                WHERE user_id = ?{key_clause}
                """,
                (source_user_id, *key_params),
            )
            for owner, reason, created_at in cursor.fetchall():
                cursor.execute(
                    """
                    INSERT INTO blacklist (owner, reason, user_id, key_id, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (owner, reason, dest_user_id, dest_key_id, created_at),
                )
                counts["blacklist"] += 1

            cursor.execute(
                f"""
                SELECT order_id, owner, account_name, account_id, steam_id, rental_minutes,
                       lot_number, amount, price, action, created_at
                FROM order_history
                WHERE user_id = ?{key_clause}
                """,
                (source_user_id, *key_params),
            )
            for row in cursor.fetchall():
                (
                    order_id,
                    owner,
                    account_name,
                    account_id,
                    steam_id,
                    rental_minutes,
                    lot_number,
                    amount,
                    price,
                    action,
                    created_at,
                ) = row
                mapped_account_id = account_id_map.get(int(account_id)) if account_id is not None else None
                cursor.execute(
                    """
                    INSERT INTO order_history (
                        order_id, owner, account_name, account_id, steam_id, rental_minutes,
                        lot_number, amount, price, action, user_id, key_id, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        order_id,
                        owner,
                        account_name,
                        mapped_account_id,
                        steam_id,
                        rental_minutes,
                        lot_number,
                        amount,
                        price,
                        action,
                        dest_user_id,
                        dest_key_id,
                        created_at,
                    ),
                )
                counts["order_history"] += 1

            cursor.execute(
                f"""
                SELECT chat_id, owner, count, last_called_at
                FROM admin_calls
                WHERE user_id = ?{key_clause}
                """,
                (source_user_id, *key_params),
            )
            for chat_id, owner, count, last_called_at in cursor.fetchall():
                cursor.execute(
                    """
                    INSERT INTO admin_calls (user_id, chat_id, owner, count, last_called_at, key_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (dest_user_id, chat_id, owner, count, last_called_at, dest_key_id),
                )
                counts["admin_calls"] += 1

            cursor.execute(
                f"""
                SELECT total_rub, available_rub, total_usd, total_eur, created_at
                FROM funpay_balance_snapshots
                WHERE user_id = ?{key_clause}
                """,
                (source_user_id, *key_params),
            )
            for total_rub, available_rub, total_usd, total_eur, created_at in cursor.fetchall():
                cursor.execute(
                    """
                    INSERT INTO funpay_balance_snapshots (
                        user_id, total_rub, available_rub, total_usd, total_eur, created_at, key_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        dest_user_id,
                        total_rub,
                        available_rub,
                        total_usd,
                        total_eur,
                        created_at,
                        dest_key_id,
                    ),
                )
                counts["balance_snapshots"] += 1

            self.conn.commit()
            return {"success": True, **counts}
        except Exception as exc:
            logger.error(f"Error cloning workspace data: {exc}")
            return {"success": False, "error": str(exc)}
        finally:
            cursor.close()

    def add_user_key(
        self,
        user_id: int,
        label: str,
        golden_key: str,
        make_default: bool = False,
        proxy_url: str | None = None,
        proxy_username: str | None = None,
        proxy_password: str | None = None,
    ) -> int | None:
        cursor = self._cursor()
        try:
            cursor.execute(
                "SELECT id FROM user_keys WHERE user_id = ? AND golden_key = ? LIMIT 1",
                (user_id, golden_key),
            )
            row = cursor.fetchone()
            if row:
                key_id = int(row[0])
                if make_default:
                    cursor.execute("UPDATE user_keys SET is_default = 0 WHERE user_id = ?", (user_id,))
                    cursor.execute("UPDATE user_keys SET is_default = 1 WHERE user_id = ? AND id = ?", (user_id, key_id))
                    cursor.execute("UPDATE users SET golden_key = ? WHERE id = ?", (golden_key, user_id))
                cursor.execute(
                    "UPDATE user_keys SET proxy_url = ?, proxy_username = ?, proxy_password = ? WHERE id = ?",
                    (proxy_url, proxy_username, proxy_password, key_id),
                )
                self.conn.commit()
                return key_id
            cursor.execute(
                """
                INSERT INTO user_keys (user_id, label, golden_key, is_default, proxy_url, proxy_username, proxy_password)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, label, golden_key, 1 if make_default else 0, proxy_url, proxy_username, proxy_password),
            )
            key_id = cursor.lastrowid
            if make_default:
                cursor.execute("UPDATE user_keys SET is_default = 0 WHERE user_id = ? AND id <> ?", (user_id, key_id))
                cursor.execute("UPDATE users SET golden_key = ? WHERE id = ?", (golden_key, user_id))
            self.conn.commit()
            return key_id
        except Exception as exc:
            logger.error(f"Error adding user key: {exc}")
            return None
        finally:
            cursor.close()

    def update_user_key(
        self,
        user_id: int,
        key_id: int,
        label: str | None = None,
        golden_key: str | None = None,
        make_default: bool | None = None,
        proxy_url: str | None = None,
        proxy_username: str | None = None,
        proxy_password: str | None = None,
    ) -> bool:
        cursor = self._cursor()
        try:
            sets = []
            params = []
            if label is not None:
                sets.append("label = ?")
                params.append(label)
            if golden_key is not None:
                sets.append("golden_key = ?")
                params.append(golden_key)
            if proxy_url is not None:
                sets.append("proxy_url = ?")
                params.append(proxy_url)
            if proxy_username is not None:
                sets.append("proxy_username = ?")
                params.append(proxy_username)
            if proxy_password is not None:
                sets.append("proxy_password = ?")
                params.append(proxy_password)
            if sets:
                params.extend([user_id, key_id])
                cursor.execute(f"UPDATE user_keys SET {', '.join(sets)} WHERE user_id = ? AND id = ?", params)
            if make_default:
                cursor.execute("UPDATE user_keys SET is_default = 0 WHERE user_id = ?", (user_id,))
                cursor.execute("UPDATE user_keys SET is_default = 1 WHERE user_id = ? AND id = ?", (user_id, key_id))
            if golden_key is not None and make_default:
                cursor.execute("UPDATE users SET golden_key = ? WHERE id = ?", (golden_key, user_id))
            self.conn.commit()
            return True
        except Exception as exc:
            logger.error(f"Error updating user key: {exc}")
            return False
        finally:
            cursor.close()

    def delete_user_key(self, user_id: int, key_id: int) -> bool:
        cursor = self._cursor()
        try:
            cursor.execute(
                "SELECT id, golden_key, is_default FROM user_keys WHERE user_id = ? AND id = ?",
                (user_id, key_id),
            )
            row = cursor.fetchone()
            if not row:
                return False
            is_default = bool(row[2])

            cursor.execute("DELETE FROM lots WHERE user_id = ? AND key_id = ?", (user_id, key_id))
            cursor.execute("DELETE FROM accounts WHERE user_id = ? AND key_id = ?", (user_id, key_id))
            cursor.execute("DELETE FROM order_history WHERE user_id = ? AND key_id = ?", (user_id, key_id))
            cursor.execute("DELETE FROM blacklist WHERE user_id = ? AND key_id = ?", (user_id, key_id))
            cursor.execute("DELETE FROM admin_calls WHERE user_id = ? AND key_id = ?", (user_id, key_id))
            cursor.execute(
                "DELETE FROM funpay_balance_snapshots WHERE user_id = ? AND key_id = ?",
                (user_id, key_id),
            )

            cursor.execute("DELETE FROM user_keys WHERE user_id = ? AND id = ?", (user_id, key_id))
            if is_default:
                cursor.execute(
                    "SELECT id, golden_key FROM user_keys WHERE user_id = ? ORDER BY id ASC LIMIT 1",
                    (user_id,),
                )
                fallback = cursor.fetchone()
                if fallback:
                    cursor.execute(
                        "UPDATE user_keys SET is_default = 1 WHERE user_id = ? AND id = ?",
                        (user_id, fallback[0]),
                    )
                    cursor.execute(
                        "UPDATE users SET golden_key = ? WHERE id = ?",
                        (fallback[1], user_id),
                    )
                else:
                    cursor.execute("UPDATE users SET golden_key = '' WHERE id = ?", (user_id,))
            self.conn.commit()
            return True
        except Exception as exc:
            logger.error(f"Error deleting user key: {exc}")
            return False
        finally:
            cursor.close()

    def get_default_key(self, user_id: int):
        cursor = self._cursor()
        try:
            cursor.execute(
                """
                SELECT id, label, golden_key, proxy_url, proxy_username, proxy_password
                FROM user_keys
                WHERE user_id = ? AND is_default = 1
                LIMIT 1
                """,
                (user_id,),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "label": row[1],
                    "golden_key": row[2],
                    "proxy_url": row[3],
                    "proxy_username": row[4],
                    "proxy_password": row[5],
                }
            cursor.execute(
                """
                SELECT id, label, golden_key, proxy_url, proxy_username, proxy_password
                FROM user_keys
                WHERE user_id = ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (user_id,),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "label": row[1],
                    "golden_key": row[2],
                    "proxy_url": row[3],
                    "proxy_username": row[4],
                    "proxy_password": row[5],
                }
            return None
        finally:
            cursor.close()

    def normalize_legacy_key_data(self, user_id: int, default_key_id: int) -> None:
        cursor = self._cursor()
        try:
            tables = [
                "accounts",
                "lots",
                "blacklist",
                "order_history",
                "admin_calls",
                "funpay_balance_snapshots",
            ]
            for table in tables:
                cursor.execute(
                    f"UPDATE {table} SET key_id = ? WHERE user_id = ? AND (key_id IS NULL OR key_id = 0)",
                    (default_key_id, user_id),
                )
            self.conn.commit()
        except Exception as exc:
            logger.error(f"Error normalizing legacy keys for user {user_id}: {exc}")
        finally:
            cursor.close()

    def normalize_orphan_keys(self, user_id: int) -> None:
        cursor = self._cursor()
        try:
            default = self.get_default_key(user_id)
            if not default or not default.get("id"):
                return
            default_id = int(default["id"])
            tables = [
                "accounts",
                "lots",
                "blacklist",
                "order_history",
                "admin_calls",
                "funpay_balance_snapshots",
            ]
            for table in tables:
                cursor.execute(
                    f"""
                    UPDATE {table}
                    SET key_id = ?
                    WHERE user_id = ?
                      AND (
                        key_id IS NULL
                        OR key_id = 0
                        OR key_id NOT IN (SELECT id FROM user_keys WHERE user_id = ?)
                      )
                    """,
                    (default_id, user_id, user_id),
                )
            self.conn.commit()
        except Exception as exc:
            logger.error(f"Error normalizing orphan keys for user {user_id}: {exc}")
        finally:
            cursor.close()

    def purge_orphan_key_data(self, user_id: int) -> None:
        """Remove data whose key_id does not belong to the user's existing workspaces."""
        cursor = self._cursor()
        try:
            cursor.execute("SELECT id FROM user_keys WHERE user_id = ?", (user_id,))
            valid_ids = [int(row[0]) for row in cursor.fetchall()]
            placeholders = ",".join("?" for _ in valid_ids) if valid_ids else ""
            tables = [
                "lots",
                "accounts",
                "blacklist",
                "order_history",
                "admin_calls",
                "funpay_balance_snapshots",
            ]
            for table in tables:
                if valid_ids:
                    cursor.execute(
                        f"DELETE FROM {table} WHERE user_id = ? AND key_id IS NOT NULL AND key_id NOT IN ({placeholders})",
                        (user_id, *valid_ids),
                    )
                else:
                    cursor.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
            self.conn.commit()
        except Exception as exc:
            logger.error(f"Error purging orphan key data for user {user_id}: {exc}")
        finally:
            cursor.close()

    def has_any_golden_key(self) -> bool:
        cursor = self._cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM users WHERE golden_key IS NOT NULL AND golden_key <> ''")
            row = cursor.fetchone()
            return bool(row and row[0] > 0)
        finally:
            cursor.close()

    def logout_token(self, token: str) -> None:
        cursor = self._cursor()
        try:
            cursor.execute("UPDATE users SET session_token = NULL WHERE session_token = ?", (token,))
            self.conn.commit()
        finally:
            cursor.close()

    def create_session(self, user_id: int, expires_at: datetime, last_seen_at: datetime | None = None) -> str:
        session_id = secrets.token_urlsafe(32)
        cursor = self._cursor()
        try:
            cursor.execute(
                """
                INSERT INTO sessions (session_id, user_id, expires_at, last_seen_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, user_id, expires_at.strftime("%Y-%m-%d %H:%M:%S"),
                 last_seen_at.strftime("%Y-%m-%d %H:%M:%S") if last_seen_at else None),
            )
            self.conn.commit()
            return session_id
        finally:
            cursor.close()

    def get_session(self, session_id: str):
        cursor = self._cursor()
        try:
            cursor.execute(
                """
                SELECT session_id, user_id, expires_at, last_seen_at
                FROM sessions
                WHERE session_id = ?
                """,
                (session_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "session_id": row[0],
                "user_id": row[1],
                "expires_at": row[2],
                "last_seen_at": row[3],
            }
        finally:
            cursor.close()

    def get_session_user(self, session_id: str):
        cursor = self._cursor()
        try:
            cursor.execute(
                """
                SELECT s.session_id, s.user_id, s.expires_at, s.last_seen_at, u.username, u.golden_key
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.session_id = ?
                """,
                (session_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "session_id": row[0],
                "user_id": row[1],
                "expires_at": row[2],
                "last_seen_at": row[3],
                "username": row[4],
                "golden_key": row[5],
            }
        finally:
            cursor.close()

    def refresh_session(self, session_id: str, expires_at: datetime, last_seen_at: datetime) -> None:
        cursor = self._cursor()
        try:
            cursor.execute(
                """
                UPDATE sessions
                SET expires_at = ?, last_seen_at = ?
                WHERE session_id = ?
                """,
                (
                    expires_at.strftime("%Y-%m-%d %H:%M:%S"),
                    last_seen_at.strftime("%Y-%m-%d %H:%M:%S"),
                    session_id,
                ),
            )
            self.conn.commit()
        finally:
            cursor.close()

    def delete_session(self, session_id: str) -> None:
        cursor = self._cursor()
        try:
            cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            self.conn.commit()
        finally:
            cursor.close()

    def verify_user_credentials(self, username: str, password: str):
        user = self.get_user_by_username(username)
        if not user:
            return None
        if not self._verify_password(password, user["password_hash"]):
            return None
        return user

    def add_authorized_user(self, user_id: int) -> bool:
        """Add a user to the authorized users list."""
        try:
            cursor = self._cursor()
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    INSERT IGNORE INTO authorized_users (user_id)
                    VALUES (?)
                    """,
                    (user_id,),
                )
            else:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO authorized_users (user_id)
                    VALUES (?)
                    """,
                    (user_id,),
                )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding authorized user: {str(e)}")
            return False
        finally:
            cursor.close()

    def get_authorized_users(self) -> list:
        """Retrieve all authorized user IDs."""
        try:
            cursor = self._cursor()
            cursor.execute("SELECT user_id FROM authorized_users")
            users = [row[0] for row in cursor.fetchall()]
            return users
        except Exception as e:
            logger.error(f"Error retrieving authorized users: {str(e)}")
            return []
        finally:
            cursor.close()

    def extend_rental_duration(
        self,
        account_id: int,
        additional_hours: int,
        additional_minutes: int = 0,
        user_id: int | None = None,
        key_id: int | None = None,
    ) -> bool:
        """
        Extend the rental duration for a specific account.
        
        Args:
            account_id (int): The ID of the account to extend
            additional_hours (int): Number of hours to add to the rental duration
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            total_minutes = int(additional_hours) * 60 + int(additional_minutes)
            if total_minutes <= 0:
                return False
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            if user_id in (None, 0):
                cursor.execute(
                    f"""
                    UPDATE accounts 
                    SET rental_duration_minutes = COALESCE(rental_duration_minutes, rental_duration * 60) + ?,
                        rental_duration = rental_duration + ?
                    WHERE ID = ? AND owner IS NOT NULL AND owner != 'OTHER_ACCOUNT'{key_clause}
                    """,
                    (total_minutes, additional_hours, account_id, *key_params),
                )
            else:
                cursor.execute(
                    f"""
                    UPDATE accounts 
                    SET rental_duration_minutes = COALESCE(rental_duration_minutes, rental_duration * 60) + ?,
                        rental_duration = rental_duration + ?
                    WHERE ID = ? AND owner IS NOT NULL AND owner != 'OTHER_ACCOUNT' AND user_id = ?{key_clause}
                    """,
                    (total_minutes, additional_hours, account_id, user_id, *key_params),
                )
            success = cursor.rowcount > 0
            self.conn.commit()
            return success
        except Exception as e:
            logger.error(f"Error extending rental duration: {str(e)}")
            return False
        finally:
            cursor.close()

    def extend_rental_duration_for_owner(
        self,
        account_id: int,
        owner_id: str,
        additional_hours: int,
        additional_minutes: int = 0,
        key_id: int | None = None,
    ) -> bool:
        """
        Extend rental duration, but only if the account is currently owned by the given owner.
        """
        try:
            total_minutes = int(additional_hours) * 60 + int(additional_minutes)
            if total_minutes <= 0:
                return False
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            cursor.execute(
                f"""
                UPDATE accounts
                SET rental_duration_minutes = COALESCE(rental_duration_minutes, rental_duration * 60) + ?,
                    rental_duration = rental_duration + ?
                WHERE ID = ? AND owner = ?{key_clause}
                """,
                (total_minutes, additional_hours, account_id, owner_id, *key_params),
            )
            success = cursor.rowcount > 0
            self.conn.commit()
            return success
        except Exception as e:
            logger.error(f"Error extending rental duration for owner: {str(e)}")
            return False
        finally:
            cursor.close()

    def reduce_rental_duration_for_owner(
        self,
        account_id: int,
        owner_id: str,
        reduce_hours: int,
        reduce_minutes: int = 0,
        key_id: int | None = None,
    ) -> bool:
        """
        Reduce rental duration, but only if the account is currently owned by the given owner.
        """
        try:
            total_minutes = int(reduce_hours) * 60 + int(reduce_minutes)
            if total_minutes <= 0:
                return False
            key_clause, key_params = self._key_filter(key_id, "key_id")
            cursor = self._cursor()
            cursor.execute(
                f"""
                UPDATE accounts
                SET rental_duration_minutes = CASE
                        WHEN COALESCE(rental_duration_minutes, rental_duration * 60) > ?
                        THEN COALESCE(rental_duration_minutes, rental_duration * 60) - ?
                        ELSE 0
                    END,
                    rental_duration = CASE
                        WHEN COALESCE(rental_duration, 0) > ?
                        THEN COALESCE(rental_duration, 0) - ?
                        ELSE 0
                    END
                WHERE ID = ? AND owner = ?{key_clause}
                """,
                (total_minutes, total_minutes, reduce_hours, reduce_hours, account_id, owner_id, *key_params),
            )
            success = cursor.rowcount > 0
            self.conn.commit()
            return success
        except Exception as e:
            logger.error(f"Error reducing rental duration for owner: {str(e)}")
            return False
        finally:
            cursor.close()
