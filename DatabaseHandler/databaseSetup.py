import secrets
import bcrypt
from datetime import datetime, timedelta

from config import (
    DATABASE_ENGINE,
    MYSQLDATABASE,
    MYSQLHOST,
    MYSQLPASSWORD,
    MYSQLPORT,
    MYSQLUSER,
)
from logger import logger

import mysql.connector as mysql_connector


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


class SQLiteDB:
    def __init__(self, db_name=None):
        self.db_name = None
        self.db_type = "mysql"
        self.conn = _NoopConnection()
        self.create_table()

    def _format_sql(self, sql: str) -> str:
        if self.db_type == "mysql":
            return sql.replace("?", "%s")
        return sql

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
            return _CursorWrapper(conn.cursor(), self._format_sql, connection=conn)
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
            return conn, _CursorWrapper(conn.cursor(), self._format_sql, connection=conn)
        conn = sqlite3.connect(self.db_name, check_same_thread=False)
        return conn, conn.cursor()

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
        self.conn.commit()
        cursor.close()
        self._ensure_mafile_column()
        self._ensure_lot_url_column()
        self._ensure_users_table()
        self._ensure_user_owner_columns()
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

            cursor = self._cursor()
            cursor.execute(
                """
                INSERT INTO accounts (
                    account_name, path_to_maFile, mafile_json, login, password, rental_duration, owner, user_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (account_name, path_to_maFile, mafile_json, login, password, duration, owner, user_id),
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
            SELECT ID, account_name, path_to_maFile, login, password, rental_duration
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
                "password": row[4],
                "rental_duration": row[5],
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
            rental_start = (datetime.utcnow() + timedelta(hours=3, minutes=10)).strftime(
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
        return rows

    def update_password_by_owner(self, owner_name: str, new_password: str) -> bool:
        """
        Update the password for the most recent account owned by the specified owner.
        """
        try:
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
                (new_password, owner_name, owner_name),
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
        return owners_data

    def get_all_accounts(self, user_id: int | None = None):
        """Retrieve all accounts from the database."""
        cursor = self._cursor()
        if user_id is None:
            cursor.execute(
                """
                SELECT ID, account_name, path_to_maFile, login, password, rental_duration, owner, rental_start, user_id
                FROM accounts
                """
            )
        else:
            cursor.execute(
                """
                SELECT ID, account_name, path_to_maFile, login, password, rental_duration, owner, rental_start, user_id
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
                "password": row[4],
                "rental_duration": row[5],
                "owner": row[6],
                "rental_start": row[7],
                "user_id": row[8] if len(row) > 8 else None,
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

    def get_lot_mapping(self, lot_number: int):
        cursor = self._cursor()
        cursor.execute(
            """
            SELECT l.lot_number, l.account_id, l.lot_url, a.account_name
            FROM lots l
            JOIN accounts a ON a.ID = l.account_id
            WHERE l.lot_number = ?
            """,
            (lot_number,),
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
                SELECT a.ID, a.account_name, a.login, a.password, a.rental_duration, a.owner, a.rental_start, a.mafile_json
                FROM lots l
                JOIN accounts a ON a.ID = l.account_id
                WHERE l.lot_number = ?
                """,
                (lot_number,),
            )
        else:
            cursor.execute(
                """
                SELECT a.ID, a.account_name, a.login, a.password, a.rental_duration, a.owner, a.rental_start, a.mafile_json
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
            "password": row[3],
            "rental_duration": row[4],
            "owner": row[5],
            "rental_start": row[6],
            "mafile_json": row[7],
        }

    def get_available_lot_accounts(self, user_id: int | None = None) -> list:
        cursor = self._cursor()
        if user_id is None:
            cursor.execute(
                """
                SELECT a.ID, a.account_name, a.owner, a.rental_start, a.rental_duration, l.lot_number, l.lot_url
                FROM lots l
                JOIN accounts a ON a.ID = l.account_id
                WHERE a.owner IS NULL
                ORDER BY l.lot_number
                """
            )
        else:
            cursor.execute(
                """
                SELECT a.ID, a.account_name, a.owner, a.rental_start, a.rental_duration, l.lot_number, l.lot_url
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
                "lot_number": row[5],
                "lot_url": row[6],
            }
            for row in rows
        ]

    def get_all_lot_accounts(self) -> list:
        cursor = self._cursor()
        cursor.execute(
            """
            SELECT a.ID, a.account_name, a.owner, a.rental_start, a.rental_duration, l.lot_number, l.lot_url
            FROM lots l
            JOIN accounts a ON a.ID = l.account_id
            ORDER BY l.lot_number
            """
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
                "lot_number": row[5],
                "lot_url": row[6],
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
        }
        updates = {key: value for key, value in fields.items() if key in allowed_fields}
        if not updates:
            return False

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
                SELECT ID, account_name, path_to_maFile, login, password, rental_duration, owner, rental_start
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
                    "password": row[4],
                    "rental_duration": row[5],
                    "owner": row[6],
                    "rental_start": row[7]
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
                           rental_duration, owner, rental_start, mafile_json
                    FROM accounts 
                    WHERE ID = ?
                    """,
                    (account_id,),
                )
            else:
                cursor.execute(
                    """
                    SELECT ID, account_name, path_to_maFile, login, password, 
                           rental_duration, owner, rental_start, mafile_json
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
                    "password": row[4],
                    "rental_duration": row[5],
                    "owner": row[6],
                    "rental_start": row[7],
                    "mafile_json": row[8],
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
                cursor.execute("SELECT SUM(rental_duration) FROM accounts WHERE owner IS NOT NULL")
            else:
                cursor.execute(
                    "SELECT SUM(rental_duration) FROM accounts WHERE owner IS NOT NULL AND user_id = ?", (user_id,)
                )
            total_hours = cursor.fetchone()[0] or 0
            
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
                SELECT ID, account_name, login, rental_duration, rental_start
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
                    "rental_start": row[4],
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Error getting user rental history: {str(e)}")
            return []
        finally:
            cursor.close()

    def add_time_to_owner_accounts(self, owner: str, hours: int, user_id: int | None = None) -> bool:
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
                    if isinstance(rental_start, datetime):
                        new_rental_start = rental_start - timedelta(hours=hours)
                    else:
                        new_rental_start = datetime.strptime(
                            rental_start, "%Y-%m-%d %H:%M:%S"
                        ) - timedelta(hours=hours)
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

    def get_active_users(self, user_id: int | None = None):
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
                        path_to_maFile,
                        login
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
                        path_to_maFile,
                        login
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
                    "path_to_maFile": row[5],
                    "login": row[6],
                }
                for row in rows
            ]
            return active_users
        except Exception as e:
            logger.error(f"Error retrieving active users: {str(e)}")
            return []
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
                SELECT ID, account_name, login, password, rental_duration, rental_start
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
                    "password": row[3],
                    "rental_duration": row[4],
                    "rental_start": row[5],
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
                    SELECT ID, account_name, login, password, rental_duration, rental_start
                    FROM accounts 
                    WHERE owner = ?
                    ORDER BY rental_start DESC
                    """,
                    (owner_id,),
                )
            else:
                cursor.execute(
                    """
                    SELECT ID, account_name, login, password, rental_duration, rental_start
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
                    "password": row[3],
                    "rental_duration": row[4],
                    "rental_start": row[5],
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
            cursor = self._cursor()
            cursor.execute(
                """
                UPDATE accounts
                SET password = ?
                WHERE login = ?
                """,
                (new_password, login),
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
                SELECT a.ID, a.account_name, a.login, a.password, a.rental_duration, a.rental_start, l.lot_number, l.lot_url
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
                    "password": row[3],
                    "rental_duration": row[4],
                    "rental_start": row[5],
                    "lot_number": row[6],
                    "lot_url": row[7],
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

    def extend_rental_duration(self, account_id: int, additional_hours: int, user_id: int | None = None) -> bool:
        """
        Extend the rental duration for a specific account.
        
        Args:
            account_id (int): The ID of the account to extend
            additional_hours (int): Number of hours to add to the rental duration
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            cursor = self._cursor()
            if user_id in (None, 0):
                cursor.execute(
                    """
                    UPDATE accounts 
                    SET rental_duration = rental_duration + ?
                    WHERE ID = ? AND owner IS NOT NULL AND owner != 'OTHER_ACCOUNT'
                    """,
                    (additional_hours, account_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE accounts 
                    SET rental_duration = rental_duration + ?
                    WHERE ID = ? AND owner IS NOT NULL AND owner != 'OTHER_ACCOUNT' AND user_id = ?
                    """,
                    (additional_hours, account_id, user_id),
                )
            success = cursor.rowcount > 0
            self.conn.commit()
            return success
        except Exception as e:
            logger.error(f"Error extending rental duration: {str(e)}")
            return False
        finally:
            cursor.close()

    def extend_rental_duration_for_owner(self, account_id: int, owner_id: str, additional_hours: int) -> bool:
        """
        Extend rental duration, but only if the account is currently owned by the given owner.
        """
        try:
            cursor = self._cursor()
            cursor.execute(
                """
                UPDATE accounts
                SET rental_duration = rental_duration + ?
                WHERE ID = ? AND owner = ?
                """,
                (additional_hours, account_id, owner_id),
            )
            success = cursor.rowcount > 0
            self.conn.commit()
            return success
        except Exception as e:
            logger.error(f"Error extending rental duration for owner: {str(e)}")
            return False
        finally:
            cursor.close()
