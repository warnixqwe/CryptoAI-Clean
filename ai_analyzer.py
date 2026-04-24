import asyncio
import logging
import re
import json
import random
import math
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime, timedelta
from collections import deque

# Import configuration and database
from config import get_config
from database import get_db

# Optional AI imports with fallbacks
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logging.warning("OpenAI library not installed. Install with: pip install openai")

try:
    from transformers import pipeline
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False

cfg = get_config()
logger = logging.getLogger(__name__)

# ===================================================================
# Technical indicators calculator
# ===================================================================

class TechnicalIndicators:
    """Calculate various technical indicators from price data"""
    
    @staticmethod
    def rsi(prices: List[float], period: int = 14) -> float:
        """Relative Strength Index"""
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
        rsi = 100 - (100 / (1 + rs))
        return round(rsi, 2)
    
    @staticmethod
    def macd(prices: List[float]) -> Dict[str, float]:
        """MACD (Moving Average Convergence Divergence)"""
        if len(prices) < 26:
            return {"macd": 0, "signal": 0, "histogram": 0}
        # Simple EMA calculation
        def ema(data, span):
            alpha = 2 / (span + 1)
            ema_val = data[0]
            for val in data[1:]:
                ema_val = alpha * val + (1 - alpha) * ema_val
            return ema_val
        
        ema12 = ema(prices, 12)
        ema26 = ema(prices, 26)
        macd_line = ema12 - ema26
        # Signal line (9-period EMA of MACD)
        signal = ema([macd_line] * 9, 9) if len(prices) >= 9 else macd_line
        histogram = macd_line - signal
        return {"macd": round(macd_line, 4), "signal": round(signal, 4), "histogram": round(histogram, 4)}
    
    @staticmethod
    def moving_average(prices: List[float], period: int) -> float:
        """Simple Moving Average"""
        if len(prices) < period:
            return prices[-1] if prices else 0
        return sum(prices[-period:]) / period
    
    @staticmethod
    def bollinger_bands(prices: List[float], period: int = 20, std_dev: float = 2.0) -> Dict[str, float]:
        """Bollinger Bands (upper, middle, lower)"""
        if len(prices) < period:
            middle = prices[-1] if prices else 0
            return {"upper": middle, "middle": middle, "lower": middle}
        middle = TechnicalIndicators.moving_average(prices, period)
        variance = sum((x - middle) ** 2 for x in prices[-period:]) / period
        std = math.sqrt(variance)
        upper = middle + std_dev * std
        lower = middle - std_dev * std
        return {"upper": round(upper, 2), "middle": round(middle, 2), "lower": round(lower, 2)}
    
    @staticmethod
    def volume_analysis(volumes: List[float], price_changes: List[float]) -> Dict[str, Any]:
        """Analyze volume patterns"""
        if len(volumes) < 5:
            return {"volume_trend": "neutral", "price_volume_correlation": 0}
        avg_vol = sum(volumes[-5:]) / 5
        last_vol = volumes[-1]
        volume_surge = last_vol > avg_vol * 1.5
        # Price-volume correlation
        price_up = price_changes[-1] > 0 if price_changes else False
        if volume_surge and price_up:
            trend = "bullish"
        elif volume_surge and not price_up:
            trend = "bearish"
        else:
            trend = "neutral"
        return {"volume_trend": trend, "volume_surge": volume_surge, "avg_volume": avg_vol, "last_volume": last_vol}

# ===================================================================
# News sentiment analyzer
# ===================================================================

