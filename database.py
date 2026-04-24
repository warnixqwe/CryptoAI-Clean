import sqlite3
import json
import time
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from contextlib import contextmanager

from config import get_config

cfg = get_config()
logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or cfg.DB_PATH
        self._init_tables()
        logger.info(f"Database initialized at {self.db_path}")
    
    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def _init_tables(self):
        with self._get_conn() as conn:
            c = conn.cursor()
            # Users
            c.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                language TEXT DEFAULT 'en',
                registered_at INTEGER,
                subscribed INTEGER DEFAULT 0,
                subscribe_until INTEGER,
                balance REAL DEFAULT 0.0,
                total_spent REAL DEFAULT 0.0,
                total_signals_requested INTEGER DEFAULT 0,
                banned INTEGER DEFAULT 0,
                referral_code TEXT UNIQUE
            )''')
            # Referrals
            c.execute('''CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER UNIQUE,
                level INTEGER,
                reward_amount REAL,
                created_at INTEGER
            )''')
            # Payments
            c.execute('''CREATE TABLE IF NOT EXISTS payments (
                payment_id TEXT PRIMARY KEY,
                user_id INTEGER,
                amount REAL,
                currency TEXT,
                status TEXT,
                created_at INTEGER,
                paid_at INTEGER
            )''')
            # User actions
            c.execute('''CREATE TABLE IF NOT EXISTS user_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT,
                details TEXT,
                timestamp INTEGER
            )''')
            # Admin logs
            c.execute('''CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT,
                target_user INTEGER,
                details TEXT,
                timestamp INTEGER
            )''')
            # Daily stats
            c.execute('''CREATE TABLE IF NOT EXISTS daily_stats (
                date TEXT PRIMARY KEY,
                new_users INTEGER,
                active_users INTEGER,
                subscriptions_sold INTEGER,
                revenue_usd REAL
            )''')
            # Signals cache
            c.execute('''CREATE TABLE IF NOT EXISTS signals_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                signal_type TEXT,
                confidence INTEGER,
                price REAL,
                generated_at INTEGER
            )''')
            # Indexes
            c.execute("CREATE INDEX IF NOT EXISTS idx_users_subscribed ON users(subscribed, subscribe_until)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id, status)")
    
    # ---- User CRUD ----
    def register_user(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None, language: str = "en"):
        with self._get_conn() as conn:
            c = conn.cursor()
            now = int(time.time())
            import random, string
            ref_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            c.execute('''INSERT OR IGNORE INTO users 
                (user_id, username, first_name, last_name, language, registered_at, referral_code)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (user_id, username, first_name, last_name, language, now, ref_code))
    
    def get_user(self, user_id: int) -> Optional[Dict]:
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = c.fetchone()
            return dict(row) if row else None
    
    def has_active_subscription(self, user_id: int) -> bool:
        with self._get_conn() as conn:
            c = conn.cursor()
            now = int(time.time())
            c.execute("SELECT subscribed, subscribe_until FROM users WHERE user_id = ?", (user_id,))
            row = c.fetchone()
            return row and row["subscribed"] == 1 and row["subscribe_until"] and row["subscribe_until"] > now
    
    def activate_subscription(self, user_id: int, days: int = None, amount: float = None, payment_id: str = None):
        if days is None: days = cfg.SUBSCRIPTION_DAYS
        if amount is None: amount = cfg.SUBSCRIPTION_PRICE_USD
        with self._get_conn() as conn:
            c = conn.cursor()
            now = int(time.time())
            expire = now + days * 86400
            c.execute("UPDATE users SET subscribed=1, subscribe_until=?, total_spent=total_spent+? WHERE user_id=?", (expire, amount, user_id))
            if payment_id:
                c.execute("UPDATE payments SET status='paid', paid_at=? WHERE payment_id=?", (now, payment_id))
            self.log_user_action(user_id, "subscribe", f"days={days}, amount={amount}")
    
    # ---- Referral ----
    def add_referral(self, referrer_id: int, referred_id: int):
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM referrals WHERE referred_id=?", (referred_id,))
            if c.fetchone(): return
            now = int(time.time())
            c.execute("INSERT INTO referrals (referrer_id, referred_id, level, reward_amount, created_at) VALUES (?,?,1,?,?)",
                      (referrer_id, referred_id, cfg.REFERRAL_BONUS_ON_SUBSCRIBE, now))
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (cfg.REFERRAL_BONUS_ON_SUBSCRIBE, referrer_id))
    
    def get_referral_stats(self, user_id: int) -> Dict:
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=? AND level=1", (user_id,))
            direct = c.fetchone()[0]
            c.execute("SELECT SUM(reward_amount) FROM referrals WHERE referrer_id=?", (user_id,))
            total = c.fetchone()[0] or 0.0
            return {"direct_count": direct, "total_earned": total}
    
    def get_balance(self, user_id: int) -> float:
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
            row = c.fetchone()
            return row["balance"] if row else 0.0
    
    def add_balance(self, user_id: int, amount: float, reason: str = ""):
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
            self.log_user_action(user_id, "balance_add", f"{amount} ({reason})")
    
    # ---- Payments ----
    def create_payment(self, user_id: int, amount: float, currency: str = "USDT") -> str:
        import uuid
        payment_id = str(uuid.uuid4())
        with self._get_conn() as conn:
            c = conn.cursor()
            now = int(time.time())
            c.execute("INSERT INTO payments (payment_id, user_id, amount, currency, status, created_at) VALUES (?,?,?,?,?,?)",
                      (payment_id, user_id, amount, currency, "pending", now))
        return payment_id
    
    def get_payment_status(self, payment_id: str) -> Optional[str]:
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT status FROM payments WHERE payment_id=?", (payment_id,))
            row = c.fetchone()
            return row["status"] if row else None
    
    # ---- Logging ----
    def log_user_action(self, user_id: int, action: str, details: str = ""):
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO user_actions (user_id, action, details, timestamp) VALUES (?,?,?,?)",
                      (user_id, action, details, int(time.time())))
    
    def log_admin_action(self, admin_id: int, action: str, target_user: int = None, details: str = ""):
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO admin_logs (admin_id, action, target_user, details, timestamp) VALUES (?,?,?,?,?)",
                      (admin_id, action, target_user, details, int(time.time())))
    
    # ---- Stats ----
    def get_user_count(self) -> int:
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM users")
            return c.fetchone()[0]
    
    def get_active_subscribers_count(self) -> int:
        with self._get_conn() as conn:
            c = conn.cursor()
            now = int(time.time())
            c.execute("SELECT COUNT(*) FROM users WHERE subscribed=1 AND subscribe_until>?", (now,))
            return c.fetchone()[0]
    
    def get_total_revenue(self) -> float:
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT SUM(amount) FROM payments WHERE status='paid'")
            row = c.fetchone()
            return row[0] or 0.0
    
    def cleanup_expired_subscriptions(self):
        with self._get_conn() as conn:
            c = conn.cursor()
            now = int(time.time())
            c.execute("UPDATE users SET subscribed=0 WHERE subscribed=1 AND subscribe_until<?", (now,))
            return c.rowcount

_db_instance = None

def get_db() -> Database:
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance