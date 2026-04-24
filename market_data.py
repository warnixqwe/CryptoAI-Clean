import asyncio
import logging
import time
import json
import random
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from collections import deque
import threading

# Import configuration
from config import get_config

# Exchange libraries with fallbacks
try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False
    logging.warning("CCXT not installed. Install with: pip install ccxt")

try:
    import websockets
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False

cfg = get_config()
logger = logging.getLogger(__name__)

# ===================================================================
# Exchange manager with failover and rate limiting
# ===================================================================

class ExchangeManager:
    """Manage multiple exchange connections with automatic failover"""
    
    def __init__(self):
        self.exchanges = {}
        self.primary_exchange = cfg.PRIMARY_EXCHANGE
        self._init_exchanges()
        self._last_request_time = {}
        self._rate_limit_lock = threading.Lock()
    
    def _init_exchanges(self):
        """Initialize all configured exchanges"""
        if not CCXT_AVAILABLE:
            logger.error("CCXT not available. Market data will be mocked.")
            return
        
        exchange_configs = {
            "binance": {
                "class": ccxt.binance,
                "rate_limit": 1200,  # requests per minute
                "enable_rate_limit": True
            },
            "bybit": {
                "class": ccxt.bybit,
                "rate_limit": 50,
                "enable_rate_limit": True
            },
            "okx": {
                "class": ccxt.okx,
                "rate_limit": 60,
                "enable_rate_limit": True
            },
            "kucoin": {
                "class": ccxt.kucoin,
                "rate_limit": 60,
                "enable_rate_limit": True
            },
            "huobi": {
                "class": ccxt.huobi,
                "rate_limit": 100,
                "enable_rate_limit": True
            }
        }
        
        for name, config in exchange_configs.items():
            if name in cfg.EXCHANGES:
                try:
                    exchange = config["class"]({
                        "enableRateLimit": config.get("enable_rate_limit", True),
                        "rateLimit": 1000 / config.get("rate_limit", 100) * 1000,
                        "timeout": 30000,
                    })
                    self.exchanges[name] = exchange
                    logger.info(f"Initialized exchange: {name}")
                except Exception as e:
                    logger.error(f"Failed to initialize {name}: {e}")
    
    async def fetch_ticker(self, symbol: str, exchange_name: str = None) -> Dict[str, Any]:
        """Fetch ticker from specific exchange or primary with fallback"""
        if not CCXT_AVAILABLE:
            return self._mock_ticker(symbol)
        
        if exchange_name is None:
            exchange_name = self.primary_exchange
        
        # Try primary exchange
        if exchange_name in self.exchanges:
            try:
                ticker = await asyncio.to_thread(
                    self.exchanges[exchange_name].fetch_ticker, symbol
                )
                return {
                    "symbol": symbol,
                    "bid": ticker.get("bid", 0),
                    "ask": ticker.get("ask", 0),
                    "last": ticker.get("last", 0),
                    "high": ticker.get("high", 0),
                    "low": ticker.get("low", 0),
                    "volume": ticker.get("quoteVolume", ticker.get("baseVolume", 0)),
                    "change_24h": ticker.get("percentage", 0),
                    "exchange": exchange_name,
                    "timestamp": int(time.time())
                }
            except Exception as e:
                logger.warning(f"Primary exchange {exchange_name} failed for {symbol}: {e}")
                # Try fallback exchanges
                for alt_name in self.exchanges:
                    if alt_name != exchange_name:
                        try:
                            ticker = await asyncio.to_thread(self.exchanges[alt_name].fetch_ticker, symbol)
                            logger.info(f"Fallback to {alt_name} for {symbol}")
                            result = {
                                "symbol": symbol,
                                "bid": ticker.get("bid", 0),
                                "ask": ticker.get("ask", 0),
                                "last": ticker.get("last", 0),
                                "high": ticker.get("high", 0),
                                "low": ticker.get("low", 0),
                                "volume": ticker.get("quoteVolume", ticker.get("baseVolume", 0)),
                                "change_24h": ticker.get("percentage", 0),
                                "exchange": alt_name,
                                "timestamp": int(time.time())
                            }
                            return result
                        except:
                            continue
        
        # All exchanges failed
        logger.error(f"All exchanges failed for {symbol}, using mock data")
        return self._mock_ticker(symbol)
    
    async def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 100, exchange_name: str = None) -> List[List[float]]:
        """Fetch OHLCV candle data"""
        if not CCXT_AVAILABLE:
            return self._mock_ohlcv(symbol, timeframe, limit)
        
        if exchange_name is None:
            exchange_name = self.primary_exchange
        
        if exchange_name in self.exchanges:
            try:
                ohlcv = await asyncio.to_thread(
                    self.exchanges[exchange_name].fetch_ohlcv, symbol, timeframe, None, limit
                )
                return ohlcv
            except Exception as e:
                logger.warning(f"OHLCV failed on {exchange_name}: {e}")
                for alt_name in self.exchanges:
                    if alt_name != exchange_name:
                        try:
                            ohlcv = await asyncio.to_thread(self.exchanges[alt_name].fetch_ohlcv, symbol, timeframe, None, limit)
                            return ohlcv
                        except:
                            continue
        return self._mock_ohlcv(symbol, timeframe, limit)
    
    async def fetch_order_book(self, symbol: str, limit: int = 100) -> Dict[str, Any]:
        """Fetch order book (bids/asks)"""
        if not CCXT_AVAILABLE:
            return {"bids": [], "asks": []}
        
        for exchange_name in [self.primary_exchange] + [e for e in self.exchanges if e != self.primary_exchange]:
            if exchange_name in self.exchanges:
                try:
                    orderbook = await asyncio.to_thread(self.exchanges[exchange_name].fetch_order_book, symbol, limit)
                    return {
                        "bids": orderbook["bids"][:10],
                        "asks": orderbook["asks"][:10],
                        "exchange": exchange_name,
                        "timestamp": int(time.time())
                    }
                except:
                    continue
        return {"bids": [], "asks": []}
    
    def _mock_ticker(self, symbol: str) -> Dict[str, Any]:
        """Generate mock ticker data when exchanges unavailable"""
        base_price = 50000 if "BTC" in symbol else (3000 if "ETH" in symbol else 100)
        variation = random.uniform(-0.02, 0.02)
        last_price = base_price * (1 + variation)
        return {
            "symbol": symbol,
            "bid": last_price * 0.999,
            "ask": last_price * 1.001,
            "last": last_price,
            "high": last_price * 1.02,
            "low": last_price * 0.98,
            "volume": random.uniform(100, 10000),
            "change_24h": random.uniform(-5, 5),
            "exchange": "mock",
            "timestamp": int(time.time())
        }
    
    def _mock_ohlcv(self, symbol: str, timeframe: str, limit: int) -> List[List[float]]:
        """Generate mock OHLCV data"""
        base_price = 50000 if "BTC" in symbol else (3000 if "ETH" in symbol else 100)
        ohlcv = []
        now = int(time.time())
        timeframe_seconds = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}.get(timeframe, 3600)
        for i in range(limit):
            timestamp = now - (limit - i) * timeframe_seconds
            open_price = base_price * (1 + random.uniform(-0.05, 0.05))
            high = open_price * (1 + random.uniform(0, 0.03))
            low = open_price * (1 - random.uniform(0, 0.03))
            close = (open_price + high + low) / 3 + random.uniform(-0.01, 0.01)
            volume = random.uniform(100, 10000)
            ohlcv.append([timestamp, open_price, high, low, close, volume])
        return ohlcv

