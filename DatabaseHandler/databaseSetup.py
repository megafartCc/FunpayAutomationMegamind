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
                    rental_start DATETIME DEFAULT NULL
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
                    lot_number INT PRIMARY KEY,
                    account_id INT NOT NULL UNIQUE,
                    lot_url TEXT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
                CREATE TABLE IF NOT EXISTS ai_memory_facts (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    owner VARCHAR(255) NOT NULL,
                    user_id INT NOT NULL DEFAULT 0,
                    fact TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_memory_owner (owner, user_id, id)
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
                    lot_number INT NULL,
                    amount INT DEFAULT 1,
                    price DECIMAL(10,2) NULL,
                    action VARCHAR(32) NOT NULL,
                    user_id INT NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_order_owner_created (owner, created_at),
                    INDEX idx_order_user_owner (user_id, owner)
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
                    lot_number INTEGER PRIMARY KEY,
                    account_id INTEGER NOT NULL UNIQUE,
                    lot_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
                CREATE TABLE IF NOT EXISTS ai_memory_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner TEXT NOT NULL,
                    user_id INTEGER NOT NULL DEFAULT 0,
                    fact TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        self.conn.commit()
        cursor.close()
        self._ensure_mafile_column()
        self._ensure_rental_duration_minutes_column()
        self._ensure_mmr_column()
        self._ensure_lot_url_column()
        self._ensure_users_table()
        self._ensure_user_owner_columns()
        self._ensure_feedback_rewards_table()
        self._ensure_blacklist_table()
        self._ensure_feedback_rewards_revoked_column()
        self._migrate_lots_schema()

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
    ):
        """Add an account to the database."""
        cursor = None
        try:
            # Проверяем, не существует ли уже аккаунт с таким названием
            existing_account = self.get_account_by_name(account_name)
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

            cursor = self._cursor()
            cursor.execute(
                """
                INSERT INTO accounts (
                    account_name, path_to_maFile, mafile_json, login, password, rental_duration, rental_duration_minutes, mmr, owner, user_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            WHERE owner IS NULL
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

    def set_account_owner(self, account_id: int, owner_id: str, user_id: int | None = None) -> bool:
        """
        Set the owner of an account and record the rental start time with a +3 hours offset.
        Also marks all accounts with the same login as 'OTHER_ACCOUNT'.
        """
        try:
            cursor = self._cursor()
            rental_start = (datetime.utcnow() + timedelta(hours=3)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            # Update owner and set rental start time
            if user_id in (None, 0):
                cursor.execute(
                    """
                    UPDATE accounts 
                    SET owner = ?, rental_start = ?
                    WHERE ID = ? AND owner IS NULL
                    """,
                    (owner_id, rental_start, account_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE accounts 
                    SET owner = ?, rental_start = ?
                    WHERE ID = ? AND owner IS NULL AND user_id = ?
                    """,
                    (owner_id, rental_start, account_id, user_id),
                )
            if cursor.rowcount == 0:
                return False
            # Get the login of the updated account
            if user_id in (None, 0):
                cursor.execute(
                    """
                    SELECT login 
                    FROM accounts 
                    WHERE ID = ?
                    """,
                    (account_id,),
                )
            else:
                cursor.execute(
                    """
                    SELECT login 
                    FROM accounts 
                    WHERE ID = ? AND user_id = ?
                    """,
                    (account_id, user_id),
                )
            login_row = cursor.fetchone()
            if login_row:
                login = login_row[0]
                # Mark all accounts with the same login as 'OTHER_ACCOUNT'
                if user_id in (None, 0):
                    cursor.execute(
                        """
                        UPDATE accounts 
                        SET owner = 'OTHER_ACCOUNT'
                        WHERE login = ? AND owner IS NULL
                        """,
                        (login,),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE accounts 
                        SET owner = 'OTHER_ACCOUNT'
                        WHERE login = ? AND owner IS NULL AND user_id = ?
                        """,
                        (login, user_id),
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

    def get_owner_mafile(self, owner_id: str) -> list:
        """
        Retrieve the .maFile path and account details from the most recent account
        associated with the given owner ID.
        """
        cursor = self._cursor()
        cursor.execute(
            """
            SELECT ID, account_name, path_to_maFile, mafile_json, login, rental_duration
            FROM accounts 
            WHERE owner = ?
            ORDER BY rental_start DESC
            """,
            (owner_id,),
        )
        rows = cursor.fetchall()
        cursor.close()
        return [
            (row[0], row[1], row[2], self._decrypt_value(row[3]), row[4], row[5])
            for row in rows
        ]

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

    def get_all_accounts(self, user_id: int | None = None):
        """Retrieve all accounts from the database."""
        cursor = self._cursor()
        if user_id is None:
            cursor.execute(
                """
                SELECT ID, account_name, path_to_maFile, login, password, rental_duration, rental_duration_minutes, mmr, owner, rental_start, user_id, mafile_json
                FROM accounts
                """
            )
        else:
            cursor.execute(
                """
                SELECT ID, account_name, path_to_maFile, login, password, rental_duration, rental_duration_minutes, mmr, owner, rental_start, user_id, mafile_json
                FROM accounts
                WHERE user_id = ?
                """,
                (user_id,),
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
            }
            for row in rows
        ]
        return accounts

    def list_lot_mappings(self, user_id: int | None = None) -> list:
        cursor = self._cursor()
        if user_id is None:
            cursor.execute(
                """
                SELECT l.lot_number, l.account_id, l.lot_url, a.account_name, a.owner
                FROM lots l
                JOIN accounts a ON a.ID = l.account_id
                ORDER BY l.lot_number
                """
            )
        else:
            cursor.execute(
                """
                SELECT l.lot_number, l.account_id, l.lot_url, a.account_name, a.owner
                FROM lots l
                JOIN accounts a ON a.ID = l.account_id
                WHERE l.user_id = ?
                ORDER BY l.lot_number
                """,
                (user_id,),
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
            }
            for row in rows
        ]

    def set_lot_mapping(self, lot_number: int, account_id: int, lot_url: str | None = None, user_id: int | None = None) -> bool:
        cursor = self._cursor()
        try:
            effective_user_id = user_id if user_id is not None else 0
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
                "REPLACE INTO lots (lot_number, account_id, lot_url, user_id) VALUES (?, ?, ?, ?)",
                (lot_number, account_id, lot_url, effective_user_id),
            )
            self.conn.commit()
            return True
        finally:
            if self.db_type == "mysql":
                cursor.close()

    def delete_lot_mapping(self, lot_number: int, user_id: int | None = None) -> None:
        cursor = self._cursor()
        if user_id in (None, 0):
            cursor.execute("DELETE FROM lots WHERE lot_number = ?", (lot_number,))
        else:
            cursor.execute("DELETE FROM lots WHERE lot_number = ? AND user_id = ?", (lot_number, user_id))
        if self.db_type == "mysql":
            cursor.close()

    def get_lot_mapping(self, lot_number: int, user_id: int | None = None):
        cursor = self._cursor()
        if user_id in (None, 0):
            cursor.execute(
                """
                SELECT l.lot_number, l.account_id, l.lot_url, a.account_name
                FROM lots l
                JOIN accounts a ON a.ID = l.account_id
                WHERE l.lot_number = ?
                """,
                (lot_number,),
            )
        else:
            cursor.execute(
                """
                SELECT l.lot_number, l.account_id, l.lot_url, a.account_name
                FROM lots l
                JOIN accounts a ON a.ID = l.account_id
                WHERE l.lot_number = ? AND l.user_id = ?
                """,
                (lot_number, user_id),
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

    def get_account_by_lot_number(self, lot_number: int, user_id: int | None = None):
        cursor = self._cursor()
        if user_id is None:
            cursor.execute(
                """
                SELECT a.ID, a.account_name, a.login, a.password, a.rental_duration, a.rental_duration_minutes, a.mmr, a.owner, a.rental_start, a.mafile_json
                FROM lots l
                JOIN accounts a ON a.ID = l.account_id
                WHERE l.lot_number = ?
                """,
                (lot_number,),
            )
        else:
            cursor.execute(
                """
                SELECT a.ID, a.account_name, a.login, a.password, a.rental_duration, a.rental_duration_minutes, a.mmr, a.owner, a.rental_start, a.mafile_json
                FROM lots l
                JOIN accounts a ON a.ID = l.account_id
                WHERE l.lot_number = ? AND l.user_id = ?
                """,
                (lot_number, user_id),
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

    def get_available_lot_accounts(self, user_id: int | None = None) -> list:
        cursor = self._cursor()
        if user_id is None:
            cursor.execute(
                """
                SELECT a.ID, a.account_name, a.owner, a.rental_start, a.rental_duration, a.rental_duration_minutes, a.mmr, l.lot_number, l.lot_url
                FROM lots l
                JOIN accounts a ON a.ID = l.account_id
                WHERE a.owner IS NULL
                ORDER BY l.lot_number
                """
            )
        else:
            cursor.execute(
                """
                SELECT a.ID, a.account_name, a.owner, a.rental_start, a.rental_duration, a.rental_duration_minutes, a.mmr, l.lot_number, l.lot_url
                FROM lots l
                JOIN accounts a ON a.ID = l.account_id
                WHERE a.owner IS NULL AND a.user_id = ?
                ORDER BY l.lot_number
                """,
                (user_id,),
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

    def get_all_lot_accounts(self, user_id: int | None = None) -> list:
        cursor = self._cursor()
        if user_id is None:
            cursor.execute(
                """
                SELECT a.ID, a.account_name, a.owner, a.rental_start, a.rental_duration, a.rental_duration_minutes, a.mmr, l.lot_number, l.lot_url
                FROM lots l
                JOIN accounts a ON a.ID = l.account_id
                ORDER BY l.lot_number
                """
            )
        else:
            cursor.execute(
                """
                SELECT a.ID, a.account_name, a.owner, a.rental_start, a.rental_duration, a.rental_duration_minutes, a.mmr, l.lot_number, l.lot_url
                FROM lots l
                JOIN accounts a ON a.ID = l.account_id
                WHERE l.user_id = ?
                ORDER BY l.lot_number
                """,
                (user_id,),
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
    ) -> list:
        cursor = self._cursor()
        low = int(target_mmr) - int(mmr_range)
        high = int(target_mmr) + int(mmr_range)
        if user_id is None:
            cursor.execute(
                """
                SELECT a.ID, a.account_name, a.mmr, a.owner, a.rental_start,
                       a.rental_duration, a.rental_duration_minutes,
                       l.lot_number, l.lot_url
                FROM accounts a
                LEFT JOIN lots l ON l.account_id = a.ID
                WHERE a.mmr BETWEEN ? AND ?
                ORDER BY a.mmr, a.ID
                """,
                (low, high),
            )
        else:
            cursor.execute(
                """
                SELECT a.ID, a.account_name, a.mmr, a.owner, a.rental_start,
                       a.rental_duration, a.rental_duration_minutes,
                       l.lot_number, l.lot_url
                FROM accounts a
                LEFT JOIN lots l ON l.account_id = a.ID AND l.user_id = ?
                WHERE a.user_id = ? AND a.mmr BETWEEN ? AND ?
                ORDER BY a.mmr, a.ID
                """,
                (user_id, user_id, low, high),
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

    def delete_account_by_id(self, account_id: int, user_id: int | None = None) -> bool:
        """
        Delete all accounts that share the same login as the account with the given ID.
        """
        try:
            cursor = self._cursor()
            if user_id in (None, 0):
                cursor.execute(
                    """
                    SELECT login
                    FROM accounts
                    WHERE ID = ?
                    """,
                    (account_id,),
                )
            else:
                cursor.execute(
                    """
                    SELECT login
                    FROM accounts
                    WHERE ID = ? AND user_id = ?
                    """,
                    (account_id, user_id),
                )
            result = cursor.fetchone()
            if not result:
                logger.error(f"No account found with ID {account_id}.")
                return False
            login = result[0]
            if user_id in (None, 0):
                cursor.execute(
                    """
                    DELETE FROM accounts
                    WHERE login = ?
                    """,
                    (login,),
                )
            else:
                cursor.execute(
                    """
                    DELETE FROM accounts
                    WHERE login = ? AND user_id = ?
                    """,
                    (login, user_id),
                )
            success = cursor.rowcount > 0
            self.conn.commit()
            return success
        except Exception as e:
            logger.error(f"Error deleting accounts: {str(e)}")
            return False
        finally:
            cursor.close()

    def release_account(self, account_id: int, user_id: int | None = None) -> bool:
        """Clear owner and rental start for an account."""
        try:
            cursor = self._cursor()
            if user_id in (None, 0):
                cursor.execute(
                    """
                    UPDATE accounts
                    SET owner = NULL, rental_start = NULL
                    WHERE ID = ?
                    """,
                    (account_id,),
                )
            else:
                cursor.execute(
                    """
                    UPDATE accounts
                    SET owner = NULL, rental_start = NULL
                    WHERE ID = ? AND user_id = ?
                    """,
                    (account_id, user_id),
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

    def update_account(self, account_id: int, fields: dict, user_id: int | None = None) -> bool:
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
        }
        updates = {key: value for key, value in fields.items() if key in allowed_fields}
        if not updates:
            return False
        if "mafile_json" in updates:
            updates["mafile_json"] = self._encrypt_value(self._normalize_mafile(updates["mafile_json"]))
        if "password" in updates:
            updates["password"] = self._encrypt_value(updates["password"])

        try:
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
                WHERE ID = ?{where_user}
                """,
                values,
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

    def get_all_account_names(self) -> list:
        """Retrieve all distinct account names."""
        try:
            cursor = self._cursor()
            cursor.execute("SELECT account_name FROM accounts")
            account_names = [row[0] for row in cursor.fetchall()]
            return account_names
        except Exception as e:
            logger.error(f"Error retrieving account names: {str(e)}")
            return []
        finally:
            cursor.close()

    def get_unowned_account_names(self) -> list:
        """Retrieve account names for accounts with no owner."""
        try:
            cursor = self._cursor()
            cursor.execute("SELECT account_name FROM accounts WHERE owner IS NULL")
            unowned_account_names = [row[0] for row in cursor.fetchall()]
            return unowned_account_names
        except Exception as e:
            logger.error(f"Error retrieving unowned account names: {str(e)}")
            return []
        finally:
            cursor.close()

    def get_account_by_name(self, account_name: str):
        """Get account by its name."""
        try:
            cursor = self._cursor()
            cursor.execute(
                """
                SELECT ID, account_name, path_to_maFile, login, password, rental_duration, rental_duration_minutes, mmr, owner, rental_start
                FROM accounts 
                WHERE account_name = ?
                """,
                (account_name,)
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

    def get_account_by_id(self, account_id: int, user_id: int | None = None) -> dict:
        """
        Get account details by ID.
        
        Args:
            account_id (int): The ID of the account
            
        Returns:
            dict: Account details or None if not found
        """
        try:
            cursor = self._cursor()
            if user_id is None:
                cursor.execute(
                    """
                    SELECT ID, account_name, path_to_maFile, login, password, 
                           rental_duration, rental_duration_minutes, mmr, owner, rental_start, mafile_json
                    FROM accounts 
                    WHERE ID = ?
                    """,
                    (account_id,),
                )
            else:
                cursor.execute(
                    """
                    SELECT ID, account_name, path_to_maFile, login, password, 
                           rental_duration, rental_duration_minutes, mmr, owner, rental_start, mafile_json
                    FROM accounts 
                    WHERE ID = ? AND user_id = ?
                    """,
                    (account_id, user_id),
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
                }
            return None
        except Exception as e:
            logger.error(f"Error getting account by ID: {str(e)}")
            return None
        finally:
            cursor.close()

    def get_rental_statistics(self, user_id: int | None = None) -> dict:
        """
        Get rental statistics for the system.
        
        Returns:
            dict: Statistics including total accounts, active rentals, etc.
        """
        try:
            cursor = self._cursor()
            
            # Total accounts
            if user_id is None:
                cursor.execute("SELECT COUNT(*) FROM accounts")
            else:
                cursor.execute("SELECT COUNT(*) FROM accounts WHERE user_id = ?", (user_id,))
            total_accounts = cursor.fetchone()[0]
            
            # Active rentals
            if user_id is None:
                cursor.execute("SELECT COUNT(*) FROM accounts WHERE owner IS NOT NULL")
            else:
                cursor.execute("SELECT COUNT(*) FROM accounts WHERE owner IS NOT NULL AND user_id = ?", (user_id,))
            active_rentals = cursor.fetchone()[0]
            
            # Available accounts
            if user_id is None:
                cursor.execute("SELECT COUNT(*) FROM accounts WHERE owner IS NULL")
            else:
                cursor.execute("SELECT COUNT(*) FROM accounts WHERE owner IS NULL AND user_id = ?", (user_id,))
            available_accounts = cursor.fetchone()[0]
            
            # Total rental hours
            if user_id is None:
                cursor.execute(
                    "SELECT SUM(COALESCE(rental_duration_minutes, rental_duration * 60)) FROM accounts WHERE owner IS NOT NULL"
                )
            else:
                cursor.execute(
                    "SELECT SUM(COALESCE(rental_duration_minutes, rental_duration * 60)) FROM accounts WHERE owner IS NOT NULL AND user_id = ?",
                    (user_id,),
                )
            total_minutes = cursor.fetchone()[0] or 0
            total_hours = round(total_minutes / 60, 2)
            
            # Recent rentals (last 24 hours)
            since = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
            if user_id is None:
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM accounts 
                    WHERE owner IS NOT NULL 
                    AND rental_start >= ?
                    """,
                    (since,),
                )
            else:
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM accounts 
                    WHERE owner IS NOT NULL 
                    AND rental_start >= ?
                    AND user_id = ?
                    """,
                    (since, user_id),
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

    def add_memory_fact(
        self,
        owner_id: str,
        fact: str,
        user_id: int | None = None,
        max_facts: int = 20,
    ) -> bool:
        if not owner_id or not fact:
            return False
        try:
            cursor = self._cursor()
            cursor.execute(
                """
                INSERT INTO ai_memory_facts (owner, user_id, fact)
                VALUES (?, ?, ?)
                """,
                (str(owner_id), int(user_id or 0), str(fact)),
            )
            self.conn.commit()
            if max_facts and int(max_facts) > 0:
                cursor.execute(
                    """
                    DELETE FROM ai_memory_facts
                    WHERE owner = ? AND user_id = ?
                    AND id NOT IN (
                        SELECT id FROM (
                            SELECT id
                            FROM ai_memory_facts
                            WHERE owner = ? AND user_id = ?
                            ORDER BY id DESC
                            LIMIT ?
                        ) AS recent
                    )
                    """,
                    (
                        str(owner_id),
                        int(user_id or 0),
                        str(owner_id),
                        int(user_id or 0),
                        int(max_facts),
                    ),
                )
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error(f"Error adding memory fact: {exc}")
            return False
        finally:
            cursor.close()

    def get_memory_facts(
        self,
        owner_id: str,
        user_id: int | None = None,
        limit: int = 20,
    ) -> list:
        if not owner_id:
            return []
        try:
            limit_value = int(limit or 0)
        except Exception:
            limit_value = 20
        try:
            cursor = self._cursor()
            cursor.execute(
                """
                SELECT id, fact, created_at
                FROM ai_memory_facts
                WHERE owner = ? AND user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (str(owner_id), int(user_id or 0), int(limit_value)),
            )
            rows = cursor.fetchall()
            rows.reverse()
            return [
                {"id": row[0], "text": row[1], "created_at": row[2]} for row in rows
            ]
        except Exception as exc:
            logger.error(f"Error getting memory facts: {exc}")
            return []
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
    ) -> bool:
        if not order_id or not owner_id or not action:
            return False
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
            cursor = self._cursor()
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
            cursor.close()

    def get_order_history(
        self, owner_id: str, limit: int = 5, user_id: int | None = None
    ) -> list:
        if not owner_id:
            return []
        try:
            cursor = self._cursor()
            cursor.execute(
                """
                SELECT order_id, account_name, lot_number, amount, price, action, created_at
                FROM order_history
                WHERE owner = ? AND user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (str(owner_id), int(user_id or 0), int(limit)),
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

    def list_blacklist(self, user_id: int | None = None, query: str | None = None) -> list:
        try:
            cursor = self._cursor()
            owner_query = None
            if query:
                owner_query = f"%{str(query).strip().lower()}%"
            if owner_query:
                cursor.execute(
                    """
                    SELECT id, owner, reason, created_at
                    FROM blacklist
                    WHERE user_id = ? AND owner LIKE ?
                    ORDER BY created_at DESC
                    """,
                    (int(user_id or 0), owner_query),
                )
            else:
                cursor.execute(
                    """
                    SELECT id, owner, reason, created_at
                    FROM blacklist
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    """,
                    (int(user_id or 0),),
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

    def is_blacklisted(self, owner: str, user_id: int | None = None) -> bool:
        if not owner:
            return False
        owner_key = str(owner).strip().lower()
        try:
            cursor = self._cursor()
            cursor.execute(
                """
                SELECT 1 FROM blacklist WHERE owner = ? AND user_id = ? LIMIT 1
                """,
                (owner_key, int(user_id or 0)),
            )
            return cursor.fetchone() is not None
        except Exception as exc:
            logger.error(f"Error checking blacklist for {owner}: {exc}")
            return False
        finally:
            cursor.close()

    def add_blacklist_entry(self, owner: str, reason: str | None = None, user_id: int | None = None) -> bool:
        if not owner:
            return False
        owner_key = str(owner).strip().lower()
        reason_value = reason.strip() if isinstance(reason, str) and reason.strip() else None
        try:
            cursor = self._cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO blacklist (owner, reason, user_id)
                    VALUES (?, ?, ?)
                    """,
                    (owner_key, reason_value, int(user_id or 0)),
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

    def remove_blacklist_entries(self, owners: list[str], user_id: int | None = None) -> int:
        if not owners:
            return 0
        owner_keys = [str(owner).strip().lower() for owner in owners if str(owner).strip()]
        if not owner_keys:
            return 0
        placeholders = ", ".join(["?"] * len(owner_keys))
        try:
            cursor = self._cursor()
            cursor.execute(
                f"DELETE FROM blacklist WHERE user_id = ? AND owner IN ({placeholders})",
                (int(user_id or 0), *owner_keys),
            )
            self.conn.commit()
            return max(0, cursor.rowcount)
        except Exception as exc:
            logger.error(f"Error removing blacklist entries: {exc}")
            return 0
        finally:
            cursor.close()

    def clear_blacklist(self, user_id: int | None = None) -> int:
        try:
            cursor = self._cursor()
            cursor.execute(
                "DELETE FROM blacklist WHERE user_id = ?",
                (int(user_id or 0),),
            )
            self.conn.commit()
            return max(0, cursor.rowcount)
        except Exception as exc:
            logger.error(f"Error clearing blacklist: {exc}")
            return 0
        finally:
            cursor.close()

    def add_time_to_owner_accounts(
        self, owner: str, hours: int, minutes: int = 0, user_id: int | None = None
    ) -> bool:
        """
        Extract the rental_start timestamp, add the specified number of hours to it,
        and update the rental_start field for all accounts with the same owner.
        """
        try:
            cursor = self._cursor()
            # Retrieve the current rental_start timestamps for the owner
            if user_id in (None, 0):
                cursor.execute(
                    """
                    SELECT ID, rental_start
                    FROM accounts
                    WHERE owner = ? AND rental_start IS NOT NULL
                    """,
                    (owner,),
                )
            else:
                cursor.execute(
                    """
                    SELECT ID, rental_start
                    FROM accounts
                    WHERE owner = ? AND rental_start IS NOT NULL AND user_id = ?
                    """,
                    (owner, user_id),
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
                        """
                        UPDATE accounts
                        SET rental_start = ?
                        WHERE ID = ?
                        """,
                        (new_rental_start_str, account_id),
                    )

            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding hours for owner {owner}: {str(e)}")
            return False
        finally:
            cursor.close()

    def get_active_users(self, user_id: int | None = None, include_mafile: bool = True):
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
                        mafile_json
                    FROM accounts 
                    WHERE owner IS NOT NULL 
                    AND owner != 'OTHER_ACCOUNT'
                    AND rental_start IS NOT NULL
                    ORDER BY rental_start DESC
                    """
                )
            else:
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
                        mafile_json
                    FROM accounts 
                    WHERE owner IS NOT NULL 
                    AND owner != 'OTHER_ACCOUNT'
                    AND rental_start IS NOT NULL
                    AND user_id = ?
                    ORDER BY rental_start DESC
                    """,
                    (user_id,),
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
                }
                for row in rows
            ]
            return active_users
        except Exception as e:
            logger.error(f"Error retrieving active users: {str(e)}")
            return []
        finally:
            cursor.close()

    def upsert_feedback_reward(self, order_id: str, owner: str, rating: int, review_text: str | None) -> bool:
        try:
            cursor = self._cursor()
            if self.db_type == "mysql":
                cursor.execute(
                    """
                    INSERT INTO feedback_rewards (order_id, owner, rating, review_text)
                    VALUES (?, ?, ?, ?)
                    ON DUPLICATE KEY UPDATE
                        owner = VALUES(owner),
                        rating = VALUES(rating),
                        review_text = VALUES(review_text),
                        reviewed_at = CURRENT_TIMESTAMP
                    """,
                    (order_id, owner, int(rating), review_text),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO feedback_rewards (order_id, owner, rating, review_text, reviewed_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(order_id) DO UPDATE SET
                        owner = excluded.owner,
                        rating = excluded.rating,
                        review_text = excluded.review_text,
                        reviewed_at = excluded.reviewed_at
                    """,
                    (order_id, owner, int(rating), review_text),
                )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error upserting feedback reward: {str(e)}")
            return False
        finally:
            cursor.close()

    def get_unclaimed_feedback_reward(self, owner: str, min_rating: int = 5) -> dict | None:
        try:
            cursor = self._cursor()
            cursor.execute(
                """
                SELECT order_id, rating, review_text, reviewed_at
                FROM feedback_rewards
                WHERE owner = ? AND claimed_at IS NULL AND rating >= ?
                ORDER BY reviewed_at DESC
                LIMIT 1
                """,
                (owner, int(min_rating)),
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

    def mark_feedback_reward_claimed(self, order_id: str, account_id: int | None = None) -> bool:
        try:
            cursor = self._cursor()
            cursor.execute(
                """
                UPDATE feedback_rewards
                SET claimed_at = CURRENT_TIMESTAMP, account_id = ?
                WHERE order_id = ? AND claimed_at IS NULL
                """,
                (account_id, order_id),
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error marking feedback reward claimed: {str(e)}")
            return False
        finally:
            cursor.close()

    def get_feedback_reward(self, order_id: str) -> dict | None:
        try:
            cursor = self._cursor()
            cursor.execute(
                """
                SELECT order_id, owner, rating, review_text, reviewed_at, claimed_at, account_id, revoked_at
                FROM feedback_rewards
                WHERE order_id = ?
                """,
                (order_id,),
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
            }
        except Exception as e:
            logger.error(f"Error reading feedback reward: {str(e)}")
            return None
        finally:
            cursor.close()

    def mark_feedback_reward_revoked(self, order_id: str) -> bool:
        try:
            cursor = self._cursor()
            cursor.execute(
                """
                UPDATE feedback_rewards
                SET revoked_at = CURRENT_TIMESTAMP
                WHERE order_id = ? AND revoked_at IS NULL
                """,
                (order_id,),
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error marking feedback reward revoked: {str(e)}")
            return False
        finally:
            cursor.close()

    def get_user_accounts_by_name(self, owner_id: str, account_name: str) -> list:
        """
        Get active accounts of a specific user by account name.
        
        Args:
            owner_id (str): The owner ID
            account_name (str): The name of the account type
            
        Returns:
            list: List of active accounts with the specified name
        """
        try:
            cursor = self._cursor()
            cursor.execute(
                """
                SELECT ID, account_name, login, password, rental_duration, rental_duration_minutes, rental_start
                FROM accounts 
                WHERE owner = ? AND account_name = ?
                """,
                (owner_id, account_name),
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
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Error getting user accounts by name: {str(e)}")
            return []
        finally:
            cursor.close()

    def get_user_active_accounts(self, owner_id: str, user_id: int | None = None) -> list:
        """
        Get all active accounts of a specific user.
        
        Args:
            owner_id (str): The owner ID
            
        Returns:
            list: List of all active accounts for the user
        """
        try:
            cursor = self._cursor()
            if user_id in (None, 0):
                cursor.execute(
                    """
                    SELECT ID, account_name, login, password, rental_duration, rental_duration_minutes, rental_start
                    FROM accounts 
                    WHERE owner = ?
                    ORDER BY rental_start DESC
                    """,
                    (owner_id,),
                )
            else:
                cursor.execute(
                    """
                    SELECT ID, account_name, login, password, rental_duration, rental_duration_minutes, rental_start
                    FROM accounts 
                    WHERE owner = ? AND user_id = ?
                    ORDER BY rental_start DESC
                    """,
                    (owner_id, user_id),
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
            if pk_cols != ["lot_number", "user_id"]:
                cursor.execute("ALTER TABLE lots DROP PRIMARY KEY")
                cursor.execute("ALTER TABLE lots ADD PRIMARY KEY (lot_number, user_id)")

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
                cursor.execute("ALTER TABLE lots ADD UNIQUE KEY uniq_account_user (account_id, user_id)")
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

    def get_user_active_lot_accounts(self, owner_id: str) -> list:
        """
        Get all active accounts of a specific user with lot mapping info (if configured).
        """
        try:
            cursor = self._cursor()
            cursor.execute(
                """
                SELECT a.ID, a.account_name, a.login, a.password, a.rental_duration, a.rental_duration_minutes, a.rental_start, l.lot_number, l.lot_url
                FROM accounts a
                LEFT JOIN lots l ON l.account_id = a.ID
                WHERE a.owner = ?
                ORDER BY a.rental_start DESC
                """,
                (owner_id,),
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
                "SELECT id, username, golden_key FROM users WHERE golden_key IS NOT NULL AND golden_key <> ''"
            )
            return [
                {"id": row[0], "username": row[1], "golden_key": row[2]}
                for row in cursor.fetchall()
            ]
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
            cursor = self._cursor()
            if user_id in (None, 0):
                cursor.execute(
                    """
                    UPDATE accounts 
                    SET rental_duration_minutes = COALESCE(rental_duration_minutes, rental_duration * 60) + ?,
                        rental_duration = rental_duration + ?
                    WHERE ID = ? AND owner IS NOT NULL AND owner != 'OTHER_ACCOUNT'
                    """,
                    (total_minutes, additional_hours, account_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE accounts 
                    SET rental_duration_minutes = COALESCE(rental_duration_minutes, rental_duration * 60) + ?,
                        rental_duration = rental_duration + ?
                    WHERE ID = ? AND owner IS NOT NULL AND owner != 'OTHER_ACCOUNT' AND user_id = ?
                    """,
                    (total_minutes, additional_hours, account_id, user_id),
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
        self, account_id: int, owner_id: str, additional_hours: int, additional_minutes: int = 0
    ) -> bool:
        """
        Extend rental duration, but only if the account is currently owned by the given owner.
        """
        try:
            total_minutes = int(additional_hours) * 60 + int(additional_minutes)
            if total_minutes <= 0:
                return False
            cursor = self._cursor()
            cursor.execute(
                """
                UPDATE accounts
                SET rental_duration_minutes = COALESCE(rental_duration_minutes, rental_duration * 60) + ?,
                    rental_duration = rental_duration + ?
                WHERE ID = ? AND owner = ?
                """,
                (total_minutes, additional_hours, account_id, owner_id),
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
        self, account_id: int, owner_id: str, reduce_hours: int, reduce_minutes: int = 0
    ) -> bool:
        """
        Reduce rental duration, but only if the account is currently owned by the given owner.
        """
        try:
            total_minutes = int(reduce_hours) * 60 + int(reduce_minutes)
            if total_minutes <= 0:
                return False
            cursor = self._cursor()
            cursor.execute(
                """
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
                WHERE ID = ? AND owner = ?
                """,
                (total_minutes, total_minutes, reduce_hours, reduce_hours, account_id, owner_id),
            )
            success = cursor.rowcount > 0
            self.conn.commit()
            return success
        except Exception as e:
            logger.error(f"Error reducing rental duration for owner: {str(e)}")
            return False
        finally:
            cursor.close()
