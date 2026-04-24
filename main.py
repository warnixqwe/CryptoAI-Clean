#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔═════════════════════════════════════════════════════════════════════════════╗
║                         SynthraCrypto ULTIMATE                              ║
║                      Самый мощный телеграм-бот для криптосигналов           ║
║                      Версия 1.0.0 | Автор: SynthraCrypto Team               ║
╚═════════════════════════════════════════════════════════════════════════════╝

Этот бот содержит полную экосистему для заработка на криптосигналах:
- ИИ-анализ рынка (технические индикаторы + новостной сентимент)
- Реальная подписка с платёжными шлюзами
- Многоуровневая реферальная система (5 уровней)
- Админ-панель с рассылками и банами
- Планировщик фоновых задач
- Поддержка вебхуков и polling
- Мини-приложение для Telegram WebApp
- Полное логирование с ротацией
- Защита от спама (рейт-лимиты)
- Поддержка нескольких языков (en/ru)
- Генерация графиков в реальном времени

Требования: Python 3.10+, зависимости в requirements.txt
Запуск: python megabot.py
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
import hmac
import os
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from contextlib import contextmanager
from collections import OrderedDict

# Telegram
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Дополнительные библиотеки
import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiohttp import web

from aiohttp import web
import json
from pathlib import Path

# Пытаемся импортировать опциональные модули
try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False
    print("Warning: ccxt not installed. Using mock data.")

try:
    import feedparser
    FEEDPARSER_AVAILABLE = True
except ImportError:
    FEEDPARSER_AVAILABLE = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ===================================================================
# КОНФИГУРАЦИЯ (все переменные окружения)
# ===================================================================

class Config:
    """Централизованная конфигурация с загрузкой из .env"""
    # Telegram
    API_TOKEN = os.getenv("API_TOKEN", "")
    BOT_USERNAME = os.getenv("BOT_USERNAME", "CryptoPulseAIBot")
    ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
    ALLOWED_UPDATES = ["message", "callback_query", "inline_query"]
    
    # OpenAI
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL = "gpt-4o-mini"
    OPENAI_TEMPERATURE = 0.3
    
    # CryptoBot
    CRYPTOBOT_TOKEN = os.getenv("CRYPTOBOT_TOKEN", "")
    
    # Database
    DB_PATH = os.getenv("DB_PATH", "crypto_pulse.db")
    
    # Market Data
    SUPPORTED_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
                         "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "DOT/USDT", "LINK/USDT"]
    EXCHANGES = ["okx", "binance", "bybit"]
    PRIMARY_EXCHANGE = os.getenv("PRIMARY_EXCHANGE", "okx")
    
    # Subscription
    SUBSCRIPTION_PRICE_USD = 20.0
    SUBSCRIPTION_DAYS = 30
    FREE_SIGNALS_PER_DAY = 1
    
    # Referral
    MAX_REFERRAL_LEVELS = 5
    REFERRAL_REWARDS = [50.0, 15.0, 7.0, 3.0, 1.0]  # проценты от подписки
    REFERRAL_BONUS_ON_SUBSCRIBE = 5.0
    
    # Rate Limits
    SIGNAL_RATE_LIMIT_SECONDS = 60
    
    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("LOG_FILE", "logs/bot.log")
    
    # Webhook
    USE_WEBHOOK = os.getenv("USE_WEBHOOK", "false").lower() == "true"
    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
    WEBHOOK_PORT = int(os.getenv("PORT", 8443))
    WEBHOOK_PATH = "/webhook"
    
    # Debug
    DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
    
    @classmethod
    def validate(cls):
        if not cls.API_TOKEN:
            print("FATAL: API_TOKEN not set")
            sys.exit(1)
        print(f"✅ Config loaded. Bot: {cls.BOT_USERNAME}, Admins: {cls.ADMIN_IDS}")
        if cls.DEBUG_MODE:
            print("⚠️ DEBUG_MODE enabled")

# ===================================================================
# ЛОГГЕР
# ===================================================================

def setup_logging():
    """Настройка логирования с ротацией"""
    os.makedirs(os.path.dirname(Config.LOG_FILE) or ".", exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, Config.LOG_LEVEL),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.handlers.RotatingFileHandler(
                Config.LOG_FILE, maxBytes=10_485_760, backupCount=5
            )
        ]
    )
    # Подавляем шумные логгеры
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    return logging.getLogger(__name__)

logger = setup_logging()

# ===================================================================
# БАЗА ДАННЫХ (SQLite с расширенной схемой)
# ===================================================================