# ===================================================================
# Technical indicator calculator (real-time)
# ===================================================================

class TechnicalIndicatorCalculator:
    """Calculate technical indicators from price series"""
    
    @staticmethod
    def moving_average(prices: List[float], period: int) -> float:
        if len(prices) < period:
            return prices[-1] if prices else 0
        return sum(prices[-period:]) / period
    
    @staticmethod
    def exponential_moving_average(prices: List[float], period: int) -> float:
        if len(prices) < period:
            return prices[-1] if prices else 0
        multiplier = 2 / (period + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = (price - ema) * multiplier + ema
        return ema
    
    @staticmethod
    def rsi(prices: List[float], period: int = 14) -> float:
        if len(prices) < period + 1:
            return 50.0
        gains = []
        losses = []
        for i in range(1, period + 1):
            diff = prices[-i] - prices[-i-1]
            if diff > 0:
                gains.append(diff)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(diff))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    @staticmethod
    def macd(prices: List[float]) -> Dict[str, float]:
        if len(prices) < 26:
            return {"macd": 0, "signal": 0, "histogram": 0}
        ema12 = TechnicalIndicatorCalculator.exponential_moving_average(prices, 12)
        ema26 = TechnicalIndicatorCalculator.exponential_moving_average(prices, 26)
        macd_line = ema12 - ema26
        signal = TechnicalIndicatorCalculator.exponential_moving_average([macd_line] * 9, 9) if len(prices) >= 9 else macd_line
        histogram = macd_line - signal
        return {"macd": macd_line, "signal": signal, "histogram": histogram}
    
    @staticmethod
    def bollinger_bands(prices: List[float], period: int = 20, std_dev: float = 2.0) -> Dict[str, float]:
        if len(prices) < period:
            mid = prices[-1] if prices else 0
            return {"upper": mid, "middle": mid, "lower": mid}
        middle = TechnicalIndicatorCalculator.moving_average(prices, period)
        variance = sum((p - middle) ** 2 for p in prices[-period:]) / period
        std = variance ** 0.5
        upper = middle + std_dev * std
        lower = middle - std_dev * std
        return {"upper": upper, "middle": middle, "lower": lower}
    
    @staticmethod
    def atr(prices: List[float], high_low: List[Tuple[float, float]], period: int = 14) -> float:
        """Average True Range requires high/low data"""
        if len(high_low) < 2:
            return 0
        tr_values = []
        for i in range(1, len(high_low)):
            hl = high_low[i][0] - high_low[i][1]
            hc = abs(high_low[i][0] - prices[i-1])
            lc = abs(high_low[i][1] - prices[i-1])
            tr = max(hl, hc, lc)
            tr_values.append(tr)
        if not tr_values:
            return 0
        return sum(tr_values[-period:]) / min(period, len(tr_values))

