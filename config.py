# config.py
# ===================================================================
# CryptoPulse AI Ultimate - Configuration Module
# Version: 3.2.1 (исправлено для Python 3.13)
# ===================================================================

import os
import sys
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

# ===================================================================
# Base configuration class
# ===================================================================

@dataclass
class Config:
    """Main configuration class for CryptoPulse AI bot"""
    
    # -----------------------------------------------------------------
    # Telegram Bot Settings
    # -----------------------------------------------------------------
    API_TOKEN: str = os.getenv("API_TOKEN", "")
    BOT_USERNAME: str = os.getenv("BOT_USERNAME", "CryptoPulseAIBot")
    ADMIN_IDS: List[int] = field(default_factory=list)
    ALLOWED_UPDATES: List[str] = field(default_factory=lambda: ["message", "callback_query", "inline_query"])
    
    # -----------------------------------------------------------------
    # OpenAI / AI Settings
    # -----------------------------------------------------------------
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    OPENAI_TEMPERATURE: float = float(os.getenv("OPENAI_TEMPERATURE", "0.3"))
    OPENAI_MAX_TOKENS: int = int(os.getenv("OPENAI_MAX_TOKENS", "500"))
    OPENAI_TIMEOUT: int = int(os.getenv("OPENAI_TIMEOUT", "30"))
    
    # -----------------------------------------------------------------
    # Crypto Payment Settings
    # -----------------------------------------------------------------
    CRYPTOBOT_TOKEN: str = os.getenv("CRYPTOBOT_TOKEN", "")
    CRYPTOBOT_API_URL: str = "https://pay.crypt.bot/api"
    CRYPTOBOT_PAY_FORM_LINK: str = "https://t.me/CryptoBot?start="
    BINANCE_PAY_API_KEY: str = os.getenv("BINANCE_PAY_API_KEY", "")
    BINANCE_PAY_SECRET_KEY: str = os.getenv("BINANCE_PAY_SECRET_KEY", "")
    
    # -----------------------------------------------------------------
    # Database Settings
    # -----------------------------------------------------------------
    DB_PATH: str = os.getenv("DB_PATH", "crypto_pulse.db")
    DB_BACKUP_INTERVAL_HOURS: int = int(os.getenv("DB_BACKUP_INTERVAL_HOURS", "24"))
    REDIS_URL: Optional[str] = os.getenv("REDIS_URL", None)
    # USE_REDIS будет вычислен в __post_init__
    
    # -----------------------------------------------------------------
    # Market Data Settings
    # -----------------------------------------------------------------
    SUPPORTED_SYMBOLS: List[str] = field(default_factory=lambda: [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
        "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "DOT/USDT", "LINK/USDT",
        "MATIC/USDT", "UNI/USDT", "ATOM/USDT", "LTC/USDT", "ETC/USDT"
    ])
    FIAT_CURRENCIES: List[str] = field(default_factory=lambda: ["USD", "EUR", "RUB", "UAH", "KZT"])
    DEFAULT_FIAT: str = "USD"
    EXCHANGES: List[str] = field(default_factory=lambda: ["binance", "bybit", "okx", "kucoin", "huobi"])
    PRIMARY_EXCHANGE: str = "binance"
    MARKET_DATA_CACHE_SECONDS: int = int(os.getenv("MARKET_DATA_CACHE_SECONDS", "30"))
    WEBSOCKET_ENABLED: bool = os.getenv("WEBSOCKET_ENABLED", "false").lower() == "true"
    
    # -----------------------------------------------------------------
    # News Parsing Settings
    # -----------------------------------------------------------------
    NEWS_SOURCES: List[str] = field(default_factory=lambda: [
        "coindesk", "cointelegraph", "cryptopanic", "decrypt", "theblock", "coindaily"
    ])
    NEWS_CACHE_MINUTES: int = int(os.getenv("NEWS_CACHE_MINUTES", "15"))
    MAX_NEWS_PER_SOURCE: int = int(os.getenv("MAX_NEWS_PER_SOURCE", "20"))
    PROXY_LIST: List[str] = field(default_factory=lambda: [p.strip() for p in os.getenv("PROXY_LIST", "").split(",") if p.strip()])
    # USE_PROXY_FOR_NEWS будет вычислен в __post_init__
    
    # -----------------------------------------------------------------
    # Signal Generation Settings
    # -----------------------------------------------------------------
    SIGNAL_TYPES: List[str] = field(default_factory=lambda: ["BUY", "SELL", "HOLD", "TAKE_PROFIT", "STOP_LOSS"])
    MIN_CONFIDENCE_PERCENT: int = int(os.getenv("MIN_CONFIDENCE_PERCENT", "60"))
    SIGNAL_HISTORY_DAYS: int = int(os.getenv("SIGNAL_HISTORY_DAYS", "30"))
    TECHNICAL_INDICATORS: List[str] = field(default_factory=lambda: ["RSI", "MACD", "EMA_12", "EMA_26", "BOLLINGER_BANDS", "FIBONACCI"])
    USE_ENSEMBLE_AI: bool = os.getenv("USE_ENSEMBLE_AI", "true").lower() == "true"
    
    # -----------------------------------------------------------------
    # Subscription & Payment Settings
    # -----------------------------------------------------------------
    SUBSCRIPTION_PRICE_USD: float = float(os.getenv("SUBSCRIPTION_PRICE_USD", "20.0"))
    SUBSCRIPTION_DAYS: int = int(os.getenv("SUBSCRIPTION_DAYS", "30"))
    TRIAL_DAYS: int = int(os.getenv("TRIAL_DAYS", "3"))
    FREE_SIGNALS_PER_DAY: int = int(os.getenv("FREE_SIGNALS_PER_DAY", "1"))
    SUBSCRIPTION_CURRENCIES: List[str] = field(default_factory=lambda: ["USDT", "BTC", "ETH", "BNB"])
    
    # -----------------------------------------------------------------
    # Referral System
    # -----------------------------------------------------------------
    MAX_REFERRAL_LEVELS: int = int(os.getenv("MAX_REFERRAL_LEVELS", "5"))
    REFERRAL_REWARD_PERCENT: List[float] = field(default_factory=lambda: [50.0, 15.0, 7.0, 3.0, 1.0])
    REFERRAL_MIN_WITHDRAW: float = float(os.getenv("REFERRAL_MIN_WITHDRAW", "10.0"))
    REFERRAL_BONUS_ON_SUBSCRIBE: float = float(os.getenv("REFERRAL_BONUS_ON_SUBSCRIBE", "5.0"))
    
    # -----------------------------------------------------------------
    # Rate Limiting & Anti-Fraud
    # -----------------------------------------------------------------
    SIGNAL_RATE_LIMIT_SECONDS_FREE: int = int(os.getenv("SIGNAL_RATE_LIMIT_SECONDS_FREE", "120"))
    SIGNAL_RATE_LIMIT_SECONDS_PREMIUM: int = int(os.getenv("SIGNAL_RATE_LIMIT_SECONDS_PREMIUM", "10"))
    MAX_COMMANDS_PER_MINUTE: int = int(os.getenv("MAX_COMMANDS_PER_MINUTE", "30"))
    BAN_THRESHOLD_VIOLATIONS: int = int(os.getenv("BAN_THRESHOLD_VIOLATIONS", "10"))
    BAN_DURATION_HOURS: int = int(os.getenv("BAN_DURATION_HOURS", "24"))
    
    # -----------------------------------------------------------------
    # Localization
    # -----------------------------------------------------------------
    DEFAULT_LANGUAGE: str = os.getenv("DEFAULT_LANGUAGE", "en")
    SUPPORTED_LANGUAGES: List[str] = field(default_factory=lambda: ["en", "ru", "es", "de", "fr", "zh", "tr", "ar"])
    TRANSLATIONS_PATH: str = os.getenv("TRANSLATIONS_PATH", "locales/")
    
    # -----------------------------------------------------------------
    # Logging & Monitoring
    # -----------------------------------------------------------------
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "logs/bot.log")
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_MAX_BYTES: int = int(os.getenv("LOG_MAX_BYTES", "10485760"))
    LOG_BACKUP_COUNT: int = int(os.getenv("LOG_BACKUP_COUNT", "5"))
    SENTRY_DSN: Optional[str] = os.getenv("SENTRY_DSN", None)
    
    # -----------------------------------------------------------------
    # Performance & Concurrency
    # -----------------------------------------------------------------
    WORKER_COUNT: int = int(os.getenv("WORKER_COUNT", "4"))
    ASYNC_TASK_TIMEOUT: int = int(os.getenv("ASYNC_TASK_TIMEOUT", "60"))
    MAX_CONCURRENT_REQUESTS: int = int(os.getenv("MAX_CONCURRENT_REQUESTS", "10"))
    
    # -----------------------------------------------------------------
    # Webhook vs Polling
    # -----------------------------------------------------------------
    USE_WEBHOOK: bool = os.getenv("USE_WEBHOOK", "false").lower() == "true"
    WEBHOOK_URL: Optional[str] = os.getenv("WEBHOOK_URL", None)
    WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8443"))
    WEBHOOK_PATH: str = os.getenv("WEBHOOK_PATH", "/webhook")
    
    # -----------------------------------------------------------------
    # Admin / Debug Features
    # -----------------------------------------------------------------
    DEBUG_MODE: bool = os.getenv("DEBUG_MODE", "false").lower() == "true"
    ENABLE_ADMIN_STATS: bool = os.getenv("ENABLE_ADMIN_STATS", "true").lower() == "true"
    ENABLE_BROADCAST: bool = os.getenv("ENABLE_BROADCAST", "true").lower() == "true"
    ENABLE_TEST_COMMANDS: bool = os.getenv("ENABLE_TEST_COMMANDS", "false").lower() == "true"
    
    # -----------------------------------------------------------------
    # External APIs (additional)
    # -----------------------------------------------------------------
    COINGECKO_API_KEY: str = os.getenv("COINGECKO_API_KEY", "")
    CRYPTOCOMPARE_API_KEY: str = os.getenv("CRYPTOCOMPARE_API_KEY", "")
    TWITTER_BEARER_TOKEN: str = os.getenv("TWITTER_BEARER_TOKEN", "")
    
    # -----------------------------------------------------------------
    # Вычисляемые поля (заполняются в __post_init__)
    # -----------------------------------------------------------------
    USE_PROXY_FOR_NEWS: bool = False
    USE_REDIS: bool = False
    
    # -----------------------------------------------------------------
    # Внутренняя валидация и инициализация
    # -----------------------------------------------------------------
    def __post_init__(self):
        # Вычисляем зависимые поля после того, как все переменные окружения загружены
        self.USE_PROXY_FOR_NEWS = len(self.PROXY_LIST) > 0 and self.PROXY_LIST[0] != ""
        self.USE_REDIS = self.REDIS_URL is not None and self.REDIS_URL != ""
        
        # Загружаем ADMIN_IDS из переменной окружения
        self._load_admin_ids()
        # Валидация
        self._validate()
    
    def _validate(self):
        if not self.API_TOKEN:
            logging.critical("API_TOKEN not set. Bot will not start.")
            sys.exit(1)
        if not self.OPENAI_API_KEY and not self.USE_ENSEMBLE_AI:
            logging.warning("OPENAI_API_KEY not set. AI signals will fallback to mock data.")
        if self.SUBSCRIPTION_PRICE_USD < 0:
            raise ValueError("SUBSCRIPTION_PRICE_USD cannot be negative")
        if self.MAX_REFERRAL_LEVELS < 1 or self.MAX_REFERRAL_LEVELS > 10:
            raise ValueError("MAX_REFERRAL_LEVELS must be between 1 and 10")
        # Привести REFERRAL_REWARD_PERCENT к нужной длине
        while len(self.REFERRAL_REWARD_PERCENT) < self.MAX_REFERRAL_LEVELS:
            self.REFERRAL_REWARD_PERCENT.append(0.0)
        self.REFERRAL_REWARD_PERCENT = self.REFERRAL_REWARD_PERCENT[:self.MAX_REFERRAL_LEVELS]
        if self.USE_WEBHOOK and not self.WEBHOOK_URL:
            raise ValueError("WEBHOOK_URL must be set when USE_WEBHOOK is True")
    
    def _load_admin_ids(self):
        admin_ids_env = os.getenv("ADMIN_IDS", "")
        if admin_ids_env:
            try:
                self.ADMIN_IDS = [int(x.strip()) for x in admin_ids_env.split(",") if x.strip().isdigit()]
            except ValueError:
                logging.error("Invalid ADMIN_IDS format. Use comma-separated integers.")
                self.ADMIN_IDS = []
        if not self.ADMIN_IDS and not self.DEBUG_MODE:
            logging.warning("No ADMIN_IDS configured. Admin commands will be disabled.")
    
    def is_admin(self, user_id: int) -> bool:
        return user_id in self.ADMIN_IDS
    
    def get_referral_reward_for_level(self, level: int) -> float:
        if 1 <= level <= self.MAX_REFERRAL_LEVELS:
            return self.REFERRAL_REWARD_PERCENT[level - 1]
        return 0.0
    
    def get_symbols_as_list(self) -> List[str]:
        symbols_env = os.getenv("SUPPORTED_SYMBOLS", "")
        if symbols_env:
            return [s.strip() for s in symbols_env.split(",") if s.strip()]
        return self.SUPPORTED_SYMBOLS
    
    def get_config_dict(self) -> Dict[str, Any]:
        return {
            "bot_username": self.BOT_USERNAME,
            "admins": self.ADMIN_IDS,
            "openai_model": self.OPENAI_MODEL,
            "supported_symbols": self.get_symbols_as_list(),
            "subscription_price_usd": self.SUBSCRIPTION_PRICE_USD,
            "subscription_days": self.SUBSCRIPTION_DAYS,
            "referral_levels": self.MAX_REFERRAL_LEVELS,
            "debug": self.DEBUG_MODE,
            "use_webhook": self.USE_WEBHOOK,
            "redis_enabled": self.USE_REDIS,
        }