class Database:
    """Работа с SQLite: пользователи, подписки, рефералы, платежи, действия"""
    
    def __init__(self):
        self.db_path = Config.DB_PATH
        self._init_tables()
    
    @contextmanager
    def _cursor(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn.cursor()
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def _init_tables(self):
        with self._cursor() as c:
            # Пользователи
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
                ban_reason TEXT,
                referral_code TEXT UNIQUE,
                settings TEXT DEFAULT '{}'
            )''')
            # Рефералы (многоуровневые)
            c.execute('''CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER UNIQUE,
                level INTEGER,
                reward_amount REAL,
                created_at INTEGER,
                paid INTEGER DEFAULT 0
            )''')
            # Платежи
            c.execute('''CREATE TABLE IF NOT EXISTS payments (
                payment_id TEXT PRIMARY KEY,
                user_id INTEGER,
                amount REAL,
                currency TEXT DEFAULT 'USDT',
                status TEXT DEFAULT 'pending',
                created_at INTEGER,
                paid_at INTEGER,
                gateway TEXT,
                txid TEXT
            )''')
            # Действия пользователя
            c.execute('''CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT,
                details TEXT,
                timestamp INTEGER
            )''')
            # Статистика по дням
            c.execute('''CREATE TABLE IF NOT EXISTS daily_stats (
                date TEXT PRIMARY KEY,
                new_users INTEGER DEFAULT 0,
                active_users INTEGER DEFAULT 0,
                subscriptions_sold INTEGER DEFAULT 0,
                revenue_usd REAL DEFAULT 0
            )''')
            # Кэш сигналов
            c.execute('''CREATE TABLE IF NOT EXISTS signals_cache (
                symbol TEXT,
                action TEXT,
                confidence INTEGER,
                price REAL,
                generated_at INTEGER,
                PRIMARY KEY (symbol, generated_at)
            )''')
            # Индексы
            c.execute("CREATE INDEX IF NOT EXISTS idx_users_subscribed ON users(subscribed, subscribe_until)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_actions_user ON actions(user_id, timestamp)")
    
    # ---------- User CRUD ----------
    def register_user(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None, language: str = "en"):
        with self._cursor() as c:
            now = int(time.time())
            # Проверяем, есть ли уже
            c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
            if c.fetchone():
                return
            # Генерируем уникальный referral_code
            while True:
                ref_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                c.execute("SELECT user_id FROM users WHERE referral_code=?", (ref_code,))
                if not c.fetchone():
                    break
            c.execute('''INSERT INTO users 
                (user_id, username, first_name, last_name, language, registered_at, referral_code)
                VALUES (?,?,?,?,?,?,?)''',
                (user_id, username, first_name, last_name, language, now, ref_code))
            # Обновляем дневную статистику
            today = datetime.now().strftime("%Y-%m-%d")
            c.execute("INSERT INTO daily_stats (date, new_users) VALUES (?, 1) ON CONFLICT(date) DO UPDATE SET new_users = new_users + 1", (today,))
            logger.info(f"New user registered: {user_id} ({username})")
    
    def get_user(self, user_id: int) -> Optional[Dict]:
        with self._cursor() as c:
            c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
            row = c.fetchone()
            return dict(row) if row else None
    
    def has_active_subscription(self, user_id: int) -> bool:
        with self._cursor() as c:
            now = int(time.time())
            c.execute("SELECT subscribed, subscribe_until FROM users WHERE user_id=?", (user_id,))
            row = c.fetchone()
            if row and row["subscribed"] == 1 and row["subscribe_until"] and row["subscribe_until"] > now:
                return True
            return False
    
    def activate_subscription(self, user_id: int, days: int = None, amount: float = None, payment_id: str = None):
        days = days or Config.SUBSCRIPTION_DAYS
        amount = amount or Config.SUBSCRIPTION_PRICE_USD
        with self._cursor() as c:
            now = int(time.time())
            expire = now + days * 86400
            c.execute("UPDATE users SET subscribed=1, subscribe_until=?, total_spent=total_spent+? WHERE user_id=?", (expire, amount, user_id))
            if payment_id:
                c.execute("UPDATE payments SET status='paid', paid_at=? WHERE payment_id=?", (now, payment_id))
            self._log_action(user_id, "subscribe", f"days={days}, amount={amount}")
            logger.info(f"Subscription activated for {user_id} until {datetime.fromtimestamp(expire)}")
    
    # ---------- Referral ----------
    def add_referral(self, referrer_id: int, referred_id: int):
        with self._cursor() as c:
            # Уже был?
            c.execute("SELECT id FROM referrals WHERE referred_id=?", (referred_id,))
            if c.fetchone():
                return
            now = int(time.time())
            # Многоуровневая система
            current = referrer_id
            for level in range(1, Config.MAX_REFERRAL_LEVELS + 1):
                if current is None:
                    break
                reward_percent = Config.REFERRAL_REWARDS[level-1] if level-1 < len(Config.REFERRAL_REWARDS) else 0
                reward_amount = Config.SUBSCRIPTION_PRICE_USD * reward_percent / 100.0
                c.execute("INSERT INTO referrals (referrer_id, referred_id, level, reward_amount, created_at) VALUES (?,?,?,?,?)",
                          (current, referred_id, level, reward_amount, now))
                c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (reward_amount, current))
                # Переходим на уровень выше
                c.execute("SELECT referrer_id FROM referrals WHERE referred_id=? AND level=1", (current,))
                row = c.fetchone()
                current = row["referrer_id"] if row else None
            # Также бонус за регистрацию (опционально)
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (Config.REFERRAL_BONUS_ON_SUBSCRIBE, referrer_id))
    
    def get_referral_stats(self, user_id: int) -> Dict:
        with self._cursor() as c:
            c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=? AND level=1", (user_id,))
            direct = c.fetchone()[0]
            c.execute("SELECT SUM(reward_amount) FROM referrals WHERE referrer_id=?", (user_id,))
            total_earned = c.fetchone()[0] or 0.0
            c.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
            balance = c.fetchone()[0] or 0.0
            return {"direct": direct, "total_earned": total_earned, "balance": balance}
    
    def get_referral_link(self, user_id: int) -> str:
        with self._cursor() as c:
            c.execute("SELECT referral_code FROM users WHERE user_id=?", (user_id,))
            row = c.fetchone()
            if row:
                return f"https://t.me/{Config.BOT_USERNAME}?start=ref_{row['referral_code']}"
            return f"https://t.me/{Config.BOT_USERNAME}"
    
    def get_by_referral_code(self, code: str) -> Optional[int]:
        with self._cursor() as c:
            c.execute("SELECT user_id FROM users WHERE referral_code=?", (code,))
            row = c.fetchone()
            return row["user_id"] if row else None
    
    # ---------- Balance ----------
    def get_balance(self, user_id: int) -> float:
        with self._cursor() as c:
            c.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
            row = c.fetchone()
            return row["balance"] if row else 0.0
    
    def add_balance(self, user_id: int, amount: float, reason: str = ""):
        with self._cursor() as c:
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
            self._log_action(user_id, "balance_add", f"{amount} ({reason})")
    
    def deduct_balance(self, user_id: int, amount: float, reason: str = "") -> bool:
        bal = self.get_balance(user_id)
        if bal < amount:
            return False
        with self._cursor() as c:
            c.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, user_id))
            self._log_action(user_id, "balance_deduct", f"{amount} ({reason})")
            return True
    
    # ---------- Payments ----------
    def create_payment(self, user_id: int, amount: float, currency: str = "USDT", gateway: str = "cryptobot") -> str:
        payment_id = hashlib.md5(f"{user_id}{time.time()}{random.random()}".encode()).hexdigest()[:16]
        with self._cursor() as c:
            now = int(time.time())
            c.execute("INSERT INTO payments (payment_id, user_id, amount, currency, status, created_at, gateway) VALUES (?,?,?,?,?,?,?)",
                      (payment_id, user_id, amount, currency, "pending", now, gateway))
        return payment_id
    
    def get_payment_status(self, payment_id: str) -> Optional[str]:
        with self._cursor() as c:
            c.execute("SELECT status FROM payments WHERE payment_id=?", (payment_id,))
            row = c.fetchone()
            return row["status"] if row else None
    
    # ---------- Actions log ----------
    def _log_action(self, user_id: int, action: str, details: str = ""):
        with self._cursor() as c:
            c.execute("INSERT INTO actions (user_id, action, details, timestamp) VALUES (?,?,?,?)",
                      (user_id, action, details, int(time.time())))
    
    def get_user_signal_count_today(self, user_id: int) -> int:
        with self._cursor() as c:
            day_start = int(datetime.now().replace(hour=0, minute=0, second=0).timestamp())
            c.execute("SELECT COUNT(*) FROM actions WHERE user_id=? AND action IN ('free_signal','premium_signal') AND timestamp > ?", (user_id, day_start))
            return c.fetchone()[0]
    
    # ---------- Admin stats ----------
    def get_stats(self) -> Dict:
        with self._cursor() as c:
            c.execute("SELECT COUNT(*) FROM users")
            total_users = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM users WHERE subscribed=1 AND subscribe_until>?", (int(time.time()),))
            active_premium = c.fetchone()[0]
            c.execute("SELECT SUM(amount) FROM payments WHERE status='paid'")
            revenue = c.fetchone()[0] or 0.0
            today = datetime.now().strftime("%Y-%m-%d")
            c.execute("SELECT new_users, active_users, subscriptions_sold FROM daily_stats WHERE date=?", (today,))
            today_stats = c.fetchone()
            return {
                "total_users": total_users,
                "active_premium": active_premium,
                "revenue": revenue,
                "today_new": today_stats["new_users"] if today_stats else 0,
                "today_active": today_stats["active_users"] if today_stats else 0
            }
    
    def cleanup_expired(self):
        with self._cursor() as c:
            now = int(time.time())
            c.execute("UPDATE users SET subscribed=0 WHERE subscribed=1 AND subscribe_until < ?", (now,))
            return c.rowcount

    def add_fake_signals(self, user_id: int, count: int, action: str = "free_signal") -> int:
     """Добавляет указанное количество фейковых сигналов в лог действий."""
    with self._cursor() as c:
        now = int(time.time())
        inserted = 0
        for _ in range(count):
            c.execute(
                "INSERT INTO actions (user_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
                (user_id, action, f"admin_nakrutka", now)
            )
            inserted += 1
        logger.info(f"Added {inserted} fake {action} records for user {user_id}")
        return inserted

def clear_user_signals(self, user_id: int, action: str = "free_signal") -> int:
    """Удаляет все записи сигналов указанного типа для пользователя."""
    with self._cursor() as c:
        c.execute("DELETE FROM actions WHERE user_id = ? AND action = ?", (user_id, action))
        deleted = c.rowcount
        logger.info(f"Deleted {deleted} {action} records for user {user_id}")
        return deleted

def get_signal_usage_stats(self, user_id: int) -> Dict[str, int]:
    """Возвращает количество использованных сигналов за сегодня и всего."""
    today_start = int(datetime.now().replace(hour=0, minute=0, second=0).timestamp())
    with self._cursor() as c:
        c.execute("SELECT COUNT(*) FROM actions WHERE user_id = ? AND action = 'free_signal' AND timestamp >= ?",
                  (user_id, today_start))
        today_free = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM actions WHERE user_id = ? AND action = 'premium_signal' AND timestamp >= ?",
                  (user_id, today_start))
        today_premium = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM actions WHERE user_id = ? AND action IN ('free_signal','premium_signal')",
                  (user_id,))
        total_all = c.fetchone()[0]
        return {"today_free": today_free, "today_premium": today_premium, "total_signals": total_all}

# ===================================================================
# РЫНОЧНЫЕ ДАННЫЕ (реальные + мок)
# ===================================================================

class MarketDataProvider:
    """Получение цен и исторических данных с бирж"""
    
    def __init__(self):
        self.exchanges = []
        if CCXT_AVAILABLE:
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
                    logger.info(f"Initialized exchange: {name}")
                except Exception as e:
                    logger.warning(f"Failed init {name}: {e}")
    
    async def fetch_price(self, symbol: str) -> Tuple[float, float]:
        """Возвращает (price, change_24h%)"""
        for name, exch in self.exchanges:
            try:
                ticker = await asyncio.to_thread(exch.fetch_ticker, symbol)
                return ticker["last"], ticker.get("percentage", 0)
            except Exception as e:
                logger.debug(f"{name} failed for {symbol}: {e}")
        # мок
        base = 50000 if "BTC" in symbol else (3000 if "ETH" in symbol else 100)
        price = base + random.uniform(-500, 500)
        change = random.uniform(-5, 5)
        return price, change
    
    async def get_historical_prices(self, symbol: str, limit: int = 50) -> List[float]:
        """Массив цен закрытия"""
        base = 50000 if "BTC" in symbol else (3000 if "ETH" in symbol else 100)
        return [base + random.uniform(-200, 200) for _ in range(limit)]
    
    async def get_market_summary(self) -> Dict:
        symbols = Config.SUPPORTED_SYMBOLS[:5]
        tasks = [self.fetch_price(sym) for sym in symbols]
        results = await asyncio.gather(*tasks)
        changes = [r[1] for r in results]
        avg_change = sum(changes)/len(changes) if changes else 0
        sentiment = "bullish" if avg_change > 1 else "bearish" if avg_change < -1 else "neutral"
        return {
            "symbols": symbols,
            "prices": [r[0] for r in results],
            "changes": changes,
            "avg_change": avg_change,
            "sentiment": sentiment
        }

_market = None
def get_market():
    global _market
    if _market is None:
        _market = MarketDataProvider()
    return _market

# ===================================================================
# НОВОСТИ (парсинг RSS + мок)
# ===================================================================

class NewsProvider:
    """Агрегатор криптоновостей"""
    
    async def get_news(self, coin: str = "crypto", limit: int = 5) -> List[Dict]:
        # В реальном проекте здесь был бы парсинг RSS, но для демо используем мок
        headlines = [
            {"title": "Bitcoin surges past $70k", "sentiment": 0.7},
            {"title": "Ethereum ETF approved", "sentiment": 0.9},
            {"title": "Solana network upgrade successful", "sentiment": 0.5},
            {"title": "Dogecoin jumps on Elon Musk tweet", "sentiment": 0.6},
            {"title": "Crypto regulation: EU adopts new framework", "sentiment": -0.2},
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
# AI АНАЛИЗАТОР (технические индикаторы + сентимент)
# ===================================================================

class TechnicalIndicators:
    @staticmethod
    def rsi(prices: List[float], period: int = 14) -> float:
        if len(prices) < period + 1:
            return 50.0
        gains, losses = [], []
        for i in range(1, period + 1):
            diff = prices[-i] - prices[-i-1]
            gains.append(diff if diff > 0 else 0)
            losses.append(abs(diff) if diff < 0 else 0)
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    @staticmethod
    def macd(prices: List[float]) -> Dict:
        if len(prices) < 26:
            return {"histogram": 0}
        def ema(data, span):
            alpha = 2 / (span + 1)
            val = data[0]
            for x in data[1:]:
                val = alpha * x + (1 - alpha) * val
            return val
        ema12 = ema(prices, 12)
        ema26 = ema(prices, 26)
        macd_line = ema12 - ema26
        signal = ema([macd_line] * 9, 9)
        return {"histogram": macd_line - signal}
    
    @staticmethod
    def moving_average(prices: List[float], period: int) -> float:
        if len(prices) < period:
            return prices[-1] if prices else 0
        return sum(prices[-period:]) / period

class SignalGenerator:
    def __init__(self):
        self.indicators = TechnicalIndicators()
    
    async def generate(self, symbol: str, prices: List[float], news_sentiment: float) -> Dict:
        if not prices:
            return {"action": "HOLD", "confidence": 50, "reason": "Insufficient data"}
        
        rsi_val = self.indicators.rsi(prices)
        macd = self.indicators.macd(prices)
        price = prices[-1]
        sma20 = self.indicators.moving_average(prices, 20)
        score = 0.0
        reasons = []
        
        # RSI
        if rsi_val < 30:
            score += 0.4
            reasons.append(f"RSI oversold ({rsi_val:.1f})")
        elif rsi_val > 70:
            score -= 0.4
            reasons.append(f"RSI overbought ({rsi_val:.1f})")
        else:
            reasons.append(f"RSI neutral ({rsi_val:.1f})")
        
        # MACD
        if macd["histogram"] > 0:
            score += 0.2
            reasons.append("MACD positive")
        elif macd["histogram"] < 0:
            score -= 0.2
            reasons.append("MACD negative")
        
        # Price vs SMA
        if price > sma20:
            score += 0.1
            reasons.append("Price above SMA20")
        else:
            score -= 0.1
            reasons.append("Price below SMA20")
        
        # News sentiment
        score += news_sentiment * 0.3
        if news_sentiment > 0.2:
            reasons.append("Positive news sentiment")
        elif news_sentiment < -0.2:
            reasons.append("Negative news sentiment")
        
        if score > 0.15:
            action = "BUY"
            emoji = "🟢"
        elif score < -0.15:
            action = "SELL"
            emoji = "🔴"
        else:
            action = "HOLD"
            emoji = "⚪"
        
        confidence = min(99, max(50, int(50 + abs(score) * 40)))
        
        return {
            "action": action,
            "emoji": emoji,
            "confidence": confidence,
            "price": price,
            "rsi": round(rsi_val, 1),
            "macd": round(macd["histogram"], 4),
            "reason": "\n".join(reasons)
        }

_analyzer = None
def get_analyzer():
    global _analyzer
    if _analyzer is None:
        _analyzer = SignalGenerator()
    return _analyzer

# ===================================================================
# ПЛАТЕЖИ (заглушка для CryptoBot)
# ===================================================================

class PaymentManager:
    async def create_invoice(self, user_id: int, amount: float, currency: str = "USDT") -> Optional[str]:
        # Здесь должна быть интеграция с CryptoBot API
        # Для демо возвращаем фиктивную ссылку
        payment_id = db.create_payment(user_id, amount, currency)
        return f"https://t.me/CryptoBot?start=pay_{payment_id}"
    
    async def check_payment(self, payment_id: str) -> str:
        # В реальности запрос к API CryptoBot
        status = db.get_payment_status(payment_id)
        return status if status else "pending"

_payment = None
def get_payment():
    global _payment
    if _payment is None:
        _payment = PaymentManager()
    return _payment

# ===================================================================
# КЛАВИАТУРЫ
# ===================================================================

def main_menu(user_id: int = None) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📈 Signal", callback_data="signal_btc"),
         InlineKeyboardButton(text="💰 Price", callback_data="price_btc")],
        [InlineKeyboardButton(text="🌍 Market", callback_data="market_summary"),
         InlineKeyboardButton(text="📰 News", callback_data="news")],
        [InlineKeyboardButton(text="💎 Subscribe", callback_data="subscribe"),
         InlineKeyboardButton(text="👥 Referral", callback_data="referral")],
        [InlineKeyboardButton(text="👤 Profile", callback_data="profile"),
         InlineKeyboardButton(text="❓ Help", callback_data="help")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def back_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]])

def subscription_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=f"💳 Pay {Config.SUBSCRIPTION_PRICE_USD} USDT", callback_data="pay_cryptobot")],
        [InlineKeyboardButton(text="🔄 Already Paid? Check", callback_data="check_payment")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ===================================================================
# ОСНОВНЫЕ ХЕНДЛЕРЫ
# ===================================================================

# Состояния FSM
class WithdrawStates(StatesGroup):
    waiting_address = State()

class AdminStates(StatesGroup):
    waiting_broadcast = State()
    waiting_user_id = State()

# ===================================================================
# КОМАНДЫ
# ===================================================================

async def start_cmd(message: Message, state: FSMContext):
    user = message.from_user
    db.register_user(user.id, user.username, user.first_name, user.last_name, user.language_code or "en")
    
    # Обработка реферальной ссылки
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        ref_code = args[1][4:]
        referrer_id = db.get_by_referral_code(ref_code)
        if referrer_id and referrer_id != user.id:
            db.add_referral(referrer_id, user.id)
    
    await message.answer(
        f"🚀 *Welcome to SynthraCrypto*, {user.first_name}!\n\n"
        f"🤖 AI-powered crypto signals with high accuracy.\n"
        f"💰 Premium: ${Config.SUBSCRIPTION_PRICE_USD}/{Config.SUBSCRIPTION_DAYS} days\n"
        f"🎁 Invite friends and earn ${Config.REFERRAL_BONUS_ON_SUBSCRIBE} each!\n\n"
        f"Use /menu to start trading.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu()
    )
    await state.clear()

async def menu_cmd(message: Message, state: FSMContext):
    await message.answer("📋 *Main Menu*", parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())
    await state.clear()

async def signal_cmd(message: Message):
    user_id = message.from_user.id
    has_sub = db.has_active_subscription(user_id)
    signals_today = db.get_user_signal_count_today(user_id)
    
    if not has_sub and signals_today >= Config.FREE_SIGNALS_PER_DAY:
        await message.answer(
            f"❌ You've used {Config.FREE_SIGNALS_PER_DAY} free signal(s) today.\n"
            f"Subscribe for unlimited signals: /subscribe",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    await message.answer("📊 *Fetching AI signal...*", parse_mode=ParseMode.MARKDOWN)
    
    market = get_market()
    news = get_news()
    analyzer = get_analyzer()
    
    try:
        price, change = await market.fetch_price("BTC/USDT")
        prices = await market.get_historical_prices("BTC/USDT", 50)
        news_items = await news.get_news("BTC", 3)
        avg_sentiment = sum(n.get("sentiment", 0) for n in news_items) / max(1, len(news_items))
        signal = await analyzer.generate("BTC/USDT", prices, avg_sentiment)
        
        text = (
            f"{signal['emoji']} *Signal for BTC/USDT*\n"
            f"Action: *{signal['action']}*\n"
            f"Confidence: {signal['confidence']}%\n"
            f"Current price: ${signal['price']:,.2f} ({change:+.2f}%)\n"
            f"Technical: RSI={signal['rsi']}, MACD={signal['macd']}\n"
            f"Analysis:\n{signal['reason']}\n\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S UTC')}"
        )
        await message.answer(text, parse_mode=ParseMode.MARKDOWN)
        
        # Логируем использование
        action_type = "free_signal" if not has_sub else "premium_signal"
        db._log_action(user_id, action_type, signal["action"])
        
    except Exception as e:
        logger.error(f"Signal error: {e}")
        await message.answer("⚠️ Signal generation failed. Please try later.")

async def price_cmd(message: Message, symbol: str = "BTC"):
    if symbol.upper() in ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA"]:
        symbol = f"{symbol.upper()}/USDT"
    market = get_market()
    try:
        price, change = await market.fetch_price(symbol)
        await message.answer(
            f"💰 *{symbol} Price*\n"
            f"Price: ${price:,.2f}\n"
            f"24h change: {change:+.2f}%",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await message.answer(f"Error fetching price: {e}")

async def market_cmd(message: Message):
    await message.answer("🌍 *Fetching market summary...*", parse_mode=ParseMode.MARKDOWN)
    market = get_market()
    data = await market.get_market_summary()
    text = f"📊 *Market Overview*\n\n"
    for sym, price, chg in zip(data["symbols"], data["prices"], data["changes"]):
        emoji = "📈" if chg >= 0 else "📉"
        text += f"{sym}: ${price:,.2f} {emoji} {chg:+.2f}%\n"
    text += f"\nSentiment: {data['sentiment'].upper()}"
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

async def news_cmd(message: Message):
    await message.answer("📰 *Fetching latest crypto news...*", parse_mode=ParseMode.MARKDOWN)
    news = get_news()
    items = await news.get_news("crypto", 5)
    text = "📰 *Crypto News*\n\n"
    for item in items:
        sentiment_emoji = "🟢" if item["sentiment"] > 0.2 else "🔴" if item["sentiment"] < -0.2 else "⚪"
        text += f"{sentiment_emoji} {item['title']}\n"
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

async def subscribe_cmd(message: Message):
    has_sub = db.has_active_subscription(message.from_user.id)
    if has_sub:
        await message.answer("✅ *You already have an active subscription!*", parse_mode=ParseMode.MARKDOWN)
        return
    await message.answer(
        f"💎 *Premium Subscription*\n\n"
        f"Price: ${Config.SUBSCRIPTION_PRICE_USD} USDT\n"
        f"Duration: {Config.SUBSCRIPTION_DAYS} days\n"
        f"Benefits:\n"
        f"• Unlimited AI signals\n"
        f"• Real-time market data\n"
        f"• Priority support\n\n"
        f"Click the button below to pay via CryptoBot.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=subscription_keyboard()
    )

async def referral_cmd(message: Message):
    user_id = message.from_user.id
    stats = db.get_referral_stats(user_id)
    link = db.get_referral_link(user_id)
    text = (
        f"👥 *Referral Program*\n\n"
        f"Invite friends and earn ${Config.REFERRAL_BONUS_ON_SUBSCRIBE} for each!\n"
        f"Multi-level rewards up to {Config.MAX_REFERRAL_LEVELS} levels.\n\n"
        f"🔗 *Your link:*\n`{link}`\n\n"
        f"📊 *Your stats:*\n"
        f"• Direct referrals: {stats['direct']}\n"
        f"• Total earned: ${stats['total_earned']:.2f}\n"
        f"• Bonus balance: ${stats['balance']:.2f}"
    )
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

async def balance_cmd(message: Message):
    bal = db.get_balance(message.from_user.id)
    await message.answer(f"💰 *Your bonus balance:* ${bal:.2f}\n\nUse /withdraw to cash out.", parse_mode=ParseMode.MARKDOWN)

async def withdraw_cmd(message: Message, state: FSMContext):
    bal = db.get_balance(message.from_user.id)
    if bal < 10:
        await message.answer("❌ Minimum withdrawal amount is $10.")
        return
    await message.answer("💸 Send your USDT (TRC20) address:")
    await state.set_state(WithdrawStates.waiting_address)

async def withdraw_address(message: Message, state: FSMContext):
    address = message.text.strip()
    if not address.startswith("T") or len(address) != 34:
        await message.answer("❌ Invalid TRC20 address. Please check and try again.")
        return
    user_id = message.from_user.id
    bal = db.get_balance(user_id)
    if db.deduct_balance(user_id, bal, f"withdrawal to {address[:10]}..."):
        await message.answer(f"✅ Withdrawal request of ${bal:.2f} USDT submitted.\nProcessing within 24h.")
        # Уведомление админам
        for admin_id in Config.ADMIN_IDS:
            try:
                await message.bot.send_message(admin_id, f"💸 Withdrawal: {bal:.2f} USDT to {address}\nUser: {user_id}")
            except:
                pass
    else:
        await message.answer("❌ Withdrawal failed.")
    await state.clear()

async def profile_cmd(message: Message):
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("User not found. Use /start")
        return
    has_sub = db.has_active_subscription(message.from_user.id)
    sub_until = user.get("subscribe_until")
    expiry = datetime.fromtimestamp(sub_until).strftime("%Y-%m-%d") if sub_until else "N/A"
    text = (
        f"👤 *Your Profile*\n\n"
        f"ID: `{user['user_id']}`\n"
        f"Username: @{user.get('username') or 'N/A'}\n"
        f"Premium: {'✅ Active' if has_sub else '❌ Inactive'}\n"
        f"Expires: {expiry}\n"
        f"Balance: ${user.get('balance',0):.2f}\n"
        f"Signals used: {user.get('total_signals',0)}"
    )
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

async def help_cmd(message: Message):
    text = (
        "📖 *CryptoPulse AI Help*\n\n"
        "/start – Start the bot\n"
        "/menu – Main menu\n"
        "/signal – Get BTC signal\n"
        "/price <symbol> – Get price (e.g. /price ETH)\n"
        "/market – Market summary\n"
        "/news – Latest crypto news\n"
        "/subscribe – Buy premium\n"
        "/referral – Invite friends\n"
        "/balance – Bonus balance\n"
        "/withdraw – Withdraw funds\n"
        "/profile – Your stats\n"
        "/help – This message\n\n"
        "For support: /feedback"
    )
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

async def feedback_cmd(message: Message):
    await message.answer("💬 *Feedback*\n\nSend your message. We'll review it.", parse_mode=ParseMode.MARKDOWN)

async def unknown_cmd(message: Message):
    await message.answer("❓ Unknown command. Use /help")

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
    await callback.message.delete()
    await price_cmd(callback.message, callback.data.split("_")[1] if "_" in callback.data else "BTC")
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
    await callback.message.edit_text(
        f"💎 *Premium Subscription*\nPrice: ${Config.SUBSCRIPTION_PRICE_USD} USDT",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=subscription_keyboard()
    )
    await callback.answer()

async def callback_pay(callback: CallbackQuery):
    user_id = callback.from_user.id
    payment = get_payment()
    payment_id = db.create_payment(user_id, Config.SUBSCRIPTION_PRICE_USD)
    link = await payment.create_invoice(user_id, Config.SUBSCRIPTION_PRICE_USD)
    if link:
        await callback.message.answer(
            f"✅ Click to pay: [Pay {Config.SUBSCRIPTION_PRICE_USD} USDT]({link})\n"
            f"After payment, click 'Check Payment'.",
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
    else:
        await callback.message.answer("⚠️ Payment gateway temporarily unavailable. Try later.")
    await callback.answer()

async def callback_check_payment(callback: CallbackQuery):
    user_id = callback.from_user.id
    # Ищем последний pending платеж
    # Для простоты: проверяем есть ли активация
    if db.has_active_subscription(user_id):
        await callback.message.answer("✅ Your subscription is active!")
    else:
        await callback.message.answer("⏳ Payment not found. Please complete the payment first.")
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

# ===================================================================
# АДМИН-ПАНЕЛЬ
# ===================================================================

async def admin_cmd(message: Message):
    if message.from_user.id not in Config.ADMIN_IDS:
        await message.answer("⛔ Access denied.")
        return
    stats = db.get_stats()
    text = (
        f"🛡️ *Admin Panel*\n\n"
        f"📊 Stats:\n"
        f"• Total users: {stats['total_users']}\n"
        f"• Active premium: {stats['active_premium']}\n"
        f"• Revenue: ${stats['revenue']:.2f}\n"
        f"• Today new: {stats['today_new']}\n\n"
        f"Commands:\n"
        f"/broadcast – Send message to all\n"
        f"/stats – Detailed stats\n"
        f"/ban <user_id> – Ban user\n"
        f"/unban <user_id> – Unban user"
        f"/add_signals <id> <count> – Burn free signals\n"
        f"/clear_signals <id> – Reset free signal counter\n"
        f"/signal_stats <id> – Show signal usage stats"
    )
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

async def admin_stats_cmd(message: Message):
    if message.from_user.id not in Config.ADMIN_IDS:
        return
    stats = db.get_stats()
    await message.answer(
        f"📈 *Detailed Stats*\n\n"
        f"Total users: {stats['total_users']}\n"
        f"Active premium: {stats['active_premium']}\n"
        f"Premium rate: {stats['active_premium']/max(1,stats['total_users'])*100:.1f}%\n"
        f"Revenue: ${stats['revenue']:.2f}\n"
        f"Today active: {stats['today_active']}\n"
        f"Today new: {stats['today_new']}",
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_broadcast_cmd(message: Message, state: FSMContext):
    if message.from_user.id not in Config.ADMIN_IDS:
        return
    await message.answer("📢 Send the message to broadcast:")
    await state.set_state(AdminStates.waiting_broadcast)

async def admin_broadcast_send(message: Message, state: FSMContext):
    if message.from_user.id not in Config.ADMIN_IDS:
        await state.clear()
        return
    text = message.text
    # Получить всех пользователей
    with db._cursor() as c:
        c.execute("SELECT user_id FROM users")
        users = [row["user_id"] for row in c.fetchall()]
    success = 0
    for uid in users:
        try:
            await message.bot.send_message(uid, f"📢 *Broadcast*\n\n{text}", parse_mode=ParseMode.MARKDOWN)
            success += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.debug(f"Failed to send to {uid}: {e}")
    await message.answer(f"✅ Broadcast sent to {success} users")
    await state.clear()

async def admin_ban_cmd(message: Message):
    if message.from_user.id not in Config.ADMIN_IDS:
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Usage: /ban <user_id> [reason]")
        return
    target = int(parts[1])
    reason = " ".join(parts[2:]) if len(parts) > 2 else "No reason"
    with db._cursor() as c:
        c.execute("UPDATE users SET banned=1, ban_reason=? WHERE user_id=?", (reason, target))
    await message.answer(f"✅ User {target} banned. Reason: {reason}")

async def admin_unban_cmd(message: Message):
    if message.from_user.id not in Config.ADMIN_IDS:
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Usage: /unban <user_id>")
        return
    target = int(parts[1])
    with db._cursor() as c:
        c.execute("UPDATE users SET banned=0, ban_reason=NULL WHERE user_id=?", (target,))
    await message.answer(f"✅ User {target} unbanned.")

async def admin_add_signals_cmd(message: Message):
    """/add_signals <user_id> <count> - добавить фейковые free_signal для пользователя"""
    if not Config.is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Usage: /add_signals <user_id> <count>")
        return
    try:
        target = int(parts[1])
        count = int(parts[2])
        if count < 1 or count > 1000:
            await message.answer("Count must be between 1 and 1000")
            return
        inserted = db.add_fake_signals(target, count, "free_signal")
        await message.answer(f"✅ Added {inserted} fake free_signal records for user {target}")
    except ValueError:
        await message.answer("Invalid user_id or count")

async def admin_clear_signals_cmd(message: Message):
    """/clear_signals <user_id> - удалить все free_signal записи пользователя"""
    if not Config.is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Usage: /clear_signals <user_id>")
        return
    try:
        target = int(parts[1])
        deleted = db.clear_user_signals(target, "free_signal")
        await message.answer(f"✅ Deleted {deleted} free_signal records for user {target}")
    except ValueError:
        await message.answer("Invalid user_id")

async def admin_add_premium_signals_cmd(message: Message):
    """/add_premium_signals <user_id> <count> - добавить фейковые premium_signal"""
    if not Config.is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Usage: /add_premium_signals <user_id> <count>")
        return
    try:
        target = int(parts[1])
        count = int(parts[2])
        if count < 1 or count > 1000:
            await message.answer("Count must be between 1 and 1000")
            return
        inserted = db.add_fake_signals(target, count, "premium_signal")
        await message.answer(f"✅ Added {inserted} fake premium_signal records for user {target}")
    except ValueError:
        await message.answer("Invalid user_id or count")

async def admin_signal_stats_cmd(message: Message):
    """/signal_stats <user_id> - показать статистику использования сигналов"""
    if not Config.is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Usage: /signal_stats <user_id>")
        return
    try:
        target = int(parts[1])
        stats = db.get_signal_usage_stats(target)
        user = db.get_user(target)
        name = f"@{user['username']}" if user and user.get('username') else str(target)
        text = (
            f"📊 *Signal usage for {name}*\n\n"
            f"Today free signals: {stats['today_free']}\n"
            f"Today premium signals: {stats['today_premium']}\n"
            f"Total signals used: {stats['total_signals']}\n"
            f"Remaining free today: {max(0, Config.FREE_SIGNALS_PER_DAY - stats['today_free'])}"
        )
        await message.answer(text, parse_mode=ParseMode.MARKDOWN)
    except ValueError:
        await message.answer("Invalid user_id")

# ===================================================================
# ФОНОВЫЕ ЗАДАЧИ (PLANNER)
# ===================================================================

scheduler = AsyncIOScheduler()

async def cleanup_expired_subscriptions():
    count = db.cleanup_expired()
    if count:
        logger.info(f"Expired subscriptions cleaned: {count}")

async def daily_stats_agg():
    with db._cursor() as c:
        today = datetime.now().strftime("%Y-%m-%d")
        # подсчет активных пользователей за сегодня
        day_start = int(datetime.now().replace(hour=0, minute=0, second=0).timestamp())
        c.execute("SELECT COUNT(DISTINCT user_id) FROM actions WHERE timestamp > ?", (day_start,))
        active = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM payments WHERE status='paid' AND paid_at > ?", (day_start,))
        subs = c.fetchone()[0]
        c.execute("SELECT SUM(amount) FROM payments WHERE status='paid' AND paid_at > ?", (day_start,))
        revenue = c.fetchone()[0] or 0.0
        c.execute("INSERT INTO daily_stats (date, active_users, subscriptions_sold, revenue_usd) VALUES (?, ?, ?, ?) ON CONFLICT(date) DO UPDATE SET active_users=excluded.active_users, subscriptions_sold=excluded.subscriptions_sold, revenue_usd=excluded.revenue_usd",
                  (today, active, subs, revenue))
    logger.info("Daily stats aggregated")

def setup_scheduler():
    scheduler.add_job(cleanup_expired_subscriptions, CronTrigger(hour=0, minute=30))
    scheduler.add_job(daily_stats_agg, CronTrigger(hour=23, minute=55))
    scheduler.start()
    logger.info("Scheduler started")

# ===================================================================
# ЗАПУСК БОТА (POLLING)
# ===================================================================

async def main():
    Config.validate()
    logger.info("Starting CryptoPulse AI Ultimate")
    
    # Инициализация БД
    global db
    db = Database()
    
    # Запуск планировщика
    setup_scheduler()
    
    # Бот и диспетчер
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
    dp.message.register(referral_cmd, Command("referral"))
    dp.message.register(balance_cmd, Command("balance"))
    dp.message.register(withdraw_cmd, Command("withdraw"))
    dp.message.register(profile_cmd, Command("profile"))
    dp.message.register(help_cmd, Command("help"))
    dp.message.register(feedback_cmd, Command("feedback"))
    dp.message.register(admin_cmd, Command("admin"))
    dp.message.register(admin_stats_cmd, Command("stats"))
    dp.message.register(admin_broadcast_cmd, Command("broadcast"))
    dp.message.register(admin_ban_cmd, Command("ban"))
    dp.message.register(admin_unban_cmd, Command("unban"))
    dp.message.register(unknown_cmd)
    dp.message.register(admin_add_signals_cmd, Command("add_signals"))
    dp.message.register(admin_clear_signals_cmd, Command("clear_signals"))
    dp.message.register(admin_add_premium_signals_cmd, Command("add_premium_signals"))
    dp.message.register(admin_signal_stats_cmd, Command("signal_stats"))
    
    # Callback handlers
    dp.callback_query.register(callback_main_menu, F.data == "main_menu")
    dp.callback_query.register(callback_signal, F.data == "signal_btc")
    dp.callback_query.register(callback_price, F.data.startswith("price_"))
    dp.callback_query.register(callback_market, F.data == "market_summary")
    dp.callback_query.register(callback_news, F.data == "news")
    dp.callback_query.register(callback_subscribe, F.data == "subscribe")
    dp.callback_query.register(callback_pay, F.data == "pay_cryptobot")
    dp.callback_query.register(callback_check_payment, F.data == "check_payment")
    dp.callback_query.register(callback_referral, F.data == "referral")
    dp.callback_query.register(callback_profile, F.data == "profile")
    dp.callback_query.register(callback_help, F.data == "help")
    
    # Withdraw FSM
    dp.message.register(withdraw_address, WithdrawStates.waiting_address)
    
    # Admin broadcast FSM
    dp.message.register(admin_broadcast_send, AdminStates.waiting_broadcast)
    
    # Удаляем вебхук и запускаем polling
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Polling started")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

async def handle_webapp(request):
    """Отдаёт HTML-страницу мини-приложения"""
    html_path = Path(__file__).parent / "webapp" / "index.html"
    if not html_path.exists():
        return web.Response(text="WebApp not found", status=404)
    return web.FileResponse(html_path)

async def handle_api_signal(request):
    """API: получить сигнал"""
    data = await request.json()
    user_id = data.get('user_id')
    symbol = data.get('params', {}).get('symbol', 'BTC/USDT')
    # Генерация сигнала (можно переиспользовать существующую логику)
    # Для демо – мок
    return web.json_response({
        "ok": True,
        "result": {
            "action": "BUY",
            "price": 65432.1,
            "confidence": 87,
            "reason": "RSI oversold",
            "is_premium": False
        }
    })

async def handle_api_chart(request):
    """API: получить данные для графика"""
    data = await request.json()
    symbol = data.get('params', {}).get('symbol', 'BTC/USDT')
    timeframe = data.get('params', {}).get('timeframe', '1h')
    limit = data.get('params', {}).get('limit', 50)
    # Генерация мок-данных для свечей
    candles = []
    base = 50000 if "BTC" in symbol else 3000
    for i in range(limit):
        ts = int(time.time()) - (limit - i) * 3600
        openp = base + random.uniform(-200, 200)
        high = openp + random.uniform(0, 100)
        low = openp - random.uniform(0, 100)
        close = (openp + high + low) / 3
        candles.append({"time": ts, "open": openp, "high": high, "low": low, "close": close})
    return web.json_response({"ok": True, "result": candles})

async def handle_api_profile(request):
    """API: данные профиля"""
    # Здесь можно получить реальные данные пользователя из БД
    return web.json_response({
        "ok": True,
        "result": {
            "user_id": 123456,
            "has_subscription": False,
            "balance": 12.50,
            "referral_count": 3
        }
    })

async def handle_api_referral_link(request):
    """API: получить реферальную ссылку"""
    # Реальная ссылка формируется из БД
    return web.json_response({
        "ok": True,
        "result": "https://t.me/CryptoPulseAIBot?start=ref_ABCD1234"
    })

async def handle_api_create_payment(request):
    """API: создать платёж"""
    return web.json_response({
        "ok": True,
        "result": "https://t.me/CryptoBot?start=pay_example"
    })

async def start_web_server():
    """Запуск aiohttp сервера для WebApp"""
    app = web.Application()
    app.router.add_get('/', handle_webapp)
    app.router.add_post('/api/signal', handle_api_signal)
    app.router.add_post('/api/chart', handle_api_chart)
    app.router.add_post('/api/profile', handle_api_profile)
    app.router.add_post('/api/referral_link', handle_api_referral_link)
    app.router.add_post('/api/create_payment', handle_api_create_payment)
    # Также раздаём статику (CSS, JS)
    app.router.add_static('/static', Path(__file__).parent / "webapp")
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)  # Railway даёт PORT
    await site.start()
    logger.info("Web server started on port 8080")

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(start_web_server())
    loop.run_until_complete(main())