# ===================================================================
# MarketDataProvider (main facade)
# ===================================================================

class MarketDataProvider:
    """Central market data provider with caching, streaming, and indicators"""
    
    def __init__(self):
        self.exchange_manager = ExchangeManager()
        self.indicators = TechnicalIndicatorCalculator()
        self._price_cache = {}
        self._ohlcv_cache = {}
        self._cache_ttl = cfg.MARKET_DATA_CACHE_SECONDS
        self._websocket_connections = {}
        self._subscribers = {}
        self._streaming_tasks = []
    
    async def get_current_price(self, symbol: str, use_cache: bool = True) -> float:
        """Get current price for symbol"""
        cache_key = f"price_{symbol}"
        if use_cache and cache_key in self._price_cache:
            cached_time, price = self._price_cache[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                return price
        ticker = await self.exchange_manager.fetch_ticker(symbol)
        price = ticker.get("last", 0)
        if price:
            self._price_cache[cache_key] = (time.time(), price)
        return price
    
    async def get_multiple_prices(self, symbols: List[str]) -> Dict[str, float]:
        """Get prices for multiple symbols concurrently"""
        tasks = [self.get_current_price(sym) for sym in symbols]
        results = await asyncio.gather(*tasks)
        return {sym: price for sym, price in zip(symbols, results)}
    
    async def get_historical_prices(self, symbol: str, timeframe: str = "1h", limit: int = 100) -> List[float]:
        """Get historical closing prices for technical analysis"""
        cache_key = f"ohlcv_{symbol}_{timeframe}_{limit}"
        if cache_key in self._ohlcv_cache:
            cached_time, data = self._ohlcv_cache[cache_key]
            if time.time() - cached_time < self._cache_ttl * 2:
                return data
        
        ohlcv = await self.exchange_manager.fetch_ohlcv(symbol, timeframe, limit)
        prices = [candle[4] for candle in ohlcv]  # closing prices
        self._ohlcv_cache[cache_key] = (time.time(), prices)
        return prices
    
    async def get_full_market_data(self, symbol: str) -> Dict[str, Any]:
        """Get comprehensive market data including ticker, orderbook, and indicators"""
        # Fetch ticker
        ticker = await self.exchange_manager.fetch_ticker(symbol)
        # Fetch orderbook for depth
        orderbook = await self.exchange_manager.fetch_order_book(symbol)
        # Fetch historical prices for indicators
        prices_1h = await self.get_historical_prices(symbol, "1h", 100)
        prices_4h = await self.get_historical_prices(symbol, "4h", 100)
        prices_1d = await self.get_historical_prices(symbol, "1d", 100)
        
        # Calculate indicators
        indicators = {
            "rsi_14": self.indicators.rsi(prices_1h, 14),
            "macd": self.indicators.macd(prices_1h),
            "bollinger": self.indicators.bollinger_bands(prices_1h, 20),
            "sma_20": self.indicators.moving_average(prices_1h, 20),
            "sma_50": self.indicators.moving_average(prices_1h, 50) if len(prices_1h) >= 50 else None,
            "ema_12": self.indicators.exponential_moving_average(prices_1h, 12),
            "ema_26": self.indicators.exponential_moving_average(prices_1h, 26),
        }
        
        # 24h change
        change_24h = ticker.get("change_24h", 0)
        
        return {
            "symbol": symbol,
            "timestamp": int(time.time()),
            "current_price": ticker.get("last", 0),
            "bid": ticker.get("bid", 0),
            "ask": ticker.get("ask", 0),
            "high_24h": ticker.get("high", 0),
            "low_24h": ticker.get("low", 0),
            "volume_24h": ticker.get("volume", 0),
            "change_24h_percent": change_24h,
            "orderbook_depth": {
                "best_bid": orderbook.get("bids", [[0]])[0][0] if orderbook.get("bids") else 0,
                "best_ask": orderbook.get("asks", [[0]])[0][0] if orderbook.get("asks") else 0,
                "spread_percent": (orderbook.get("asks", [[0]])[0][0] - orderbook.get("bids", [[0]])[0][0]) / orderbook.get("bids", [[0]])[0][0] * 100 if orderbook.get("bids") and orderbook.get("asks") else 0
            },
            "indicators": indicators,
            "exchange": ticker.get("exchange", "unknown")
        }
    
    async def get_all_symbols_data(self) -> Dict[str, Dict]:
        """Get market data for all configured symbols concurrently"""
        symbols = cfg.get_symbols_as_list()
        tasks = [self.get_full_market_data(sym) for sym in symbols]
        results = await asyncio.gather(*tasks)
        return {res["symbol"]: res for res in results}
    
    # WebSocket streaming (simplified version with polling fallback)
    async def start_price_stream(self, symbols: List[str], callback, interval_seconds: int = 5):
        """Simulate WebSocket streaming via polling (for environments without websockets)"""
        async def poll_loop():
            while True:
                prices = await self.get_multiple_prices(symbols)
                await callback(prices)
                await asyncio.sleep(interval_seconds)
        task = asyncio.create_task(poll_loop())
        self._streaming_tasks.append(task)
        return task
    
    async def stop_all_streams(self):
        """Stop all streaming tasks"""
        for task in self._streaming_tasks:
            task.cancel()
        self._streaming_tasks.clear()
    
    # Pre-computed market summaries for quick responses
    async def get_market_summary(self) -> Dict[str, Any]:
        """Generate quick market summary (top gainers, losers, etc.)"""
        all_data = await self.get_all_symbols_data()
        if not all_data:
            return {}
        
        summaries = []
        for sym, data in all_data.items():
            summaries.append({
                "symbol": sym,
                "price": data["current_price"],
                "change": data["change_24h_percent"],
                "volume": data["volume_24h"]
            })
        
        # Sort by change
        gainers = sorted(summaries, key=lambda x: x["change"], reverse=True)[:5]
        losers = sorted(summaries, key=lambda x: x["change"])[:5]
        
        # Calculate market metrics
        total_volume = sum(s["volume"] for s in summaries)
        avg_change = sum(s["change"] for s in summaries) / len(summaries) if summaries else 0
        
        return {
            "timestamp": int(time.time()),
            "total_symbols": len(summaries),
            "total_volume_24h": total_volume,
            "avg_change_percent": avg_change,
            "top_gainers": gainers,
            "top_losers": losers,
            "market_sentiment": "bullish" if avg_change > 1 else ("bearish" if avg_change < -1 else "neutral")
        }
    
    # Backtesting support: get historical data for a range
    async def get_historical_range(self, symbol: str, start_timestamp: int, end_timestamp: int, timeframe: str = "1h") -> List[Dict]:
        """Get historical OHLCV data between two timestamps"""
        # Determine number of candles needed
        timeframe_seconds = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}.get(timeframe, 3600)
        limit = (end_timestamp - start_timestamp) // timeframe_seconds + 10
        limit = min(limit, 1000)  # Cap at 1000 candles
        
        ohlcv = await self.exchange_manager.fetch_ohlcv(symbol, timeframe, limit)
        # Filter by timestamp range
        filtered = []
        for candle in ohlcv:
            if start_timestamp <= candle[0] <= end_timestamp:
                filtered.append({
                    "timestamp": candle[0],
                    "open": candle[1],
                    "high": candle[2],
                    "low": candle[3],
                    "close": candle[4],
                    "volume": candle[5]
                })
        return filtered
    
    # Diagnostics
    async def check_exchange_health(self) -> Dict[str, bool]:
        """Check if each exchange is responsive"""
        health = {}
        for name in self.exchange_manager.exchanges:
            try:
                ticker = await self.exchange_manager.fetch_ticker("BTC/USDT", name)
                health[name] = ticker.get("last", 0) > 0
            except:
                health[name] = False
        return health

# ===================================================================
# Singleton instance
# ===================================================================

_market_provider: Optional[MarketDataProvider] = None

def get_market_provider() -> MarketDataProvider:
    global _market_provider
    if _market_provider is None:
        _market_provider = MarketDataProvider()
    return _market_provider

# ===================================================================
# Test / demo
# ===================================================================
if __name__ == "__main__":
    async def test():
        provider = get_market_provider()
        # Test single symbol
        data = await provider.get_full_market_data("BTC/USDT")
        print("BTC/USDT Market Data:")
        print(f"Price: ${data['current_price']:,.2f}")
        print(f"24h Change: {data['change_24h_percent']:.2f}%")
        print(f"RSI: {data['indicators']['rsi_14']:.2f}")
        print(f"MACD histogram: {data['indicators']['macd']['histogram']:.4f}")
        
        # Test summary
        summary = await provider.get_market_summary()
        print("\nMarket Summary:")
        print(f"Total Volume: ${summary.get('total_volume_24h', 0):,.0f}")
        print(f"Top Gainers: {[g['symbol'] for g in summary.get('top_gainers', [])]}")
        
        # Test health check
        health = await provider.check_exchange_health()
        print(f"\nExchange Health: {health}")
    
    asyncio.run(test())