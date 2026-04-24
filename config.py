import os
import sys
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    # Telegram
    API_TOKEN: str = os.getenv("API_TOKEN", "")
    BOT_USERNAME: str = os.getenv("BOT_USERNAME", "CryptoPulseAIBot")
    ADMIN_IDS: List[int] = field(default_factory=list)
    ALLOWED_UPDATES: List[str] = field(default_factory=lambda: ["message", "callback_query", "inline_query"])
    
    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    OPENAI_TEMPERATURE: float = float(os.getenv("OPENAI_TEMPERATURE", "0.3"))
    OPENAI_MAX_TOKENS: int = int(os.getenv("OPENAI_MAX_TOKENS", "500"))
    OPENAI_TIMEOUT: int = int(os.getenv("OPENAI_TIMEOUT", "30"))
    
    # Payments
    CRYPTOBOT_TOKEN: str = os.getenv("CRYPTOBOT_TOKEN", "")
    CRYPTOBOT_API_URL: str = "https://pay.crypt.bot/api"
    BINANCE_PAY_API_KEY: str = os.getenv("BINANCE_PAY_API_KEY", "")
    BINANCE_PAY_SECRET_KEY: str = os.getenv("BINANCE_PAY_SECRET_KEY", "")
    
    # Database
    DB_PATH: str = os.getenv("DB_PATH", "crypto_pulse.db")
    DB_BACKUP_INTERVAL_HOURS: int = int(os.getenv("DB_BACKUP_INTERVAL_HOURS", "24"))
    REDIS_URL: Optional[str] = os.getenv("REDIS_URL", None)
    
    # Market data
    SUPPORTED_SYMBOLS: List[str] = field(default_factory=lambda: [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
        "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "DOT/USDT", "LINK/USDT",
        "MATIC/USDT", "UNI/USDT", "ATOM/USDT", "LTC/USDT", "ETC/USDT"
    ])
    EXCHANGES: List[str] = field(default_factory=lambda: ["binance", "bybit", "okx", "kucoin", "huobi"])
    PRIMARY_EXCHANGE: str = os.getenv("PRIMARY_EXCHANGE", "okx")   # изменено на okx
    MARKET_DATA_CACHE_SECONDS: int = int(os.getenv("MARKET_DATA_CACHE_SECONDS", "30"))
    WEBSOCKET_ENABLED: bool = os.getenv("WEBSOCKET_ENABLED", "false").lower() == "true"
    
    # News
    NEWS_SOURCES: List[str] = field(default_factory=lambda: ["coindesk", "cointelegraph", "cryptopanic", "decrypt", "theblock", "coindaily"])
    NEWS_CACHE_MINUTES: int = int(os.getenv("NEWS_CACHE_MINUTES", "15"))
    MAX_NEWS_PER_SOURCE: int = int(os.getenv("MAX_NEWS_PER_SOURCE", "20"))
    PROXY_LIST: List[str] = field(default_factory=lambda: [p.strip() for p in os.getenv("PROXY_LIST", "").split(",") if p.strip()])
    
    # Signals
    MIN_CONFIDENCE_PERCENT: int = int(os.getenv("MIN_CONFIDENCE_PERCENT", "60"))
    USE_ENSEMBLE_AI: bool = os.getenv("USE_ENSEMBLE_AI", "true").lower() == "true"
    
    # Subscription
    SUBSCRIPTION_PRICE_USD: float = float(os.getenv("SUBSCRIPTION_PRICE_USD", "20.0"))
    SUBSCRIPTION_DAYS: int = int(os.getenv("SUBSCRIPTION_DAYS", "30"))
    FREE_SIGNALS_PER_DAY: int = int(os.getenv("FREE_SIGNALS_PER_DAY", "1"))
    
    # Referral
    MAX_REFERRAL_LEVELS: int = int(os.getenv("MAX_REFERRAL_LEVELS", "5"))
    REFERRAL_REWARD_PERCENT: List[float] = field(default_factory=lambda: [50.0, 15.0, 7.0, 3.0, 1.0])
    REFERRAL_MIN_WITHDRAW: float = float(os.getenv("REFERRAL_MIN_WITHDRAW", "10.0"))
    REFERRAL_BONUS_ON_SUBSCRIBE: float = float(os.getenv("REFERRAL_BONUS_ON_SUBSCRIBE", "5.0"))
    
    # Rate limits
    SIGNAL_RATE_LIMIT_SECONDS_FREE: int = int(os.getenv("SIGNAL_RATE_LIMIT_SECONDS_FREE", "120"))
    SIGNAL_RATE_LIMIT_SECONDS_PREMIUM: int = int(os.getenv("SIGNAL_RATE_LIMIT_SECONDS_PREMIUM", "10"))
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "logs/bot.log")
    SENTRY_DSN: Optional[str] = os.getenv("SENTRY_DSN", None)
    
    # Webhook
    USE_WEBHOOK: bool = os.getenv("USE_WEBHOOK", "false").lower() == "true"
    WEBHOOK_URL: Optional[str] = os.getenv("WEBHOOK_URL", None)
    WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8443"))
    WEBHOOK_PATH: str = os.getenv("WEBHOOK_PATH", "/webhook")
    
    # Misc
    DEBUG_MODE: bool = os.getenv("DEBUG_MODE", "false").lower() == "true"
    DEFAULT_LANGUAGE: str = os.getenv("DEFAULT_LANGUAGE", "en")
    
    # Вычисляемые поля (будут заполнены в __post_init__)
    USE_PROXY_FOR_NEWS: bool = False
    USE_REDIS: bool = False
    
    def __post_init__(self):
        self.USE_PROXY_FOR_NEWS = len(self.PROXY_LIST) > 0 and self.PROXY_LIST[0] != ""
        self.USE_REDIS = self.REDIS_URL is not None and self.REDIS_URL != ""
        self._load_admin_ids()
        self._validate()
    
    def _validate(self):
        if not self.API_TOKEN:
            logging.critical("API_TOKEN not set")
            sys.exit(1)
        if not self.OPENAI_API_KEY and not self.USE_ENSEMBLE_AI:
            logging.warning("OpenAI API key missing, signals will be limited")
        if self.SUBSCRIPTION_PRICE_USD < 0:
            raise ValueError("Invalid subscription price")
        if self.USE_WEBHOOK and not self.WEBHOOK_URL:
            raise ValueError("WEBHOOK_URL required for webhook mode")
    
    def _load_admin_ids(self):
        ids = os.getenv("ADMIN_IDS", "")
        if ids:
            self.ADMIN_IDS = [int(x.strip()) for x in ids.split(",") if x.strip().isdigit()]
    
    def is_admin(self, user_id: int) -> bool:
        return user_id in self.ADMIN_IDS
    
    def get_referral_reward_for_level(self, level: int) -> float:
        if 1 <= level <= self.MAX_REFERRAL_LEVELS:
            return self.REFERRAL_REWARD_PERCENT[level - 1]
        return 0.0
    
    def get_symbols_as_list(self) -> List[str]:
        sym_env = os.getenv("SUPPORTED_SYMBOLS", "")
        return [s.strip() for s in sym_env.split(",") if s.strip()] if sym_env else self.SUPPORTED_SYMBOLS

_config_instance = None

def get_config() -> Config:
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance

def validate_config_or_exit() -> Config:
    cfg = get_config()
    if not cfg.API_TOKEN:
        print("FATAL: API_TOKEN missing")
        sys.exit(1)
    print(f"✅ Config loaded. Bot: {cfg.BOT_USERNAME}, Admins: {cfg.ADMIN_IDS}")
    if cfg.DEBUG_MODE:
        print("⚠️ DEBUG mode enabled")
    return cfg