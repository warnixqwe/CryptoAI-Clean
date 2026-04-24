#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔═════════════════════════════════════════════════════════════════════════════╗
║                         SynthraCrypto ULTIMATE                              ║
║                      Самый мощный телеграм-бот для криптосигналов           ║
║                      Версия 2.0.0 | Mini App + Fixed DB                     ║
╚═════════════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import logging
import logging.handlers
import sqlite3
import json
import time
import re
import random
import string
import hashlib
import os
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

# Telegram
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Web server for Mini App
from aiohttp import web

# Дополнительные библиотеки
import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import ccxt
from dotenv import load_dotenv

# Voice
try:
    from gtts import gTTS
    import io
    VOICE_ENABLED = True
except ImportError:
    VOICE_ENABLED = False

load_dotenv()

# ===================================================================
# КОНФИГУРАЦИЯ
# ===================================================================
class Config:
    API_TOKEN = os.getenv("API_TOKEN", "")
    BOT_USERNAME = os.getenv("BOT_USERNAME", "SynthraCryptoBot")
    ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
    ALLOWED_UPDATES = ["message", "callback_query"]
    
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    CRYPTOBOT_TOKEN = os.getenv("CRYPTOBOT_TOKEN", "")
    
    DB_PATH = os.getenv("DB_PATH", "crypto_pulse.db")
    
    SUPPORTED_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"]
    EXCHANGES = ["binance", "bybit", "okx"]
    PRIMARY_EXCHANGE = os.getenv("PRIMARY_EXCHANGE", "okx")
    
    SUBSCRIPTION_PRICE_USD = 20.0
    SUBSCRIPTION_DAYS = 30
    FREE_SIGNALS_PER_DAY = 1
    
    MAX_REFERRAL_LEVELS = 5
    REFERRAL_REWARDS = [50.0, 15.0, 7.0, 3.0, 1.0]
    REFERRAL_BONUS_ON_SUBSCRIBE = 5.0
    
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("LOG_FILE", "logs/bot.log")
    
    USE_WEBHOOK = False
    WEBHOOK_PORT = int(os.getenv("PORT", 8080))
    
    DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
    
    @classmethod
    def validate(cls):
        if not cls.API_TOKEN:
            print("FATAL: API_TOKEN not set")
            sys.exit(1)
        print(f"✅ Config loaded. Bot: {cls.BOT_USERNAME}, Admins: {cls.ADMIN_IDS}")
        if cls.DEBUG_MODE:
            print("⚠️ DEBUG_MODE enabled")
    
    @classmethod
    def is_admin(cls, user_id: int) -> bool:
        return user_id in cls.ADMIN_IDS

# ===================================================================
# ЛОГГЕР
# ===================================================================
def setup_logging():
    os.makedirs(os.path.dirname(Config.LOG_FILE) or ".", exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, Config.LOG_LEVEL),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.handlers.RotatingFileHandler(Config.LOG_FILE, maxBytes=10_485_760, backupCount=5)
        ]
    )
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    return logging.getLogger(__name__)

logger = setup_logging()