class NewsSentimentAnalyzer:
    """Analyze cryptocurrency news sentiment using multiple methods"""
    
    def __init__(self):
        self.positive_keywords = ["bullish", "surge", "rally", "all-time high", "adoption", "partnership", "approval", "institutional", "upgrade", "launch", "profit", "gain", "breakthrough"]
        self.negative_keywords = ["bearish", "crash", "dump", "rejection", "fraud", "hack", "ban", "restrict", "lawsuit", "fine", "scam", "loss", "plunge", "sell-off"]
    
    async def analyze_text(self, text: str, use_openai: bool = True) -> Dict[str, Any]:
        """Analyze sentiment of news text"""
        text_lower = text.lower()
        
        # Simple keyword scoring
        pos_score = sum(1 for kw in self.positive_keywords if kw in text_lower)
        neg_score = sum(1 for kw in self.negative_keywords if kw in text_lower)
        keyword_sentiment = (pos_score - neg_score) / max(1, pos_score + neg_score)
        
        # Round to -1 to 1 range
        keyword_sentiment = max(-1, min(1, keyword_sentiment))
        
        # Try OpenAI for deeper analysis (if available and requested)
        openai_sentiment = None
        if use_openai and OPENAI_AVAILABLE and cfg.OPENAI_API_KEY:
            try:
                openai.api_key = cfg.OPENAI_API_KEY
                response = openai.ChatCompletion.create(
                    model=cfg.OPENAI_MODEL,
                    messages=[{
                        "role": "system",
                        "content": "You are a crypto news sentiment analyzer. Respond with JSON: {\"sentiment\": \"positive/negative/neutral\", \"score\": -1..1, \"impact\": \"high/medium/low\"}"
                    }, {
                        "role": "user",
                        "content": f"Analyze this crypto news: {text[:1500]}"
                    }],
                    temperature=0.2,
                    max_tokens=150
                )
                result = response.choices[0].message.content
                # Parse JSON from response
                json_match = re.search(r'\{.*\}', result, re.DOTALL)
                if json_match:
                    openai_sentiment = json.loads(json_match.group())
            except Exception as e:
                logger.error(f"OpenAI sentiment failed: {e}")
        
        # Combine or fallback
        if openai_sentiment:
            final_score = (keyword_sentiment + openai_sentiment.get("score", 0)) / 2
            sentiment_label = openai_sentiment.get("sentiment", "neutral")
        else:
            final_score = keyword_sentiment
            if final_score > 0.2:
                sentiment_label = "positive"
            elif final_score < -0.2:
                sentiment_label = "negative"
            else:
                sentiment_label = "neutral"
        
        return {
            "sentiment": sentiment_label,
            "score": final_score,
            "keyword_score": keyword_sentiment,
            "ai_analyzed": openai_sentiment is not None
        }
    
    async def aggregate_news_sentiment(self, news_list: List[Dict]) -> Dict[str, Any]:
        """Aggregate sentiment from multiple news articles"""
        if not news_list:
            return {"sentiment": "neutral", "score": 0, "article_count": 0}
        
        sentiments = []
        for news in news_list:
            content = f"{news.get('title', '')} {news.get('content', '')}"
            analysis = await self.analyze_text(content, use_openai=False)  # Rate limit friendly
            sentiments.append(analysis["score"])
        
        avg_score = sum(sentiments) / len(sentiments)
        if avg_score > 0.2:
            sentiment = "positive"
        elif avg_score < -0.2:
            sentiment = "negative"
        else:
            sentiment = "neutral"
        
        return {
            "sentiment": sentiment,
            "score": avg_score,
            "article_count": len(news_list),
            "std_dev": (sum((x - avg_score) ** 2 for x in sentiments) / len(sentiments)) ** 0.5 if len(sentiments) > 1 else 0
        }

# ===================================================================
# Multi-AI ensemble signal generator
# ===================================================================

