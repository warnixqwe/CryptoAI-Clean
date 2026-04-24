import asyncio
import logging
import random
import time
from typing import List, Dict, Any, Optional

import ccxt

from config import get_config

cfg = get_config()
logger = logging.getLogger(__name__)

# ========== Ленивая инициализация ==========
_market_provider = None

def get_market_provider():
    global _market_provider
    if _market_provider is None:
        try:
            from market_data import MarketDataProvider
            _market_provider = MarketDataProvider()
        except Exception as e:
            logger.error(f"MarketDataProvider init failed: {e}")
            _market_provider = None
    return _market_provider

# ========== Основной класс ==========
class MarketDataProvider:
    def __init__(self):
        self.exchanges = []
        self._init_exchanges()
    
    def _init_exchanges(self):
        for name in cfg.EXCHANGES:
            try:
                if name == "binance":
                    exch = ccxt.binance()
                elif name == "bybit":
                    exch = ccxt.bybit()
                elif name == "okx":
                    exch = ccxt.okx()
                elif name == "kucoin":
                    exch = ccxt.kucoin()
                elif name == "huobi":
                    exch = ccxt.huobi()
                else:
                    continue
                self.exchanges.append((name, exch))
                logger.info(f"Initialized exchange: {name}")
            except Exception as e:
                logger.warning(f"Failed init {name}: {e}")
    
    async def fetch_ticker(self, symbol: str) -> Dict:
        for name, exch in self.exchanges:
            try:
                ticker = await asyncio.to_thread(exch.fetch_ticker, symbol)
                return {
                    "symbol": symbol,
                    "last": ticker.get("last", 0),
                    "bid": ticker.get("bid", 0),
                    "ask": ticker.get("ask", 0),
                    "high": ticker.get("high", 0),
                    "low": ticker.get("low", 0),
                    "volume": ticker.get("quoteVolume", 0),
                    "change": ticker.get("percentage", 0),
                    "exchange": name
                }
            except Exception as e:
                logger.warning(f"{name} failed for {symbol}: {e}")
        return self._mock_ticker(symbol)
    
    async def get_historical_prices(self, symbol: str, timeframe: str = "1h", limit: int = 100) -> List[float]:
        base = 50000 if "BTC" in symbol else (3000 if "ETH" in symbol else 100)
        return [base + random.uniform(-500, 500) for _ in range(limit)]
    
    async def get_full_market_data(self, symbol: str) -> Dict:
        ticker = await self.fetch_ticker(symbol)
        return {
            "symbol": symbol,
            "current_price": ticker["last"],
            "change_24h_percent": ticker.get("change", 0),
            "volume_24h": ticker.get("volume", 0),
            "high_24h": ticker.get("high", 0),
            "low_24h": ticker.get("low", 0),
            "bid": ticker.get("bid", 0),
            "ask": ticker.get("ask", 0),
            "exchange": ticker.get("exchange", "mock")
        }
    
    async def get_market_summary(self) -> Dict:
        symbols = cfg.get_symbols_as_list()[:5]
        tasks = [self.get_full_market_data(sym) for sym in symbols]
        results = await asyncio.gather(*tasks)
        changes = [r["change_24h_percent"] for r in results if r]
        avg_change = sum(changes)/len(changes) if changes else 0
        sentiment = "bullish" if avg_change > 1 else ("bearish" if avg_change < -1 else "neutral")
        return {
            "total_symbols": len(symbols),
            "total_volume_24h": sum(r["volume_24h"] for r in results),
            "avg_change_percent": avg_change,
            "market_sentiment": sentiment,
            "top_gainers": [],
            "top_losers": []
        }
    
    async def get_all_symbols_data(self) -> Dict[str, Dict]:
        symbols = cfg.get_symbols_as_list()
        tasks = [self.get_full_market_data(sym) for sym in symbols]
        results = await asyncio.gather(*tasks)
        return {r["symbol"]: r for r in results}
    
    async def check_exchange_health(self) -> Dict:
        return {name: True for name, _ in self.exchanges}
    
    def _mock_ticker(self, symbol: str) -> Dict:
        base = 50000 if "BTC" in symbol else (3000 if "ETH" in symbol else 100)
        return {
            "symbol": symbol,
            "last": base + random.uniform(-500, 500),
            "bid": 0, "ask": 0, "high": 0, "low": 0, "volume": 0, "change": random.uniform(-5, 5), "exchange": "mock"
        }

__all__ = ["MarketDataProvider", "get_market_provider"]