# ===================================================================
# ДЕКОРАТОР ДЛЯ RETRY ПРИ DATABASE LOCKED
# ===================================================================
def retry_on_lock(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        for attempt in range(5):
            try:
                return func(self, *args, **kwargs)
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < 4:
                    time.sleep(0.5 * (attempt + 1))
                else:
                    raise
        return None
    return wrapper

# ===================================================================
# БАЗА ДАННЫХ (расширенная, с retry)
# ===================================================================
class Database:
    def __init__(self):
        self.db_path = Config.DB_PATH
        self._init_tables()
    
    @contextmanager
    def _cursor(self):
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.row_factory = sqlite3.Row
        try:
            yield conn.cursor()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def _init_tables(self):
        with self._cursor() as c:
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
                balance REAL DEFAULT 0,
                total_spent REAL DEFAULT 0,
                total_signals INTEGER DEFAULT 0,
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
            # Actions log
            c.execute('''CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT,
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
            # Signals history
            c.execute('''CREATE TABLE IF NOT EXISTS signals_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                symbol TEXT,
                action TEXT,
                confidence INTEGER,
                price REAL,
                tp1 REAL, tp2 REAL, sl REAL,
                created_at INTEGER
            )''')
            # Trader stats (leaderboard)
            c.execute('''CREATE TABLE IF NOT EXISTS trader_stats (
                user_id INTEGER PRIMARY KEY,
                total_pnl REAL DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                win_rate REAL DEFAULT 0,
                last_updated INTEGER
            )''')
            # Exchange referrals
            c.execute('''CREATE TABLE IF NOT EXISTS exchange_refs (
                user_id INTEGER,
                exchange TEXT,
                clicks INTEGER DEFAULT 0,
                registrations INTEGER DEFAULT 0,
                commission REAL DEFAULT 0,
                PRIMARY KEY (user_id, exchange)
            )''')
            # Notification settings
            c.execute('''CREATE TABLE IF NOT EXISTS user_notif_settings (
                user_id INTEGER PRIMARY KEY,
                price_alert_enabled INTEGER DEFAULT 0,
                price_threshold REAL DEFAULT 5.0,
                signal_enabled INTEGER DEFAULT 1,
                news_enabled INTEGER DEFAULT 0,
                coins TEXT DEFAULT 'BTC,ETH'
            )''')
            # Price cache for alerts
            c.execute('''CREATE TABLE IF NOT EXISTS price_cache (
                symbol TEXT PRIMARY KEY,
                last_price REAL,
                last_updated INTEGER
            )''')
            # Indexes
            c.execute("CREATE INDEX IF NOT EXISTS idx_actions_user ON actions(user_id, timestamp)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_signals_user ON signals_history(user_id, created_at)")
    
    @retry_on_lock
    def register_user(self, user_id: int, username: str = None, first_name: str = None):
        with self._cursor() as c:
            now = int(time.time())
            c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
            if c.fetchone():
                return
            ref_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            c.execute("INSERT INTO users (user_id, username, first_name, registered_at, referral_code) VALUES (?,?,?,?,?)",
                      (user_id, username, first_name, now, ref_code))
            self._update_daily_stats(now, "new_users", 1)
            logger.info(f"New user: {user_id} ({username})")
    
    def get_user(self, user_id: int) -> Optional[Dict]:
        with self._cursor() as c:
            c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
            row = c.fetchone()
            return dict(row) if row else None
    
    def has_subscription(self, user_id: int) -> bool:
        with self._cursor() as c:
            now = int(time.time())
            c.execute("SELECT subscribed, subscribe_until FROM users WHERE user_id=?", (user_id,))
            row = c.fetchone()
            return row and row["subscribed"] == 1 and row["subscribe_until"] > now
    
    @retry_on_lock
    def activate_subscription(self, user_id: int, days: int = None, amount: float = None, payment_id: str = None):
        days = days or Config.SUBSCRIPTION_DAYS
        amount = amount or Config.SUBSCRIPTION_PRICE_USD
        with self._cursor() as c:
            now = int(time.time())
            expire = now + days * 86400
            c.execute("UPDATE users SET subscribed=1, subscribe_until=?, total_spent=total_spent+? WHERE user_id=?", (expire, amount, user_id))
            if payment_id:
                c.execute("UPDATE payments SET status='paid', paid_at=? WHERE payment_id=?", (now, payment_id))
            self.log_action(user_id, "subscribe", f"{days}d ${amount}")
    
    @retry_on_lock
    def add_referral(self, referrer_id: int, referred_id: int):
        with self._cursor() as c:
            c.execute("SELECT id FROM referrals WHERE referred_id=?", (referred_id,))
            if c.fetchone():
                return
            now = int(time.time())
            reward = Config.REFERRAL_BONUS_ON_SUBSCRIBE
            c.execute("INSERT INTO referrals (referrer_id, referred_id, level, reward_amount, created_at) VALUES (?,?,1,?,?)",
                      (referrer_id, referred_id, reward, now))
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (reward, referrer_id))
    
    def get_referral_stats(self, user_id: int) -> Dict:
        with self._cursor() as c:
            c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (user_id,))
            direct = c.fetchone()[0]
            c.execute("SELECT SUM(reward_amount) FROM referrals WHERE referrer_id=?", (user_id,))
            earned = c.fetchone()[0] or 0.0
            c.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
            bal = c.fetchone()[0] or 0.0
            return {"direct": direct, "earned": earned, "balance": bal}
    
    def get_referral_link(self, user_id: int) -> str:
        with self._cursor() as c:
            c.execute("SELECT referral_code FROM users WHERE user_id=?", (user_id,))
            row = c.fetchone()
            code = row["referral_code"] if row else "unknown"
            return f"https://t.me/{Config.BOT_USERNAME}?start=ref_{code}"
    
    def get_by_referral_code(self, code: str) -> Optional[int]:
        with self._cursor() as c:
            c.execute("SELECT user_id FROM users WHERE referral_code=?", (code,))
            row = c.fetchone()
            return row["user_id"] if row else None
    
    @retry_on_lock
    def add_balance(self, user_id: int, amount: float, reason: str = ""):
        with self._cursor() as c:
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
            self.log_action(user_id, "balance_add", reason)
    
    @retry_on_lock
    def deduct_balance(self, user_id: int, amount: float, reason: str = "") -> bool:
        bal = self.get_balance(user_id)
        if bal < amount:
            return False
        with self._cursor() as c:
            c.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, user_id))
            self.log_action(user_id, "balance_deduct", reason)
            return True
    
    def get_balance(self, user_id: int) -> float:
        with self._cursor() as c:
            c.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
            row = c.fetchone()
            return row["balance"] if row else 0.0
    
    @retry_on_lock
    def log_action(self, user_id: int, action: str, details: str = ""):
        with self._cursor() as c:
            c.execute("INSERT INTO actions (user_id, action, details, timestamp) VALUES (?,?,?,?)",
                      (user_id, action, details, int(time.time())))
    
    def get_signal_usage_today(self, user_id: int) -> int:
        with self._cursor() as c:
            day_start = int(datetime.now().replace(hour=0, minute=0, second=0).timestamp())
            c.execute("SELECT COUNT(*) FROM actions WHERE user_id=? AND action IN ('free_signal','premium_signal') AND timestamp>=?",
                      (user_id, day_start))
            return c.fetchone()[0]
    
    @retry_on_lock
    def update_trader_stats(self, user_id: int, pnl_change: float, is_win: bool = None):
        with self._cursor() as c:
            now = int(time.time())
            c.execute("SELECT total_pnl, wins, losses FROM trader_stats WHERE user_id=?", (user_id,))
            row = c.fetchone()
            if row:
                new_pnl = row["total_pnl"] + pnl_change
                new_wins = row["wins"] + (1 if is_win else 0)
                new_losses = row["losses"] + (0 if is_win else 1) if is_win is not None else row["losses"]
                win_rate = (new_wins / (new_wins + new_losses) * 100) if (new_wins + new_losses) > 0 else 0
                c.execute("UPDATE trader_stats SET total_pnl=?, wins=?, losses=?, win_rate=?, last_updated=? WHERE user_id=?",
                          (new_pnl, new_wins, new_losses, win_rate, now, user_id))
            else:
                c.execute("INSERT INTO trader_stats (user_id, total_pnl, wins, losses, win_rate, last_updated) VALUES (?,?,?,?,?,?)",
                          (user_id, pnl_change, 1 if is_win else 0, 0 if is_win else 1,
                           100 if is_win else 0, now))
    
    def get_leaderboard(self, limit=10) -> List[Dict]:
        with self._cursor() as c:
            c.execute("SELECT user_id, total_pnl, wins, losses, win_rate FROM trader_stats ORDER BY total_pnl DESC LIMIT ?", (limit,))
            return [dict(row) for row in c.fetchall()]
    
    @retry_on_lock
    def record_exchange_click(self, user_id: int, exchange: str):
        with self._cursor() as c:
            c.execute("INSERT INTO exchange_refs (user_id, exchange, clicks) VALUES (?,?,1) ON CONFLICT(user_id,exchange) DO UPDATE SET clicks = clicks + 1",
                      (user_id, exchange))
    
    def get_notif_settings(self, user_id: int) -> Dict:
        with self._cursor() as c:
            c.execute("SELECT * FROM user_notif_settings WHERE user_id=?", (user_id,))
            row = c.fetchone()
            if row:
                return dict(row)
            return {"user_id": user_id, "price_alert_enabled": 0, "price_threshold": 5.0,
                    "signal_enabled": 1, "news_enabled": 0, "coins": "BTC,ETH"}
    
    @retry_on_lock
    def update_notif_settings(self, user_id: int, **kwargs):
        with self._cursor() as c:
            c.execute("INSERT OR IGNORE INTO user_notif_settings (user_id) VALUES (?)", (user_id,))
            set_clause = ", ".join([f"{k}=?" for k in kwargs.keys()])
            c.execute(f"UPDATE user_notif_settings SET {set_clause} WHERE user_id=?", tuple(kwargs.values()) + (user_id,))
    
    @retry_on_lock
    def update_price_cache(self, symbol: str, price: float):
        with self._cursor() as c:
            c.execute("INSERT OR REPLACE INTO price_cache (symbol, last_price, last_updated) VALUES (?,?,?)",
                      (symbol, price, int(time.time())))
    
    def get_price_cache(self, symbol: str) -> Optional[Dict]:
        with self._cursor() as c:
            c.execute("SELECT * FROM price_cache WHERE symbol=?", (symbol,))
            row = c.fetchone()
            return dict(row) if row else None
    
    @retry_on_lock
    def save_signal_history(self, user_id: int, symbol: str, action: str, confidence: int, price: float, tp_sl: Dict):
        with self._cursor() as c:
            c.execute('''INSERT INTO signals_history 
                (user_id, symbol, action, confidence, price, tp1, tp2, sl, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)''',
                      (user_id, symbol, action, confidence, price,
                       tp_sl.get("take_profit_1"), tp_sl.get("take_profit_2"), tp_sl.get("stop_loss"),
                       int(time.time())))
    
    def get_user_signal_history(self, user_id: int, limit=10) -> List[Dict]:
        with self._cursor() as c:
            c.execute("SELECT * FROM signals_history WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id, limit))
            return [dict(row) for row in c.fetchall()]
    
    def get_stats(self) -> Dict:
        with self._cursor() as c:
            c.execute("SELECT COUNT(*) FROM users")
            total_users = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM users WHERE subscribed=1 AND subscribe_until>?", (int(time.time()),))
            active_premium = c.fetchone()[0]
            c.execute("SELECT SUM(amount) FROM payments WHERE status='paid'")
            revenue = c.fetchone()[0] or 0.0
            today = datetime.now().strftime("%Y-%m-%d")
            c.execute("SELECT new_users, active_users FROM daily_stats WHERE date=?", (today,))
            row = c.fetchone()
            return {"total_users": total_users, "active_premium": active_premium, "revenue": revenue,
                    "today_new": row["new_users"] if row else 0, "today_active": row["active_users"] if row else 0}
    
    def get_analytics_signals(self) -> Dict:
        with self._cursor() as c:
            c.execute("SELECT AVG(confidence) FROM signals_history")
            avg_conf = c.fetchone()[0] or 0
            c.execute("SELECT action, COUNT(*) FROM signals_history GROUP BY action")
            counts = {row["action"]: row[1] for row in c.fetchall()}
            week_ago = int(time.time()) - 7*86400
            c.execute("SELECT DATE(created_at, 'unixepoch') as day, COUNT(*) FROM signals_history WHERE created_at>? GROUP BY day ORDER BY day", (week_ago,))
            daily = [{"day": row[0], "count": row[1]} for row in c.fetchall()]
            return {"avg_confidence": avg_conf, "action_counts": counts, "daily": daily}
    
    @retry_on_lock
    def _update_daily_stats(self, timestamp: int, column: str, delta: int = 1):
        date = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
        with self._cursor() as c:
            c.execute("SELECT * FROM daily_stats WHERE date = ?", (date,))
            row = c.fetchone()
            if row:
                new_val = row[column] + delta
                c.execute(f"UPDATE daily_stats SET {column} = ? WHERE date = ?", (new_val, date))
            else:
                defaults = {
                    "new_users": 0,
                    "active_users": 0,
                    "subscriptions_sold": 0,
                    "revenue_usd": 0.0
                }
                defaults[column] = delta
                c.execute('''
                    INSERT INTO daily_stats (date, new_users, active_users, subscriptions_sold, revenue_usd)
                    VALUES (?, ?, ?, ?, ?)
                ''', (date, defaults["new_users"], defaults["active_users"], defaults["subscriptions_sold"], defaults["revenue_usd"]))
    
    @retry_on_lock
    def create_payment(self, user_id: int, amount: float, currency: str = "USDT") -> str:
        import uuid
        payment_id = str(uuid.uuid4())[:16]
        with self._cursor() as c:
            c.execute("INSERT INTO payments (payment_id, user_id, amount, currency, status, created_at) VALUES (?,?,?,?,?,?)",
                      (payment_id, user_id, amount, currency, "pending", int(time.time())))
        return payment_id
    
    @retry_on_lock
    def add_fake_signals(self, user_id: int, count: int, action: str = "free_signal") -> int:
        with self._cursor() as c:
            now = int(time.time())
            inserted = 0
            for _ in range(count):
                c.execute("INSERT INTO actions (user_id, action, details, timestamp) VALUES (?,?,?,?)",
                          (user_id, action, "admin_nakrutka", now))
                inserted += 1
            return inserted
    
    @retry_on_lock
    def clear_user_signals(self, user_id: int, action: str = "free_signal") -> int:
        with self._cursor() as c:
            c.execute("DELETE FROM actions WHERE user_id=? AND action=?", (user_id, action))
            return c.rowcount

db = Database()

# ===================================================================
# РЫНОЧНЫЕ ДАННЫЕ (реальные + мок)
# ===================================================================
class MarketProvider:
    def __init__(self):
        self.exchanges = []
        for name in Config.EXCHANGES:
            try:
                if name == "binance":
                    exch = ccxt.binance()
                elif name == "bybit":
                    exch = ccxt.bybit()
                elif name == "okx":
                    exch = ccxt.okx()
                else:
                    continue
                self.exchanges.append((name, exch))
                logger.info(f"Exchange initialized: {name}")
            except Exception as e:
                logger.warning(f"Failed {name}: {e}")
    
    async def fetch_price(self, symbol: str) -> Tuple[float, float]:
        for name, exch in self.exchanges:
            try:
                ticker = await asyncio.to_thread(exch.fetch_ticker, symbol)
                return ticker["last"], ticker.get("percentage", 0)
            except Exception as e:
                logger.debug(f"{name} failed for {symbol}: {e}")
        base = 50000 if "BTC" in symbol else 3000
        price = base + random.uniform(-500, 500)
        change = random.uniform(-5, 5)
        return price, change
    
    async def get_historical_prices(self, symbol: str, limit=50) -> List[float]:
        base = 50000 if "BTC" in symbol else 3000
        return [base + random.uniform(-200, 200) for _ in range(limit)]
    
    async def get_market_summary(self) -> Dict:
        symbols = Config.SUPPORTED_SYMBOLS[:5]
        tasks = [self.fetch_price(sym) for sym in symbols]
        results = await asyncio.gather(*tasks)
        changes = [r[1] for r in results]
        avg_change = sum(changes)/len(changes) if changes else 0
        sentiment = "bullish" if avg_change > 1 else "bearish" if avg_change < -1 else "neutral"
        return {"symbols": symbols, "prices": [r[0] for r in results], "changes": changes,
                "avg_change": avg_change, "sentiment": sentiment}

_market = None
def get_market():
    global _market
    if _market is None:
        _market = MarketProvider()
    return _market

# ===================================================================
# НОВОСТИ (мок)
# ===================================================================
class NewsProvider:
    async def get_news(self, coin: str = "crypto", limit=5) -> List[Dict]:
        headlines = [
            {"title": "Bitcoin surges past $70k", "sentiment": 0.7},
            {"title": "Ethereum ETF approved", "sentiment": 0.9},
            {"title": "Solana network upgrade", "sentiment": 0.5},
            {"title": "Dogecoin jumps on tweet", "sentiment": 0.6},
            {"title": "Crypto regulation news", "sentiment": -0.2},
        ]
        if coin.lower() != "crypto":
            headlines = [h for h in headlines if coin.lower() in h["title"].lower()]
        return headlines[:limit]

_news = None
def get_news():
    global _news
    if _news is None:
        _news = NewsProvider()
    return _news

# ===================================================================
# ТЕХНИЧЕСКИЕ ИНДИКАТОРЫ
# ===================================================================
class TechIndicators:
    @staticmethod
    def rsi(prices: List[float], period=14) -> float:
        if len(prices) < period+1:
            return 50
        gains = losses = 0
        for i in range(1, period+1):
            diff = prices[-i] - prices[-i-1]
            if diff > 0:
                gains += diff
            else:
                losses += abs(diff)
        avg_gain = gains/period
        avg_loss = losses/period
        if avg_loss == 0:
            return 100
        rs = avg_gain/avg_loss
        return 100 - (100/(1+rs))
    
    @staticmethod
    def macd(prices: List[float]) -> Dict:
        if len(prices) < 26:
            return {"histogram": 0}
        def ema(data, span):
            alpha = 2/(span+1)
            val = data[0]
            for x in data[1:]:
                val = alpha*x + (1-alpha)*val
            return val
        ema12 = ema(prices, 12)
        ema26 = ema(prices, 26)
        macd_line = ema12 - ema26
        signal = ema([macd_line]*9, 9)
        return {"histogram": macd_line - signal}
    
    @staticmethod
    def atr(prices: List[float]) -> float:
        return prices[-1] * 0.02 if prices else 0

class SignalGenerator:
    def __init__(self):
        self.indicators = TechIndicators()
    
    def calc_tp_sl(self, price: float, action: str, atr_val: float = None) -> Dict:
        if atr_val is None:
            atr_val = price * 0.02
        if action == "BUY":
            tp1 = price + atr_val * 1.5
            tp2 = price + atr_val * 2.5
            sl  = price - atr_val * 1.0
        else:
            tp1 = price - atr_val * 1.5
            tp2 = price - atr_val * 2.5
            sl  = price + atr_val * 1.0
        return {"take_profit_1": round(tp1, 2), "take_profit_2": round(tp2, 2), "stop_loss": round(sl, 2)}
    
    async def generate(self, symbol: str, prices: List[float], news_sentiment: float) -> Dict:
        if not prices:
            return {"action": "HOLD", "confidence": 50, "reason": "No data", "price": 0}
        rsi_val = self.indicators.rsi(prices)
        macd = self.indicators.macd(prices)
        price = prices[-1]
        score = 0.0
        reasons = []
        if rsi_val < 30:
            score += 0.4
            reasons.append(f"RSI oversold ({rsi_val:.1f})")
        elif rsi_val > 70:
            score -= 0.4
            reasons.append(f"RSI overbought ({rsi_val:.1f})")
        if macd["histogram"] > 0:
            score += 0.2
            reasons.append("MACD positive")
        elif macd["histogram"] < 0:
            score -= 0.2
            reasons.append("MACD negative")
        score += news_sentiment * 0.3
        if news_sentiment > 0.2:
            reasons.append("Positive news")
        elif news_sentiment < -0.2:
            reasons.append("Negative news")
        action = "BUY" if score > 0.15 else "SELL" if score < -0.15 else "HOLD"
        confidence = int(50 + abs(score)*40)
        confidence = max(50, min(99, confidence))
        emoji = "🟢" if action == "BUY" else "🔴" if action == "SELL" else "⚪"
        tp_sl = self.calc_tp_sl(price, action)
        return {
            "action": action, "emoji": emoji, "confidence": confidence, "price": price,
            "rsi": round(rsi_val,1), "macd": round(macd["histogram"],4),
            "reason": "\n".join(reasons), "tp1": tp_sl["take_profit_1"], "tp2": tp_sl["take_profit_2"],
            "sl": tp_sl["stop_loss"]
        }

_analyzer = None
def get_analyzer():
    global _analyzer
    if _analyzer is None:
        _analyzer = SignalGenerator()
    return _analyzer

# ===================================================================
# ПЛАТЕЖИ (заглушка)
# ===================================================================
class PaymentManager:
    async def create_invoice(self, user_id: int, amount: float) -> Optional[str]:
        payment_id = db.create_payment(user_id, amount)
        return f"https://t.me/CryptoBot?start=pay_{payment_id}"

_payment = None
def get_payment():
    global _payment
    if _payment is None:
        _payment = PaymentManager()
    return _payment

# ===================================================================
# КЛАВИАТУРЫ
# ===================================================================
def main_menu() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📈 Signal", callback_data="signal"),
         InlineKeyboardButton(text="💰 Price", callback_data="price_btc")],
        [InlineKeyboardButton(text="🌍 Market", callback_data="market_summary"),
         InlineKeyboardButton(text="📰 News", callback_data="news")],
        [InlineKeyboardButton(text="💎 Subscribe", callback_data="subscribe"),
         InlineKeyboardButton(text="👥 Referral", callback_data="referral")],
        [InlineKeyboardButton(text="🏆 Leaderboard", callback_data="leaderboard"),
         InlineKeyboardButton(text="🔔 Settings", callback_data="settings")],
        [InlineKeyboardButton(text="👤 Profile", callback_data="profile"),
         InlineKeyboardButton(text="❓ Help", callback_data="help")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def back_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]])

# ===================================================================
# FSM
# ===================================================================
class WithdrawStates(StatesGroup):
    waiting_address = State()

class BroadcastStates(StatesGroup):
    waiting_message = State()

# ===================================================================
# ХЕНДЛЕРЫ КОМАНД
# ===================================================================
async def start_cmd(message: Message, state: FSMContext):
    user = message.from_user
    db.register_user(user.id, user.username, user.first_name)
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        ref_code = args[1][4:]
        referrer = db.get_by_referral_code(ref_code)
        if referrer and referrer != user.id:
            db.add_referral(referrer, user.id)
    await message.answer(
        f"🚀 *Welcome to CryptoPulse AI*, {user.first_name}!\n\n"
        f"AI-powered crypto signals with TP/SL.\n"
        f"💰 Premium: ${Config.SUBSCRIPTION_PRICE_USD}/{Config.SUBSCRIPTION_DAYS} days\n"
        f"Use /menu\n"
        f"Use /app to open web app",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu()
    )
    await state.clear()

async def menu_cmd(message: Message, state: FSMContext):
    await message.answer("📋 *Main Menu*", parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())
    await state.clear()

async def signal_cmd(message: Message):
    user_id = message.from_user.id
    has_sub = db.has_subscription(user_id)
    used_today = db.get_signal_usage_today(user_id)
    if not has_sub and used_today >= Config.FREE_SIGNALS_PER_DAY:
        await message.answer(f"❌ Free limit reached. Subscribe: /subscribe")
        return
    await message.answer("📊 Fetching AI signal...")
    market = get_market()
    news = get_news()
    analyzer = get_analyzer()
    try:
        price, change = await market.fetch_price("BTC/USDT")
        prices = await market.get_historical_prices("BTC/USDT", 50)
        news_items = await news.get_news("BTC", 3)
        avg_sentiment = sum(n["sentiment"] for n in news_items)/max(1,len(news_items))
        signal = await analyzer.generate("BTC/USDT", prices, avg_sentiment)
        text = (f"{signal['emoji']} *Signal for BTC/USDT*\n"
                f"Action: *{signal['action']}*\nConfidence: {signal['confidence']}%\n"
                f"Price: ${signal['price']:,.2f} ({change:+.2f}%)\n"
                f"RSI: {signal['rsi']} | MACD: {signal['macd']}\n"
                f"🎯 TP1: ${signal['tp1']} | TP2: ${signal['tp2']}\n🛑 SL: ${signal['sl']}\n"
                f"Analysis:\n{signal['reason']}")
        await message.answer(text, parse_mode=ParseMode.MARKDOWN)
        tp_sl = {"take_profit_1": signal['tp1'], "take_profit_2": signal['tp2'], "stop_loss": signal['sl']}
        db.save_signal_history(user_id, "BTC/USDT", signal['action'], signal['confidence'], signal['price'], tp_sl)
        db.log_action(user_id, "free_signal" if not has_sub else "premium_signal", signal['action'])
    except Exception as e:
        logger.error(f"Signal error: {e}")
        await message.answer("⚠️ Signal error. Try later.")

async def price_cmd(message: Message, symbol="BTC"):
    if symbol.upper() in ["BTC","ETH","SOL","BNB","XRP"]:
        symbol = f"{symbol.upper()}/USDT"
    market = get_market()
    try:
        price, change = await market.fetch_price(symbol)
        await message.answer(f"💰 *{symbol}*: ${price:,.2f} ({change:+.2f}%)", parse_mode=ParseMode.MARKDOWN)
    except:
        await message.answer("❌ Price fetch error")

async def market_cmd(message: Message):
    market = get_market()
    data = await market.get_market_summary()
    text = "🌍 *Market Overview*\n"
    for sym, p, chg in zip(data["symbols"], data["prices"], data["changes"]):
        text += f"{sym}: ${p:,.2f} ({chg:+.2f}%)\n"
    text += f"\nSentiment: {data['sentiment'].upper()}"
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

async def news_cmd(message: Message):
    news = get_news()
    items = await news.get_news("crypto", 5)
    text = "📰 *Crypto News*\n"
    for i in items:
        sent = "🟢" if i["sentiment"]>0.2 else "🔴" if i["sentiment"]<-0.2 else "⚪"
        text += f"{sent} {i['title']}\n"
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

async def subscribe_cmd(message: Message):
    if db.has_subscription(message.from_user.id):
        await message.answer("✅ You already have premium.")
        return
    await message.answer(
        f"💎 *Premium*: ${Config.SUBSCRIPTION_PRICE_USD} for {Config.SUBSCRIPTION_DAYS} days\n"
        f"Pay via CryptoBot (link will be generated).\n"
        f"Send /pay to get invoice.",
        parse_mode=ParseMode.MARKDOWN
    )

async def pay_cmd(message: Message):
    user_id = message.from_user.id
    payment = get_payment()
    link = await payment.create_invoice(user_id, Config.SUBSCRIPTION_PRICE_USD)
    if link:
        await message.answer(f"Pay here: {link}")
    else:
        await message.answer("Payment error, contact admin.")

async def referral_cmd(message: Message):
    stats = db.get_referral_stats(message.from_user.id)
    link = db.get_referral_link(message.from_user.id)
    text = (f"👥 *Referral*\nYour link: `{link}`\nDirect: {stats['direct']}\n"
            f"Earned: ${stats['earned']:.2f}\nBalance: ${stats['balance']:.2f}")
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

async def balance_cmd(message: Message):
    bal = db.get_balance(message.from_user.id)
    await message.answer(f"💰 Bonus balance: ${bal:.2f}\n/withdraw to cash out.")

async def withdraw_cmd(message: Message, state: FSMContext):
    bal = db.get_balance(message.from_user.id)
    if bal < 10:
        await message.answer("❌ Minimum $10 for withdrawal.")
        return
    await message.answer("💸 Send your USDT (TRC20) address:")
    await state.set_state(WithdrawStates.waiting_address)

async def withdraw_address(message: Message, state: FSMContext):
    addr = message.text.strip()
    if not addr.startswith("T") or len(addr) != 34:
        await message.answer("Invalid TRC20 address.")
        return
    user_id = message.from_user.id
    bal = db.get_balance(user_id)
    if db.deduct_balance(user_id, bal, "withdrawal"):
        await message.answer(f"✅ Withdrawal request: ${bal:.2f} USDT to {addr}. Processed within 24h.")
        for admin in Config.ADMIN_IDS:
            try:
                await message.bot.send_message(admin, f"💸 Withdrawal: {bal:.2f} USDT, user {user_id}, addr {addr}")
            except:
                pass
    else:
        await message.answer("❌ Withdrawal failed.")
    await state.clear()

async def profile_cmd(message: Message):
    user = db.get_user(message.from_user.id)
    if not user:
        return
    has_sub = db.has_subscription(message.from_user.id)
    expiry = datetime.fromtimestamp(user["subscribe_until"]).strftime("%Y-%m-%d") if user.get("subscribe_until") else "N/A"
    text = (f"👤 *Profile*\nID: {user['user_id']}\nPremium: {'✅' if has_sub else '❌'}\n"
            f"Expires: {expiry}\nBalance: ${user['balance']:.2f}\nSignals: {user['total_signals']}")
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

async def help_cmd(message: Message):
    text = ("📖 *Commands*\n/start, /menu, /signal, /price <BTC>, /market, /news\n"
            "/subscribe, /pay, /referral, /balance, /withdraw, /profile\n"
            "/join_competition, /submit_trade, /leaderboard\n"
            "/exchanges, /settings, /history\n"
            "/admin, /stats, /broadcast, /ban, /unban, /add_signals, /clear_signals, /signal_stats\n"
            "/app – Open Mini App")
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

async def app_cmd(message: Message):
    webapp_url = f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN', 'localhost')}/static/index.html"
    # Если домен не задан, используем относительный путь (для локального теста)
    if "localhost" in webapp_url:
        webapp_url = "http://web-production-989b49.up.railway.app/static/index.html"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚀 Open Mini App", web_app={"url": webapp_url})]])
    await message.answer("🌟 Open the Ultimate Trading Terminal:", reply_markup=kb)

# ===================================================================
# КОМАНДЫ ЛИГИ И ПАРТНЁРОВ
# ===================================================================
async def join_competition_cmd(message: Message):
    db.update_trader_stats(message.from_user.id, 0, None)
    await message.answer("✅ Joined competition! Use /submit_trade to add results.")

async def submit_trade_cmd(message: Message):
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Usage: /submit_trade <pnl> <win/loss>")
        return
    try:
        pnl = float(parts[1])
        result = parts[2].lower()
        is_win = result == "win"
    except:
        await message.answer("Invalid format.")
        return
    db.update_trader_stats(message.from_user.id, pnl, is_win)
    await message.answer(f"✅ Trade recorded: {pnl:.2f} USD, {result.upper()}")

async def leaderboard_cmd(message: Message):
    top = db.get_leaderboard()
    if not top:
        await message.answer("No participants yet.")
        return
    text = "🏆 *Leaderboard*\n"
    for i, entry in enumerate(top, 1):
        user = db.get_user(entry["user_id"])
        name = f"@{user['username']}" if user and user.get('username') else f"ID{entry['user_id']}"
        text += f"{i}. {name} — ${entry['total_pnl']:.2f} | WR: {entry['win_rate']:.1f}%\n"
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

async def exchanges_cmd(message: Message):
    user_id = message.from_user.id
    links = {
        "Binance": f"https://accounts.binance.com/register?ref=YOUR_GRO_28502_YQ2KA&uid={user_id}",
        "Bybit": f"https://www.bybit.com/invite?ref=GOBKDW5&uid={user_id}",
        "OKX": f"https://www.okx.com/join/YOUR_REF_ID?uid={user_id}"
    }
    text = "🏦 *Partner exchanges*\n"
    for name, url in links.items():
        text += f"• [{name}]({url})\n"
    await message.answer(text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    db.record_exchange_click(user_id, "exchanges_view")

# ===================================================================
# НАСТРОЙКИ УВЕДОМЛЕНИЙ
# ===================================================================
async def settings_cmd(message: Message):
    s = db.get_notif_settings(message.from_user.id)
    text = (f"🔔 *Notifications*\nPrice alerts: {'✅' if s['price_alert_enabled'] else '❌'} (threshold {s['price_threshold']}%)\n"
            f"Signal alerts: {'✅' if s['signal_enabled'] else '❌'}\nNews alerts: {'✅' if s['news_enabled'] else '❌'}\n"
            f"Coins: {s['coins']}")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Price Alert", callback_data="toggle_price"),
         InlineKeyboardButton(text="⚡ Signal Alert", callback_data="toggle_signal")],
        [InlineKeyboardButton(text="🗞️ News Alert", callback_data="toggle_news"),
         InlineKeyboardButton(text="💰 Threshold", callback_data="set_threshold")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]
    ])
    await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

async def history_cmd(message: Message):
    history = db.get_user_signal_history(message.from_user.id, 10)
    if not history:
        await message.answer("No signals yet.")
        return
    text = "📜 *Last 10 signals*\n"
    for h in history:
        dt = datetime.fromtimestamp(h["created_at"]).strftime("%m-%d %H:%M")
        text += f"{dt} {h['symbol']}: *{h['action']}* (conf {h['confidence']}%)\n"
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

# ===================================================================
# АДМИН-ПАНЕЛЬ
# ===================================================================
async def admin_cmd(message: Message):
    if not Config.is_admin(message.from_user.id):
        return
    stats = db.get_stats()
    text = (f"🛡️ *Admin*\nUsers: {stats['total_users']}\nPremium: {stats['active_premium']}\n"
            f"Revenue: ${stats['revenue']:.2f}\nToday new: {stats['today_new']}")
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

async def admin_stats_cmd(message: Message):
    if not Config.is_admin(message.from_user.id):
        return
    stats = db.get_stats()
    analytics = db.get_analytics_signals()
    text = (f"📊 *Stats*\nUsers: {stats['total_users']}\nPremium: {stats['active_premium']}\n"
            f"Revenue: ${stats['revenue']:.2f}\nAvg confidence: {analytics['avg_confidence']:.1f}%\n"
            f"BUY/SELL/HOLD: {analytics['action_counts'].get('BUY',0)}/{analytics['action_counts'].get('SELL',0)}/{analytics['action_counts'].get('HOLD',0)}")
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

async def broadcast_cmd(message: Message, state: FSMContext):
    if not Config.is_admin(message.from_user.id):
        return
    await message.answer("📢 Send broadcast message:")
    await state.set_state(BroadcastStates.waiting_message)

async def broadcast_send(message: Message, state: FSMContext):
    if not Config.is_admin(message.from_user.id):
        await state.clear()
        return
    text = message.text
    with db._cursor() as c:
        c.execute("SELECT user_id FROM users")
        users = [row["user_id"] for row in c.fetchall()]
    success = 0
    for uid in users:
        try:
            await message.bot.send_message(uid, f"📢 *Broadcast*\n{text}", parse_mode=ParseMode.MARKDOWN)
            success += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await message.answer(f"✅ Sent to {success} users")
    await state.clear()

async def ban_cmd(message: Message):
    if not Config.is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("/ban <user_id> [reason]")
        return
    target = int(parts[1])
    reason = " ".join(parts[2:]) if len(parts)>2 else "No reason"
    with db._cursor() as c:
        c.execute("UPDATE users SET banned=1, ban_reason=? WHERE user_id=?", (reason, target))
    await message.answer(f"✅ User {target} banned.")

async def unban_cmd(message: Message):
    if not Config.is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("/unban <user_id>")
        return
    target = int(parts[1])
    with db._cursor() as c:
        c.execute("UPDATE users SET banned=0, ban_reason=NULL WHERE user_id=?", (target,))
    await message.answer(f"✅ User {target} unbanned.")

async def add_signals_cmd(message: Message):
    if not Config.is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("/add_signals <user_id> <count>")
        return
    target = int(parts[1])
    count = int(parts[2])
    inserted = db.add_fake_signals(target, count, "free_signal")
    await message.answer(f"✅ Added {inserted} fake signals to user {target}")

async def clear_signals_cmd(message: Message):
    if not Config.is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("/clear_signals <user_id>")
        return
    target = int(parts[1])
    deleted = db.clear_user_signals(target, "free_signal")
    await message.answer(f"✅ Deleted {deleted} free signals for user {target}")

async def signal_stats_cmd(message: Message):
    if not Config.is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("/signal_stats <user_id>")
        return
    target = int(parts[1])
    used = db.get_signal_usage_today(target)
    await message.answer(f"User {target}: used {used}/{Config.FREE_SIGNALS_PER_DAY} free signals today.")

# ===================================================================
# CALLBACK HANDLERS
# ===================================================================
async def callback_main_menu(callback: CallbackQuery):
    await callback.message.edit_text("📋 *Main Menu*", parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())
    await callback.answer()

async def callback_signal(callback: CallbackQuery):
    await callback.message.delete()
    await signal_cmd(callback.message)
    await callback.answer()

async def callback_price(callback: CallbackQuery):
    sym = callback.data.split("_")[1] if "_" in callback.data else "BTC"
    await callback.message.delete()
    await price_cmd(callback.message, sym)
    await callback.answer()

async def callback_market(callback: CallbackQuery):
    await callback.message.delete()
    await market_cmd(callback.message)
    await callback.answer()

async def callback_news(callback: CallbackQuery):
    await callback.message.delete()
    await news_cmd(callback.message)
    await callback.answer()

async def callback_subscribe(callback: CallbackQuery):
    await subscribe_cmd(callback.message)
    await callback.answer()

async def callback_referral(callback: CallbackQuery):
    await callback.message.delete()
    await referral_cmd(callback.message)
    await callback.answer()

async def callback_profile(callback: CallbackQuery):
    await callback.message.delete()
    await profile_cmd(callback.message)
    await callback.answer()

async def callback_help(callback: CallbackQuery):
    await callback.message.delete()
    await help_cmd(callback.message)
    await callback.answer()

async def callback_leaderboard(callback: CallbackQuery):
    await callback.message.delete()
    await leaderboard_cmd(callback.message)
    await callback.answer()

async def callback_settings(callback: CallbackQuery):
    await callback.message.delete()
    await settings_cmd(callback.message)
    await callback.answer()

# ===================================================================
# ПЛАНИРОВЩИК
# ===================================================================
scheduler = AsyncIOScheduler()

async def cleanup_expired():
    with db._cursor() as c:
        now = int(time.time())
        c.execute("UPDATE users SET subscribed=0 WHERE subscribed=1 AND subscribe_until<?", (now,))
        logger.info("Cleanup expired subscriptions")

def setup_scheduler():
    scheduler.add_job(cleanup_expired, CronTrigger(hour=0, minute=30))
    # price_alert_check отключён, чтобы не блокировать БД
    scheduler.start()
    logger.info("Scheduler started")

# ===================================================================
# ВЕБ-СЕРВЕР ДЛЯ МИНИ-ПРИЛОЖЕНИЯ (aiohttp)
# ===================================================================

async def webapp_index(request):
    index_path = Path(__file__).parent / "webapp" / "index.html"
    if not index_path.exists():
        return web.Response(text="WebApp not found. Please create webapp folder.", status=404)
    return web.FileResponse(index_path)

async def webapp_index(request):
    print(f"Request path: {request.path}")
    file_path = Path(__file__).parent / "webapp" / "index.html"
    print(f"Looking for: {file_path}")
    if not file_path.exists():
        return web.Response(text=f"Not found: {file_path}", status=404)
    return web.FileResponse(file_path)

async def webapp_static(request):
    filename = request.match_info['filename']
    file_path = Path(__file__).parent / "webapp" / filename
    if not file_path.exists():
        return web.Response(status=404)
    return web.FileResponse(file_path)

# API endpoints
async def api_signal(request):
    data = await request.json()
    user_id = data.get('user_id')
    symbol = data.get('params', {}).get('symbol', 'BTC/USDT')
    # генерируем сигнал
    market = get_market()
    news = get_news()
    analyzer = get_analyzer()
    try:
        price, change = await market.fetch_price(symbol)
        prices = await market.get_historical_prices(symbol, 50)
        news_items = await news.get_news(symbol.split('/')[0], 3)
        avg_sentiment = sum(n["sentiment"] for n in news_items)/max(1,len(news_items))
        signal = await analyzer.generate(symbol, prices, avg_sentiment)
        has_sub = db.has_subscription(user_id) if user_id else False
        result = {
            "action": signal['action'],
            "price": signal['price'],
            "confidence": signal['confidence'],
            "reason": signal['reason'],
            "is_premium": has_sub
        }
        return web.json_response({"ok": True, "result": result})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})

async def api_chart(request):
    data = await request.json()
    symbol = data.get('params', {}).get('symbol', 'BTC/USDT')
    timeframe = data.get('params', {}).get('timeframe', '1h')
    limit = data.get('params', {}).get('limit', 50)
    
    market = get_market()
    # Получаем цены закрытия (или полноценные OHLCV, если есть)
    try:
        # Если у вас есть метод get_ohlcv – используйте его
        # Например, через ccxt:
        # ohlcv = await market.get_ohlcv(symbol, timeframe, limit)
        # или используем заглушку с преобразованием
        prices = await market.get_historical_prices(symbol, limit)
        # Строим свечи из цен (упрощённо, но для демо хватит)
        candles = []
        base_price = prices[0] if prices else 50000
        for i, p in enumerate(prices):
            ts = int(time.time()) - (limit - i) * 3600
            high = p + random.uniform(0, p*0.02)
            low = p - random.uniform(0, p*0.02)
            open_p = p - random.uniform(0, p*0.01)
            close = p
            candles.append({"time": ts, "open": round(open_p,2), "high": round(high,2), "low": round(low,2), "close": round(close,2)})
        return web.json_response({"ok": True, "result": candles})
    except Exception as e:
        logger.error(f"Chart error: {e}")
        return web.json_response({"ok": False, "error": str(e)})

async def api_profile(request):
    data = await request.json()
    user_id = data.get('user_id')
    if not user_id:
        return web.json_response({"ok": False, "error": "no user_id"})
    user = db.get_user(user_id)
    has_sub = db.has_subscription(user_id)
    stats = db.get_referral_stats(user_id)
    result = {
        "user_id": user_id,
        "has_subscription": has_sub,
        "balance": stats['balance'],
        "referral_count": stats['direct']
    }
    return web.json_response({"ok": True, "result": result})

async def api_referral_link(request):
    data = await request.json()
    user_id = data.get('user_id')
    link = db.get_referral_link(user_id) if user_id else ""
    return web.json_response({"ok": True, "result": link})

async def api_create_payment(request):
    data = await request.json()
    user_id = data.get('user_id')
    if not user_id:
        return web.json_response({"ok": False, "error": "no user_id"})
    payment = get_payment()
    link = await payment.create_invoice(user_id, Config.SUBSCRIPTION_PRICE_USD)
    return web.json_response({"ok": True, "result": link})

async def start_web_server():
    app = web.Application()
    app.router.add_get('/static/index.html', webapp_index)
    app.router.add_get('/static/{filename}', webapp_static)
    app.router.add_post('/api/signal', api_signal)
    app.router.add_post('/api/chart', api_chart)
    app.router.add_post('/api/profile', api_profile)
    app.router.add_post('/api/referral_link', api_referral_link)
    app.router.add_post('/api/create_payment', api_create_payment)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Web server started on port {port}")

# ===================================================================
# ЗАПУСК
# ===================================================================
async def main():
    Config.validate()
    logger.info("Starting CryptoPulse AI Ultimate")
    setup_scheduler()
    # Запускаем веб-сервер в фоне
    asyncio.create_task(start_web_server())
    bot = Bot(token=Config.API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())
    
    # Регистрация команд
    dp.message.register(start_cmd, Command("start"))
    dp.message.register(menu_cmd, Command("menu"))
    dp.message.register(signal_cmd, Command("signal"))
    dp.message.register(price_cmd, Command("price"))
    dp.message.register(market_cmd, Command("market"))
    dp.message.register(news_cmd, Command("news"))
    dp.message.register(subscribe_cmd, Command("subscribe"))
    dp.message.register(pay_cmd, Command("pay"))
    dp.message.register(referral_cmd, Command("referral"))
    dp.message.register(balance_cmd, Command("balance"))
    dp.message.register(withdraw_cmd, Command("withdraw"))
    dp.message.register(profile_cmd, Command("profile"))
    dp.message.register(help_cmd, Command("help"))
    dp.message.register(app_cmd, Command("app"))
    # Лига и партнёры
    dp.message.register(join_competition_cmd, Command("join_competition"))
    dp.message.register(submit_trade_cmd, Command("submit_trade"))
    dp.message.register(leaderboard_cmd, Command("leaderboard"))
    dp.message.register(exchanges_cmd, Command("exchanges"))
    dp.message.register(settings_cmd, Command("settings"))
    dp.message.register(history_cmd, Command("history"))
    # Админ
    dp.message.register(admin_cmd, Command("admin"))
    dp.message.register(admin_stats_cmd, Command("stats"))
    dp.message.register(broadcast_cmd, Command("broadcast"))
    dp.message.register(ban_cmd, Command("ban"))
    dp.message.register(unban_cmd, Command("unban"))
    dp.message.register(add_signals_cmd, Command("add_signals"))
    dp.message.register(clear_signals_cmd, Command("clear_signals"))
    dp.message.register(signal_stats_cmd, Command("signal_stats"))
    # FSM
    dp.message.register(withdraw_address, WithdrawStates.waiting_address)
    dp.message.register(broadcast_send, BroadcastStates.waiting_message)
    
    # Callbacks
    dp.callback_query.register(callback_main_menu, F.data == "main_menu")
    dp.callback_query.register(callback_signal, F.data == "signal")
    dp.callback_query.register(callback_price, F.data.startswith("price_"))
    dp.callback_query.register(callback_market, F.data == "market_summary")
    dp.callback_query.register(callback_news, F.data == "news")
    dp.callback_query.register(callback_subscribe, F.data == "subscribe")
    dp.callback_query.register(callback_referral, F.data == "referral")
    dp.callback_query.register(callback_profile, F.data == "profile")
    dp.callback_query.register(callback_help, F.data == "help")
    dp.callback_query.register(callback_leaderboard, F.data == "leaderboard")
    dp.callback_query.register(callback_settings, F.data == "settings")
    
    # Удаляем вебхук и polling
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Polling started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        sys.exit(1)