class SignalGenerator:
    """Generate trading signals using multiple strategies and AI ensemble"""
    
    def __init__(self):
        self.technicals = TechnicalIndicators()
        self.sentiment = NewsSentimentAnalyzer()
        self.strategy_weights = {
            "technical": 0.35,
            "sentiment": 0.25,
            "openai": 0.30,
            "volume": 0.10
        }
    
    async def generate_signal(self, symbol: str, price_data: Dict, news_data: List[Dict]) -> Dict[str, Any]:
        """
        Generate comprehensive signal.
        price_data should contain: prices (list of floats), volumes (list), maybe timestamps.
        """
        prices = price_data.get("prices", [])
        volumes = price_data.get("volumes", [])
        price_changes = price_data.get("price_changes", [])
        
        if len(prices) < 20:
            logger.warning(f"Insufficient price data for {symbol}, using fallback")
            return self._fallback_signal(symbol)
        
        # 1. Technical analysis
        technical_score, technical_reasons = await self._analyze_technical(prices)
        
        # 2. Volume analysis
        volume_analysis = self.technicals.volume_analysis(volumes, price_changes) if volumes else {}
        volume_score = 0.2 if volume_analysis.get("volume_trend") == "bullish" else (-0.2 if volume_analysis.get("volume_trend") == "bearish" else 0)
        volume_reasons = [f"Volume trend: {volume_analysis.get('volume_trend')}"]
        if volume_analysis.get("volume_surge"):
            volume_reasons.append("Volume surge detected")
        
        # 3. News sentiment
        sentiment_result = await self.sentiment.aggregate_news_sentiment(news_data)
        sentiment_score = sentiment_result["score"]  # -1..1
        sentiment_reasons = [f"News sentiment: {sentiment_result['sentiment']} (score: {sentiment_score:.2f})"]
        
        # 4. OpenAI ensemble (if available)
        openai_score, openai_reason = await self._get_openai_signal(symbol, prices, news_data, sentiment_result)
        
        # Combine scores
        total_score = (
            technical_score * self.strategy_weights["technical"] +
            sentiment_score * self.strategy_weights["sentiment"] +
            openai_score * self.strategy_weights["openai"] +
            volume_score * self.strategy_weights["volume"]
        )
        
        # Determine action and confidence
        confidence = min(99, max(50, int(abs(total_score) * 100) + 30))
        if total_score > 0.15:
            action = "BUY"
            action_emoji = "🟢"
        elif total_score < -0.15:
            action = "SELL"
            action_emoji = "🔴"
        else:
            action = "HOLD"
            action_emoji = "⚪"
        
        # Generate detailed reasoning
        reasoning = self._build_reasoning(action, total_score, technical_reasons, volume_reasons, sentiment_reasons, openai_reason)
        
        # Prepare signal object
        signal = {
            "symbol": symbol,
            "action": action,
            "action_emoji": action_emoji,
            "confidence": confidence,
            "score": total_score,
            "current_price": prices[-1] if prices else 0,
            "timestamp": int(datetime.now().timestamp()),
            "reasoning": reasoning,
            "components": {
                "technical": technical_score,
                "sentiment": sentiment_score,
                "volume": volume_score,
                "openai": openai_score
            },
            "technical_indicators": {
                "rsi": self.technicals.rsi(prices),
                "macd": self.technicals.macd(prices),
                "bollinger": self.technicals.bollinger_bands(prices),
                "sma_20": self.technicals.moving_average(prices, 20),
                "sma_50": self.technicals.moving_average(prices, 50) if len(prices) >= 50 else None
            }
        }
        
        return signal
    
    async def _analyze_technical(self, prices: List[float]) -> Tuple[float, List[str]]:
        """Return technical score (-1..1) and reasons"""
        reasons = []
        rsi_val = self.technicals.rsi(prices)
        macd = self.technicals.macd(prices)
        bb = self.technicals.bollinger_bands(prices)
        current_price = prices[-1]
        
        score = 0.0
        
        # RSI logic
        if rsi_val < 30:
            score += 0.4
            reasons.append(f"RSI oversold ({rsi_val:.1f}) → bullish")
        elif rsi_val > 70:
            score -= 0.4
            reasons.append(f"RSI overbought ({rsi_val:.1f}) → bearish")
        else:
            reasons.append(f"RSI neutral ({rsi_val:.1f})")
        
        # MACD histogram
        if macd["histogram"] > 0:
            score += 0.2
            reasons.append(f"MACD histogram positive ({macd['histogram']:.4f}) → bullish")
        elif macd["histogram"] < 0:
            score -= 0.2
            reasons.append(f"MACD histogram negative ({macd['histogram']:.4f}) → bearish")
        
        # Bollinger Bands
        if current_price < bb["lower"]:
            score += 0.3
            reasons.append(f"Price below lower Bollinger Band → potential reversal up")
        elif current_price > bb["upper"]:
            score -= 0.3
            reasons.append(f"Price above upper Bollinger Band → potential reversal down")
        
        # Moving average crossover (if enough data)
        if len(prices) >= 50:
            sma_20 = self.technicals.moving_average(prices, 20)
            sma_50 = self.technicals.moving_average(prices, 50)
            if sma_20 > sma_50:
                score += 0.2
                reasons.append(f"Golden cross: SMA20 > SMA50 (+{sma_20 - sma_50:.2f})")
            elif sma_20 < sma_50:
                score -= 0.2
                reasons.append(f"Death cross: SMA20 < SMA50 (-{sma_50 - sma_20:.2f})")
        
        # Normalize score to -1..1
        score = max(-1, min(1, score))
        return score, reasons
    
    async def _get_openai_signal(self, symbol: str, prices: List[float], news: List[Dict], sentiment: Dict) -> Tuple[float, str]:
        """Get signal from OpenAI API with fallback to mock"""
        if not OPENAI_AVAILABLE or not cfg.OPENAI_API_KEY:
            # Mock signal based on random + price trend
            trend = (prices[-1] - prices[-10]) / prices[-10] if len(prices) >= 10 else 0
            mock_score = max(-0.8, min(0.8, trend * 5 + random.uniform(-0.2, 0.2)))
            return mock_score, f"OpenAI unavailable, using trend extrapolation ({(trend*100):.2f}% 10d)"
        
        try:
            openai.api_key = cfg.OPENAI_API_KEY
            # Prepare context
            recent_prices = prices[-20:]
            price_change = (recent_prices[-1] - recent_prices[0]) / recent_prices[0] * 100
            rsi = self.technicals.rsi(prices)
            news_summary = news[0].get("title", "No recent news") if news else "No relevant news"
            
            prompt = f"""As a crypto trading analyst, analyze {symbol}:
            - Current price: {prices[-1]}
            - 20-period price change: {price_change:.2f}%
            - RSI: {rsi:.2f}
            - News sentiment: {sentiment.get('sentiment')} (score: {sentiment.get('score', 0):.2f})
            - Recent news: {news_summary}
            
            Based on this, output a signal score from -1 (strong sell) to +1 (strong buy) and a brief reason.
            Format: SCORE: [number] REASON: [your reason]
            """
            
            response = openai.ChatCompletion.create(
                model=cfg.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "You are a quantitative crypto analyst. Provide only the score and reason as requested."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.4,
                max_tokens=150
            )
            result = response.choices[0].message.content
            # Parse
            score_match = re.search(r'SCORE:\s*([+-]?\d*\.?\d+)', result, re.IGNORECASE)
            if score_match:
                score = float(score_match.group(1))
                score = max(-1, min(1, score))
            else:
                score = 0.0
            reason_match = re.search(r'REASON:\s*(.+)', result, re.IGNORECASE)
            reason = reason_match.group(1).strip() if reason_match else "OpenAI analysis inconclusive"
            return score, reason
        except Exception as e:
            logger.error(f"OpenAI signal generation failed: {e}")
            return 0.0, "OpenAI error, using neutral bias"
    
    def _build_reasoning(self, action: str, total_score: float, tech_reasons: List[str], vol_reasons: List[str], sent_reasons: List[str], ai_reason: str) -> str:
        """Construct human-readable reasoning string"""
        parts = []
        parts.append(f"📊 *Overall Signal Strength*: {action} (score: {total_score:.2f})\n")
        parts.append("🔧 *Technical Analysis*:\n• " + "\n• ".join(tech_reasons[:3]))
        if vol_reasons:
            parts.append("\n📈 *Volume Analysis*:\n• " + "\n• ".join(vol_reasons[:2]))
        parts.append("\n📰 *News Sentiment*:\n• " + "\n• ".join(sent_reasons[:2]))
        if ai_reason:
            parts.append(f"\n🤖 *AI Ensemble*:\n• {ai_reason}")
        return "\n".join(parts)
    
    def _fallback_signal(self, symbol: str) -> Dict[str, Any]:
        """Fallback when data insufficient"""
        return {
            "symbol": symbol,
            "action": "HOLD",
            "action_emoji": "⚪",
            "confidence": 50,
            "score": 0,
            "current_price": 0,
            "timestamp": int(datetime.now().timestamp()),
            "reasoning": "Insufficient data for analysis. Using HOLD as default.",
            "components": {"technical": 0, "sentiment": 0, "volume": 0, "openai": 0}
        }