# ===================================================================
# Singleton instance
# ===================================================================

_config_instance: Optional[Config] = None

def get_config() -> Config:
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance

def validate_config_or_exit() -> Config:
    cfg = get_config()
    if not cfg.API_TOKEN:
        print("[FATAL] API_TOKEN not set in .env or environment.")
        sys.exit(1)
    print(f"[INFO] Configuration loaded. Bot: {cfg.BOT_USERNAME}, Admins: {cfg.ADMIN_IDS}")
    if cfg.DEBUG_MODE:
        print("[WARNING] DEBUG_MODE is enabled. Do not use in production.")
    if cfg.USE_REDIS:
        print(f"[INFO] Redis integration enabled: {cfg.REDIS_URL}")
    else:
        print("[INFO] Redis disabled. Using SQLite only.")
    return cfg

def reload_config() -> Config:
    global _config_instance
    load_dotenv(override=True)
    _config_instance = Config()
    return _config_instance

if __name__ == "__main__":
    cfg = validate_config_or_exit()
    print("\n--- CONFIGURATION SUMMARY ---")
    for key, value in cfg.get_config_dict().items():
        print(f"{key}: {value}")
    print(f"news_sources: {cfg.NEWS_SOURCES}")
    print(f"proxies: {cfg.PROXY_LIST if cfg.USE_PROXY_FOR_NEWS else 'disabled'}")
    print(f"log_level: {cfg.LOG_LEVEL}")
    print("--- END ---")