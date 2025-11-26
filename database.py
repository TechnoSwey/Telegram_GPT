import sqlite3
import logging
import threading
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from config import config


class DatabaseError(Exception):


class DatabaseConnection:
    
    def __init__(self, db_config: DatabaseConfig):
        self.db_config = db_config
        self._local = threading.local()
    
    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'connection'):
            try:
                conn = sqlite3.connect(
                    self.db_config.name,
                    timeout=self.db_config.timeout,
                    check_same_thread=False
                )
                
                for pragma, value in self.db_config.pragmas.items():
                    conn.execute(f"PRAGMA {pragma} = {value}")
                
                conn.row_factory = sqlite3.Row
                self._local.connection = conn
                
            except sqlite3.Error as e:
                logging.error(f"Database connection failed: {e}")
                raise DatabaseError(f"Connection failed: {e}")
        
        return self._local.connection
    
    @contextmanager
    def get_cursor(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            yield cursor
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            logging.error(f"Database operation failed: {e}")
            raise DatabaseError(f"Operation failed: {e}")
        finally:
            cursor.close()
    
    def close(self):
        if hasattr(self._local, 'connection'):
            try:
                self._local.connection.close()
                delattr(self._local, 'connection')
            except sqlite3.Error as e:
                logging.error(f"Error closing connection: {e}")


class UserRepository:
    
    def __init__(self, db_connection: DatabaseConnection):
        self.db = db_connection
        self._init_schema()
    
    def _init_schema(self) -> None:
        with self.db.get_cursor() as cursor:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    tg_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    balance INTEGER DEFAULT 3,
                    total_requests INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tg_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    stars_paid INTEGER NOT NULL,
                    payment_id TEXT UNIQUE,
                    status TEXT DEFAULT 'completed',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (tg_id) REFERENCES users (tg_id)
                )
            ''')
    
    def get_user(self, tg_id: int) -> Optional[Dict[str, Any]]:
        with self.db.get_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM users WHERE tg_id = ?",
                (tg_id,)
            )
            result = cursor.fetchone()
            return dict(result) if result else None
    
    def create_user(self, tg_id: int, username: str = None, 
                   first_name: str = None, last_name: str = None) -> Dict[str, Any]:
        with self.db.get_cursor() as cursor:
            cursor.execute('''
                INSERT OR IGNORE INTO users 
                (tg_id, username, first_name, last_name, balance)
                VALUES (?, ?, ?, ?, ?)
            ''', (tg_id, username, first_name, last_name, config.bot.default_free_requests))
            
            cursor.execute(
                "SELECT * FROM users WHERE tg_id = ?",
                (tg_id,)
            )
            result = cursor.fetchone()
            
            if not result:
                raise DatabaseError("Failed to create user")
            
            return dict(result)
    
    def update_balance(self, tg_id: int, delta: int) -> bool:
        with self.db.get_cursor() as cursor:
            cursor.execute('''
                UPDATE users 
                SET balance = balance + ?, 
                    updated_at = CURRENT_TIMESTAMP,
                    total_requests = total_requests + ABS(?)
                WHERE tg_id = ? AND balance + ? >= 0
            ''', (delta, -delta if delta < 0 else 0, tg_id, delta))
            
            return cursor.rowcount > 0


class DatabaseManager:
    
    def __init__(self):
        self.connection = DatabaseConnection(config.database)
        self.users = UserRepository(self.connection)
    
    def get_or_create_user(self, tg_id: int, **user_data) -> Dict[str, Any]:
        user = self.users.get_user(tg_id)
        if user:
            return user
        
        return self.users.create_user(tg_id, **user_data)
    
    def ensure_sufficient_balance(self, tg_id: int, cost: int = 1) -> bool:
        return self.users.update_balance(tg_id, -cost)


db_manager = DatabaseManager()