# ===================================================================
# Main AI Analyzer facade
# ===================================================================

class AIAnalyzer:
    """Facade for all AI analysis operations"""
    
    def __init__(self):
        self.generator = SignalGenerator()
        self.cache = {}  # simple memory cache
        self.cache_expiry = 120  # seconds
    
    async def get_signal(self, symbol: str, price_data: Dict, news_data: List[Dict], force_refresh: bool = False) -> Dict[str, Any]:
        """Get signal with caching"""
        cache_key = f"{symbol}_{int(datetime.now().timestamp() / self.cache_expiry)}"
        if not force_refresh and cache_key in self.cache:
            return self.cache[cache_key]
        
        signal = await self.generator.generate_signal(symbol, price_data, news_data)
        self.cache[cache_key] = signal
        # Limit cache size
        if len(self.cache) > 100:
            self.cache.pop(next(iter(self.cache)))
        return signal
    
    async def batch_signals(self, symbols: List[str], market_data_dict: Dict[str, Dict], news_dict: Dict[str, List[Dict]]) -> Dict[str, Dict]:
        """Generate signals for multiple symbols concurrently"""
        tasks = []
        for sym in symbols:
            price_data = market_data_dict.get(sym, {})
            news = news_dict.get(sym, [])
            tasks.append(self.get_signal(sym, price_data, news))
        results = await asyncio.gather(*tasks)
        return {sym: result for sym, result in zip(symbols, results)}
    
    async def get_market_insight(self) -> str:
        """Generate overall market insight using AI"""
        if OPENAI_AVAILABLE and cfg.OPENAI_API_KEY:
            try:
                openai.api_key = cfg.OPENAI_API_KEY
                response = openai.ChatCompletion.create(
                    model=cfg.OPENAI_MODEL,
                    messages=[{"role": "user", "content": "Give a short (1-2 sentences) insight on current crypto market sentiment and key factor."}],
                    temperature=0.7,
                    max_tokens=100
                )
                return response.choices[0].message.content
            except:
                return "Market showing mixed signals; watch BTC dominance."
        return "AI insights unavailable. Please check configuration."

# ===================================================================
# Singleton instance
# ===================================================================

_analyzer_instance: Optional[AIAnalyzer] = None

def get_analyzer() -> AIAnalyzer:
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = AIAnalyzer()
    return _analyzer_instance

# ===================================================================
# Test / demo
# ===================================================================
if __name__ == "__main__":
    async def test():
        analyzer = get_analyzer()
        # Mock data
        prices = [50000 + i * 100 + random.randint(-200, 200) for i in range(60)]
        volumes = [random.randint(100, 1000) for _ in range(60)]
        price_data = {"prices": prices, "volumes": volumes, "price_changes": [0.01] * 60}
        news = [{"title": "Bitcoin ETF approved by SEC, institutional inflows expected", "content": "The SEC has approved several spot Bitcoin ETFs, leading to massive buying pressure."}]
        signal = await analyzer.get_signal("BTC/USDT", price_data, news)
        print(json.dumps(signal, indent=2, default=str))
    
    asyncio.run(test())