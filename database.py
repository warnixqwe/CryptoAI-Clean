import sqlite3
import json
import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple, Union
from contextlib import asynccontextmanager
from threading import Lock

# Импорт конфигурации
from config import get_config

cfg = get_config()
logger = logging.getLogger(__name__)

# ===================================================================
# Database Manager Class (Async wrapper with sync fallback)
# ===================================================================

class Database:
    """Main database handler with connection pooling and async interface"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or cfg.DB_PATH
        self._local = None
        self._lock = Lock()
        self._init_tables()
        logger.info(f"Database initialized at {self.db_path}")
    
    # -----------------------------------------------------------------
    # Connection management
    # -----------------------------------------------------------------
    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-safe connection"""
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA cache_size = 10000")
        return conn
    
    @asynccontextmanager
    async def get_cursor(self):
        """Async context manager for database cursor"""
        def _sync_operation():
            conn = self._get_connection()
            try:
                yield conn.cursor()
                conn.commit()
            except Exception as e:
                conn.rollback()
                raise e
            finally:
                conn.close()
        
        # Run sync operations in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        gen = _sync_operation()
        try:
            cursor = await loop.run_in_executor(None, lambda: next(gen))
            yield cursor
        finally:
            await loop.run_in_executor(None, lambda: next(gen, None))
    
    # -----------------------------------------------------------------
    # Table initialization (migrations)
    # -----------------------------------------------------------------
    def _init_tables(self):
        """Create all tables if they don't exist (runs synchronously at startup)"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
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
            last_signal_time INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0,
            ban_reason TEXT,
            ban_until INTEGER,
            referral_code TEXT UNIQUE,
            custom_settings TEXT DEFAULT '{}'
        )''')
        
        # Referrals (multi-level)
        cursor.execute('''CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER UNIQUE,
            level INTEGER,
            reward_amount REAL,
            created_at INTEGER,
            is_paid INTEGER DEFAULT 0,
            FOREIGN KEY(referrer_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY(referred_id) REFERENCES users(user_id) ON DELETE CASCADE
        )''')
        
        # Payments
        cursor.execute('''CREATE TABLE IF NOT EXISTS payments (
            payment_id TEXT PRIMARY KEY,
            user_id INTEGER,
            amount REAL,
            currency TEXT DEFAULT 'USDT',
            status TEXT DEFAULT 'pending',
            created_at INTEGER,
            paid_at INTEGER,
            invoice_url TEXT,
            payment_method TEXT,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )''')
        
        # Signals cache
        cursor.execute('''CREATE TABLE IF NOT EXISTS signals_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            signal_type TEXT,
            signal_text TEXT,
            confidence INTEGER,
            price REAL,
            generated_at INTEGER,
            used_by_count INTEGER DEFAULT 0,
            UNIQUE(symbol, generated_at)
        )''')
        
        # News cache
        cursor.execute('''CREATE TABLE IF NOT EXISTS news_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            title TEXT,
            content TEXT,
            published_at INTEGER,
            parsed_at INTEGER,
            sentiment_score REAL,
            keywords TEXT
        )''')
        
        # User actions log
        cursor.execute('''CREATE TABLE IF NOT EXISTS user_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            details TEXT,
            timestamp INTEGER,
            ip TEXT,
            user_agent TEXT
        )''')
        
        # Admin logs
        cursor.execute('''CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            action TEXT,
            target_user INTEGER,
            details TEXT,
            timestamp INTEGER
        )''')
        
        # Rate limiting
        cursor.execute('''CREATE TABLE IF NOT EXISTS rate_limits (
            user_id INTEGER,
            command TEXT,
            last_call INTEGER,
            count INTEGER,
            PRIMARY KEY(user_id, command)
        )''')
        
        # API keys for users (if we allow custom API keys)
        cursor.execute('''CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            api_key TEXT UNIQUE,
            permissions TEXT,
            created_at INTEGER,
            expires_at INTEGER,
            last_used INTEGER,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )''')
        
        # Feedback / support tickets
        cursor.execute('''CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            subject TEXT,
            message TEXT,
            status TEXT DEFAULT 'open',
            created_at INTEGER,
            resolved_at INTEGER,
            admin_response TEXT,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )''')
        
        # Daily statistics
        cursor.execute('''CREATE TABLE IF NOT EXISTS daily_stats (
            date TEXT PRIMARY KEY,
            new_users INTEGER DEFAULT 0,
            active_users INTEGER DEFAULT 0,
            subscriptions_sold INTEGER DEFAULT 0,
            revenue_usd REAL DEFAULT 0.0,
            signals_generated INTEGER DEFAULT 0
        )''')
        
        # Create indexes for performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_subscribed ON users(subscribed, subscribe_until)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id, status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals_cache(symbol, generated_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_actions_user ON user_actions(user_id, timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rate_limit ON rate_limits(user_id, command)")
        
        # Migration for existing databases (add missing columns)
        self._run_migrations(cursor)
        
        conn.commit()
        conn.close()
        logger.info("Database tables and indexes created/verified")
    
    def _run_migrations(self, cursor):
        """Handle incremental schema updates"""
        # Check if referral_code column exists
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]
        if "referral_code" not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN referral_code TEXT UNIQUE")
            logger.info("Added referral_code column to users")
        if "ban_until" not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN ban_until INTEGER")
        if "custom_settings" not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN custom_settings TEXT DEFAULT '{}'")
    
    # -----------------------------------------------------------------
    # User CRUD operations
    # -----------------------------------------------------------------
    async def register_user(self, user_id: int, username: str = None, 
                           first_name: str = None, last_name: str = None,
                           language: str = "en") -> bool:
        """Register a new user or update existing"""
        async with self.get_cursor() as cursor:
            now = int(time.time())
            # Check if user exists
            cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
            exists = cursor.fetchone()
            if not exists:
                # Generate unique referral code
                import random, string
                ref_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                while True:
                    cursor.execute("SELECT user_id FROM users WHERE referral_code = ?", (ref_code,))
                    if not cursor.fetchone():
                        break
                    ref_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                
                cursor.execute('''
                    INSERT INTO users (user_id, username, first_name, last_name, language, registered_at, referral_code)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, username, first_name, last_name, language, now, ref_code))
                
                # Update daily stats
                date_str = datetime.now().strftime("%Y-%m-%d")
                cursor.execute('''
                    INSERT INTO daily_stats (date, new_users) VALUES (?, 1)
                    ON CONFLICT(date) DO UPDATE SET new_users = new_users + 1
                ''', (date_str,))
                
                logger.info(f"New user registered: {user_id} ({username})")
                return True
            else:
                # Update existing user info
                cursor.execute('''
                    UPDATE users SET username = ?, first_name = ?, last_name = ?, language = ?
                    WHERE user_id = ?
                ''', (username, first_name, last_name, language, user_id))
                return False
    
    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get full user data as dict"""
        async with self.get_cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    async def update_user_settings(self, user_id: int, settings: dict):
        """Update custom settings JSON"""
        async with self.get_cursor() as cursor:
            cursor.execute("UPDATE users SET custom_settings = ? WHERE user_id = ?", 
                          (json.dumps(settings), user_id))
    
    async def ban_user(self, user_id: int, reason: str, duration_hours: int = None):
        """Ban a user (optionally for a duration)"""
        async with self.get_cursor() as cursor:
            ban_until = int(time.time() + duration_hours * 3600) if duration_hours else None
            cursor.execute('''
                UPDATE users SET banned = 1, ban_reason = ?, ban_until = ?
                WHERE user_id = ?
            ''', (reason, ban_until, user_id))
            logger.warning(f"User {user_id} banned: {reason}, until {ban_until}")
    
    async def unban_user(self, user_id: int):
        """Remove ban from user"""
        async with self.get_cursor() as cursor:
            cursor.execute("UPDATE users SET banned = 0, ban_reason = NULL, ban_until = NULL WHERE user_id = ?", (user_id,))
            logger.info(f"User {user_id} unbanned")
    
    async def is_user_banned(self, user_id: int) -> bool:
        """Check if user is currently banned"""
        async with self.get_cursor() as cursor:
            cursor.execute("SELECT banned, ban_until FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                return False
            if row["banned"]:
                if row["ban_until"] and row["ban_until"] < int(time.time()):
                    # Ban expired
                    await self.unban_user(user_id)
                    return False
                return True
            return False
    
    # -----------------------------------------------------------------
    # Subscription methods
    # -----------------------------------------------------------------
    async def has_active_subscription(self, user_id: int) -> bool:
        """Check if user has valid subscription"""
        async with self.get_cursor() as cursor:
            now = int(time.time())
            cursor.execute("SELECT subscribed, subscribe_until FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row and row["subscribed"] == 1 and row["subscribe_until"] and row["subscribe_until"] > now:
                return True
            return False
    
    async def activate_subscription(self, user_id: int, days: int = None, 
                                   amount: float = None, payment_id: str = None):
        """Activate premium subscription for user"""
        if days is None:
            days = cfg.SUBSCRIPTION_DAYS
        if amount is None:
            amount = cfg.SUBSCRIPTION_PRICE_USD
        
        async with self.get_cursor() as cursor:
            now = int(time.time())
            expire = now + days * 86400
            cursor.execute('''
                UPDATE users SET subscribed = 1, subscribe_until = ?, total_spent = total_spent + ?
                WHERE user_id = ?
            ''', (expire, amount, user_id))
            
            # Log action
            await self.log_user_action(user_id, "subscribe", f"days={days}, amount={amount}, expire={expire}")
            
            # If payment_id provided, update payment status
            if payment_id:
                cursor.execute('''
                    UPDATE payments SET status = 'paid', paid_at = ? WHERE payment_id = ?
                ''', (now, payment_id))
            
            logger.info(f"Subscription activated for user {user_id} until {datetime.fromtimestamp(expire)}")
            return expire
    
    async def cancel_subscription(self, user_id: int):
        """Cancel auto-renew (just mark as not subscribed)"""
        async with self.get_cursor() as cursor:
            cursor.execute("UPDATE users SET subscribed = 0 WHERE user_id = ?", (user_id,))
            await self.log_user_action(user_id, "unsubscribe", "manual_cancel")
    
    async def get_subscription_expiry(self, user_id: int) -> Optional[int]:
        """Return timestamp of subscription expiry or None"""
        async with self.get_cursor() as cursor:
            cursor.execute("SELECT subscribe_until FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                return row["subscribe_until"]
            return None
    
    # -----------------------------------------------------------------
    # Referral system (multi-level)
    # -----------------------------------------------------------------
    async def add_referral(self, referrer_id: int, referred_id: int) -> bool:
        """Add referral relationship with multi-level rewards"""
        async with self.get_cursor() as cursor:
            # Check if already referred
            cursor.execute("SELECT id FROM referrals WHERE referred_id = ?", (referred_id,))
            if cursor.fetchone():
                return False
            
            now = int(time.time())
            current_level = 1
            current_referrer = referrer_id
            max_level = cfg.MAX_REFERRAL_LEVELS
            
            while current_referrer and current_level <= max_level:
                reward_percent = cfg.get_referral_reward_for_level(current_level)
                reward_amount = cfg.REFERRAL_BONUS_ON_SUBSCRIBE * (reward_percent / 100.0)
                
                cursor.execute('''
                    INSERT INTO referrals (referrer_id, referred_id, level, reward_amount, created_at, is_paid)
                    VALUES (?, ?, ?, ?, ?, 0)
                ''', (current_referrer, referred_id, current_level, reward_amount, now))
                
                # Add to balance (but hold until referred subscribes? Here we add immediately)
                cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (reward_amount, current_referrer))
                
                # Move up the chain
                cursor.execute("SELECT referrer_id FROM referrals WHERE referred_id = ?", (current_referrer,))
                parent = cursor.fetchone()
                current_referrer = parent["referrer_id"] if parent else None
                current_level += 1
            
            # Generate referral code for the new user if missing
            cursor.execute("SELECT referral_code FROM users WHERE user_id = ?", (referred_id,))
            row = cursor.fetchone()
            if row and not row["referral_code"]:
                import random, string
                ref_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                cursor.execute("UPDATE users SET referral_code = ? WHERE user_id = ?", (ref_code, referred_id))
            
            logger.info(f"Referral chain added: {referrer_id} -> {referred_id}")
            return True
    
    async def get_referral_stats(self, user_id: int) -> Dict[str, Any]:
        """Get referral statistics for user"""
        async with self.get_cursor() as cursor:
            # Count direct referrals (level 1)
            cursor.execute("SELECT COUNT(*) as count FROM referrals WHERE referrer_id = ? AND level = 1", (user_id,))
            direct = cursor.fetchone()["count"]
            
            # Total earnings from referrals
            cursor.execute("SELECT SUM(reward_amount) as total FROM referrals WHERE referrer_id = ?", (user_id,))
            total_earned = cursor.fetchone()["total"] or 0.0
            
            # Count by level
            level_counts = {}
            for lvl in range(1, cfg.MAX_REFERRAL_LEVELS + 1):
                cursor.execute("SELECT COUNT(*) as cnt FROM referrals WHERE referrer_id = ? AND level = ?", (user_id, lvl))
                level_counts[lvl] = cursor.fetchone()["cnt"]
            
            # Top referrers (if admin)
            return {
                "direct_count": direct,
                "total_earned": total_earned,
                "level_counts": level_counts
            }
    
    async def get_referral_link(self, user_id: int) -> Optional[str]:
        """Get or create referral link for user"""
        async with self.get_cursor() as cursor:
            cursor.execute("SELECT referral_code FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row and row["referral_code"]:
                return f"https://t.me/{cfg.BOT_USERNAME}?start=ref_{row['referral_code']}"
            return None
    
    async def get_by_referral_code(self, code: str) -> Optional[int]:
        """Find user_id by referral code"""
        async with self.get_cursor() as cursor:
            cursor.execute("SELECT user_id FROM users WHERE referral_code = ?", (code,))
            row = cursor.fetchone()
            return row["user_id"] if row else None
    
    # -----------------------------------------------------------------
    # Balance & Transactions
    # -----------------------------------------------------------------
    async def get_balance(self, user_id: int) -> float:
        """Get user's bonus balance"""
        async with self.get_cursor() as cursor:
            cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return row["balance"] if row else 0.0
    
    async def add_balance(self, user_id: int, amount: float, reason: str = ""):
        """Add to user balance"""
        async with self.get_cursor() as cursor:
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
            await self.log_user_action(user_id, "balance_add", f"amount={amount}, reason={reason}")
            logger.debug(f"Added {amount} to user {user_id} balance")
    
    async def deduct_balance(self, user_id: int, amount: float, reason: str = ""):
        """Deduct from user balance if sufficient"""
        async with self.get_cursor() as cursor:
            cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row and row["balance"] >= amount:
                cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
                await self.log_user_action(user_id, "balance_deduct", f"amount={amount}, reason={reason}")
                return True
            return False
    
    # -----------------------------------------------------------------
    # Payments
    # -----------------------------------------------------------------
    async def create_payment(self, user_id: int, amount: float, currency: str = "USDT") -> str:
        """Create a new payment record, return payment_id"""
        import uuid
        payment_id = str(uuid.uuid4())
        async with self.get_cursor() as cursor:
            now = int(time.time())
            cursor.execute('''
                INSERT INTO payments (payment_id, user_id, amount, currency, status, created_at)
                VALUES (?, ?, ?, ?, 'pending', ?)
            ''', (payment_id, user_id, amount, currency, now))
            return payment_id
    
    async def get_payment_status(self, payment_id: str) -> Optional[str]:
        """Get payment status"""
        async with self.get_cursor() as cursor:
            cursor.execute("SELECT status FROM payments WHERE payment_id = ?", (payment_id,))
            row = cursor.fetchone()
            return row["status"] if row else None
    
    async def update_payment_status(self, payment_id: str, status: str):
        """Update payment status"""
        async with self.get_cursor() as cursor:
            now = int(time.time())
            cursor.execute('''
                UPDATE payments SET status = ?, paid_at = ? WHERE payment_id = ?
            ''', (status, now if status == "paid" else None, payment_id))
    
    # -----------------------------------------------------------------
    # Signals cache
    # -----------------------------------------------------------------
    async def cache_signal(self, symbol: str, signal_type: str, signal_text: str, 
                          confidence: int, price: float) -> int:
        """Store generated signal in cache"""
        async with self.get_cursor() as cursor:
            now = int(time.time())
            cursor.execute('''
                INSERT OR REPLACE INTO signals_cache (symbol, signal_type, signal_text, confidence, price, generated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (symbol, signal_type, signal_text, confidence, price, now))
            return cursor.lastrowid
    
    async def get_cached_signals(self, symbol: str, limit: int = 10) -> List[Dict]:
        """Get recent signals for a symbol"""
        async with self.get_cursor() as cursor:
            cursor.execute('''
                SELECT * FROM signals_cache WHERE symbol = ? ORDER BY generated_at DESC LIMIT ?
            ''', (symbol, limit))
            return [dict(row) for row in cursor.fetchall()]
    
    # -----------------------------------------------------------------
    # Logging
    # -----------------------------------------------------------------
    async def log_user_action(self, user_id: int, action: str, details: str = "", 
                              ip: str = None, user_agent: str = None):
        """Log user action for analytics"""
        async with self.get_cursor() as cursor:
            now = int(time.time())
            cursor.execute('''
                INSERT INTO user_actions (user_id, action, details, timestamp, ip, user_agent)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, action, details, now, ip, user_agent))
    
    async def log_admin_action(self, admin_id: int, action: str, target_user: int = None, details: str = ""):
        """Log admin action"""
        async with self.get_cursor() as cursor:
            now = int(time.time())
            cursor.execute('''
                INSERT INTO admin_logs (admin_id, action, target_user, details, timestamp)
                VALUES (?, ?, ?, ?, ?)
            ''', (admin_id, action, target_user, details, now))
    
    # -----------------------------------------------------------------
    # Rate limiting
    # -----------------------------------------------------------------
    async def check_rate_limit(self, user_id: int, command: str, 
                              limit_seconds: int = None, max_attempts: int = 3) -> Tuple[bool, int]:
        """
        Check if user is rate limited.
        Returns (allowed, retry_after_seconds)
        """
        if limit_seconds is None:
            # Use different limits for premium users
            if await self.has_active_subscription(user_id):
                limit_seconds = cfg.SIGNAL_RATE_LIMIT_SECONDS_PREMIUM
            else:
                limit_seconds = cfg.SIGNAL_RATE_LIMIT_SECONDS_FREE
        
        async with self.get_cursor() as cursor:
            now = int(time.time())
            cursor.execute("SELECT last_call, count FROM rate_limits WHERE user_id = ? AND command = ?", 
                          (user_id, command))
            row = cursor.fetchone()
            
            if not row:
                cursor.execute('''
                    INSERT INTO rate_limits (user_id, command, last_call, count)
                    VALUES (?, ?, ?, 1)
                ''', (user_id, command, now))
                return True, 0
            
            last_call = row["last_call"]
            count = row["count"]
            elapsed = now - last_call
            
            if elapsed > limit_seconds:
                # Reset
                cursor.execute('''
                    UPDATE rate_limits SET last_call = ?, count = 1 WHERE user_id = ? AND command = ?
                ''', (now, user_id, command))
                return True, 0
            else:
                if count >= max_attempts:
                    retry_after = limit_seconds - elapsed
                    return False, retry_after
                else:
                    cursor.execute('''
                        UPDATE rate_limits SET count = count + 1 WHERE user_id = ? AND command = ?
                    ''', (user_id, command))
                    return True, 0
    
    # -----------------------------------------------------------------
    # Statistics & Analytics
    # -----------------------------------------------------------------
    async def get_user_count(self) -> int:
        """Get total registered users"""
        async with self.get_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as cnt FROM users")
            return cursor.fetchone()["cnt"]
    
    async def get_active_subscribers_count(self) -> int:
        """Get users with active subscription"""
        async with self.get_cursor() as cursor:
            now = int(time.time())
            cursor.execute("SELECT COUNT(*) as cnt FROM users WHERE subscribed = 1 AND subscribe_until > ?", (now,))
            return cursor.fetchone()["cnt"]
    
    async def get_total_revenue(self) -> float:
        """Get total revenue from all payments"""
        async with self.get_cursor() as cursor:
            cursor.execute("SELECT SUM(amount) as total FROM payments WHERE status = 'paid'")
            row = cursor.fetchone()
            return row["total"] if row and row["total"] else 0.0
    
    async def get_daily_stats(self, days: int = 7) -> List[Dict]:
        """Get daily statistics for last N days"""
        async with self.get_cursor() as cursor:
            date_limit = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            cursor.execute('''
                SELECT * FROM daily_stats WHERE date >= ? ORDER BY date DESC
            ''', (date_limit,))
            return [dict(row) for row in cursor.fetchall()]
    
    # -----------------------------------------------------------------
    # Cleanup & Maintenance
    # -----------------------------------------------------------------
    async def cleanup_expired_subscriptions(self):
        """Automatically mark expired subscriptions as inactive"""
        async with self.get_cursor() as cursor:
            now = int(time.time())
            cursor.execute('''
                UPDATE users SET subscribed = 0 WHERE subscribed = 1 AND subscribe_until < ?
            ''', (now,))
            count = cursor.rowcount
            if count:
                logger.info(f"Cleaned up {count} expired subscriptions")
    
    async def cleanup_old_logs(self, days: int = 30):
        """Remove old action logs"""
        async with self.get_cursor() as cursor:
            cutoff = int(time.time()) - days * 86400
            cursor.execute("DELETE FROM user_actions WHERE timestamp < ?", (cutoff,))
            cursor.execute("DELETE FROM admin_logs WHERE timestamp < ?", (cutoff,))
            logger.info(f"Cleaned up logs older than {days} days")
    
    async def vacuum(self):
        """Optimize database (VACUUM)"""
        async with self.get_cursor() as cursor:
            cursor.execute("VACUUM")
            logger.info("Database VACUUM completed")
    
    # -----------------------------------------------------------------
    # Support tickets
    # -----------------------------------------------------------------
    async def create_ticket(self, user_id: int, subject: str, message: str) -> int:
        """Create a new support ticket"""
        async with self.get_cursor() as cursor:
            now = int(time.time())
            cursor.execute('''
                INSERT INTO support_tickets (user_id, subject, message, status, created_at)
                VALUES (?, ?, ?, 'open', ?)
            ''', (user_id, subject, message, now))
            return cursor.lastrowid
    
    async def get_open_tickets(self) -> List[Dict]:
        """Get all open tickets"""
        async with self.get_cursor() as cursor:
            cursor.execute("SELECT * FROM support_tickets WHERE status = 'open' ORDER BY created_at ASC")
            return [dict(row) for row in cursor.fetchall()]
    
    async def respond_ticket(self, ticket_id: int, admin_response: str, admin_id: int):
        """Respond to a ticket and close it"""
        async with self.get_cursor() as cursor:
            now = int(time.time())
            cursor.execute('''
                UPDATE support_tickets SET status = 'closed', resolved_at = ?, admin_response = ?
                WHERE id = ?
            ''', (now, admin_response, ticket_id))
            await self.log_admin_action(admin_id, "close_ticket", None, f"ticket_id={ticket_id}")

# ===================================================================
# Singleton instance
# ===================================================================

_db_instance: Optional[Database] = None

def get_db() -> Database:
    """Get global database instance"""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance

# ===================================================================
# Test/demo
# ===================================================================
if __name__ == "__main__":
    import asyncio
    async def test():
        db = get_db()
        await db.register_user(123456, "testuser", "Test", "User")
        user = await db.get_user(123456)
        print("User:", user)
        print("Has subscription:", await db.has_active_subscription(123456))
        await db.activate_subscription(123456, days=30, amount=20)
        print("After subscribe:", await db.has_active_subscription(123456))
    
    asyncio.run(test())