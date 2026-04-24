import asyncio
import aiohttp
import hashlib
import json
import re
import time
import logging
import random
import feedparser
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime, timedelta
from collections import OrderedDict
from bs4 import BeautifulSoup

# Import configuration
from config import get_config

cfg = get_config()
logger = logging.getLogger(__name__)

# ===================================================================
# News source definitions
# ===================================================================

NEWS_SOURCES = {
    "coindesk": {
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "type": "rss",
        "language": "en",
        "weight": 1.0,
        "category": "mainstream"
    },
    "cointelegraph": {
        "url": "https://cointelegraph.com/rss",
        "type": "rss",
        "language": "en",
        "weight": 1.0,
        "category": "mainstream"
    },
    "decrypt": {
        "url": "https://decrypt.co/feed",
        "type": "rss",
        "language": "en",
        "weight": 0.9,
        "category": "mainstream"
    },
    "theblock": {
        "url": "https://www.theblock.co/rss",
        "type": "rss",
        "language": "en",
        "weight": 0.9,
        "category": "research"
    },
    "cryptopanic": {
        "url": "https://cryptopanic.com/news/",
        "type": "html",
        "api_url": "https://cryptopanic.com/api/v1/posts/",
        "requires_api_key": True,
        "weight": 1.0,
        "category": "aggregator"
    },
    "coindaily": {
        "url": "https://cryptodaily.co.uk/feed",
        "type": "rss",
        "language": "en",
        "weight": 0.8,
        "category": "alternative"
    },
    "zycrypto": {
        "url": "https://zycrypto.com/feed/",
        "type": "rss",
        "language": "en",
        "weight": 0.7,
        "category": "alternative"
    },
    "newsbtc": {
        "url": "https://www.newsbtc.com/feed/",
        "type": "rss",
        "language": "en",
        "weight": 0.8,
        "category": "mainstream"
    },
    "cryptoglobe": {
        "url": "https://www.cryptoglobe.com/rss/latest",
        "type": "rss",
        "language": "en",
        "weight": 0.7,
        "category": "alternative"
    },
    "bitcoinist": {
        "url": "https://bitcoinist.com/feed/",
        "type": "rss",
        "language": "en",
        "weight": 0.8,
        "category": "mainstream"
    }
}

# ===================================================================
# News item class
# ===================================================================

class NewsItem:
    """Structured news article"""
    def __init__(self, source: str, title: str, content: str, url: str, published_at: int, 
                 author: str = None, image_url: str = None, categories: List[str] = None):
        self.source = source
        self.title = title
        self.content = content
        self.url = url
        self.published_at = published_at
        self.author = author
        self.image_url = image_url
        self.categories = categories or []
        self.sentiment_score = None
        self.keywords = []
        self.parsed_at = int(time.time())
    
    def to_dict(self) -> Dict:
        return {
            "source": self.source,
            "title": self.title,
            "content": self.content[:500] + "..." if len(self.content) > 500 else self.content,
            "full_content": self.content,
            "url": self.url,
            "published_at": self.published_at,
            "author": self.author,
            "image_url": self.image_url,
            "categories": self.categories,
            "sentiment_score": self.sentiment_score,
            "keywords": self.keywords,
            "parsed_at": self.parsed_at
        }
    
    def get_hash(self) -> str:
        """Unique hash for deduplication"""
        unique_string = f"{self.source}_{self.title}_{self.published_at}"
        return hashlib.md5(unique_string.encode()).hexdigest()

# ===================================================================
# Proxy manager
# ===================================================================

class ProxyManager:
    """Manage proxies for web scraping"""
    
    def __init__(self):
        self.proxies = cfg.PROXY_LIST if cfg.USE_PROXY_FOR_NEWS else []
        self.current_index = 0
        self.failed_proxies = set()
        self.proxy_success_count = {}
    
    def get_next_proxy(self) -> Optional[str]:
        """Get next working proxy in round-robin"""
        if not self.proxies:
            return None
        # Filter out failed proxies
        available = [p for p in self.proxies if p not in self.failed_proxies]
        if not available:
            # Reset failed proxies after some time
            self.failed_proxies.clear()
            available = self.proxies
        if not available:
            return None
        proxy = available[self.current_index % len(available)]
        self.current_index += 1
        return proxy
    
    def report_success(self, proxy: str):
        """Report successful proxy usage"""
        if proxy in self.proxy_success_count:
            self.proxy_success_count[proxy] += 1
        else:
            self.proxy_success_count[proxy] = 1
    
    def report_failure(self, proxy: str):
        """Report proxy failure"""
        self.failed_proxies.add(proxy)
        logger.warning(f"Proxy {proxy} marked as failed")
    
    def get_proxy_dict(self, proxy_url: str) -> Optional[Dict[str, str]]:
        """Convert proxy URL to aiohttp proxy dict"""
        if not proxy_url:
            return None
        # Format: http://user:pass@host:port or http://host:port
        return {"http": proxy_url, "https": proxy_url}

# ===================================================================
# Individual source parsers
# ===================================================================

class RSSParser:
    """Generic RSS feed parser"""
    
    @staticmethod
    async def parse(session: aiohttp.ClientSession, source_name: str, source_config: Dict,
                   proxy_manager: ProxyManager) -> List[NewsItem]:
        """Parse RSS feed and return list of NewsItems"""
        url = source_config.get("url")
        if not url:
            return []
        
        items = []
        proxy = proxy_manager.get_next_proxy()
        proxy_dict = proxy_manager.get_proxy_dict(proxy) if proxy else None
        
        try:
            async with session.get(url, proxy=proxy_dict.get("http") if proxy_dict else None,
                                  timeout=15, ssl=False) as response:
                if response.status != 200:
                    if proxy:
                        proxy_manager.report_failure(proxy)
                    logger.warning(f"RSS feed {source_name} returned {response.status}")
                    return []
                
                text = await response.text()
                # feedparser is synchronous, run in executor
                feed = await asyncio.to_thread(feedparser.parse, text)
                
                if proxy:
                    proxy_manager.report_success(proxy)
                
                for entry in feed.entries[:cfg.MAX_NEWS_PER_SOURCE]:
                    # Extract data
                    title = entry.get("title", "No title")
                    content = entry.get("summary", entry.get("description", ""))
                    # Clean HTML from content
                    content = BeautifulSoup(content, "html.parser").get_text()
                    link = entry.get("link", "")
                    published = entry.get("published_parsed")
                    published_ts = int(time.mktime(published)) if published else int(time.time())
                    author = entry.get("author", None)
                    categories = [tag.term for tag in entry.get("tags", [])] if "tags" in entry else []
                    
                    # Skip if too short
                    if len(title) < 5 or len(content) < 20:
                        continue
                    
                    item = NewsItem(
                        source=source_name,
                        title=title,
                        content=content[:2000],
                        url=link,
                        published_at=published_ts,
                        author=author,
                        categories=categories[:5]
                    )
                    items.append(item)
                
                logger.info(f"Parsed {len(items)} items from {source_name}")
                return items
                
        except asyncio.TimeoutError:
            logger.warning(f"Timeout parsing {source_name}")
            if proxy:
                proxy_manager.report_failure(proxy)
            return []
        except Exception as e:
            logger.error(f"Error parsing {source_name}: {e}")
            if proxy:
                proxy_manager.report_failure(proxy)
            return []

class CryptoPanicParser:
    """Parser for CryptoPanic API (requires API key)"""
    
    @staticmethod
    async def parse(session: aiohttp.ClientSession, proxy_manager: ProxyManager) -> List[NewsItem]:
        """Fetch news from CryptoPanic API"""
        api_key = cfg.CRYPTOPANIC_API_KEY
        if not api_key:
            logger.warning("CryptoPanic API key not configured")
            return []
        
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={api_key}&public=true&filter=hot"
        proxy = proxy_manager.get_next_proxy()
        proxy_dict = proxy_manager.get_proxy_dict(proxy) if proxy else None
        
        try:
            async with session.get(url, proxy=proxy_dict.get("http") if proxy_dict else None,
                                  timeout=15) as response:
                if response.status != 200:
                    if proxy:
                        proxy_manager.report_failure(proxy)
                    return []
                data = await response.json()
                if proxy:
                    proxy_manager.report_success(proxy)
                
                items = []
                for post in data.get("results", [])[:cfg.MAX_NEWS_PER_SOURCE]:
                    title = post.get("title", "")
                    content = post.get("body", post.get("description", ""))
                    url = post.get("url", "")
                    published_ts = int(datetime.strptime(post.get("created_at", "2020-01-01T00:00:00Z"), 
                                                          "%Y-%m-%dT%H:%M:%SZ").timestamp())
                    categories = [cur.get("code", "") for cur in post.get("currencies", [])]
                    
                    item = NewsItem(
                        source="cryptopanic",
                        title=title,
                        content=content[:2000],
                        url=url,
                        published_at=published_ts,
                        categories=categories[:5]
                    )
                    items.append(item)
                
                logger.info(f"Parsed {len(items)} items from CryptoPanic")
                return items
                
        except Exception as e:
            logger.error(f"CryptoPanic error: {e}")
            if proxy:
                proxy_manager.report_failure(proxy)
            return []

class GoogleNewsParser:
    """Parse Google News RSS for crypto topics"""
    
    @staticmethod
    async def parse(session: aiohttp.ClientSession, query: str = "cryptocurrency bitcoin ethereum",
                   proxy_manager: ProxyManager = None) -> List[NewsItem]:
        """Fetch Google News RSS feed for crypto"""
        # Google News RSS URL
        encoded_query = query.replace(" ", "+")
        url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
        
        proxy = proxy_manager.get_next_proxy() if proxy_manager else None
        proxy_dict = proxy_manager.get_proxy_dict(proxy) if proxy and proxy_manager else None
        
        try:
            async with session.get(url, proxy=proxy_dict.get("http") if proxy_dict else None,
                                  timeout=15) as response:
                if response.status != 200:
                    return []
                text = await response.text()
                feed = await asyncio.to_thread(feedparser.parse, text)
                if proxy and proxy_manager:
                    proxy_manager.report_success(proxy)
                
                items = []
                for entry in feed.entries[:15]:
                    title = entry.get("title", "")
                    # Google News content often in summary
                    content = entry.get("summary", entry.get("description", ""))
                    content = BeautifulSoup(content, "html.parser").get_text()
                    link = entry.get("link", "")
                    published = entry.get("published_parsed")
                    published_ts = int(time.mktime(published)) if published else int(time.time())
                    
                    if len(title) > 10 and len(content) > 30:
                        item = NewsItem(
                            source="google_news",
                            title=title,
                            content=content[:1500],
                            url=link,
                            published_at=published_ts
                        )
                        items.append(item)
                
                logger.info(f"Parsed {len(items)} items from Google News")
                return items
                
        except Exception as e:
            logger.error(f"Google News error: {e}")
            if proxy and proxy_manager:
                proxy_manager.report_failure(proxy)
            return []

# ===================================================================
# Keyword extraction and filtering
# ===================================================================

class KeywordExtractor:
    """Extract relevant keywords from news content"""
    
    # Crypto-specific keywords for filtering
    CRYPTO_KEYWORDS = {
        "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "cardano", "ada", "ripple", "xrp",
        "dogecoin", "doge", "binance", "bnb", "polygon", "matic", "avalanche", "avax",
        "crypto", "blockchain", "defi", "nft", "web3", "metaverse", "altcoin", "stablecoin",
        "usdt", "usdc", "mining", "halving", "etf", "sec", "regulation", "bear", "bull"
    }
    
    @staticmethod
    def extract(text: str) -> List[str]:
        """Extract crypto-related keywords from text"""
        text_lower = text.lower()
        found = set()
        for kw in KeywordExtractor.CRYPTO_KEYWORDS:
            if kw in text_lower:
                found.add(kw)
        # Also extract ticker patterns like $BTC, $ETH
        tickers = re.findall(r'\$([A-Z]{2,6})', text)
        found.update([t.lower() for t in tickers])
        return list(found)[:10]
    
    @staticmethod
    def is_relevant(item: NewsItem) -> bool:
        """Check if news item is relevant to crypto"""
        combined = f"{item.title} {item.content}".lower()
        relevant = any(kw in combined for kw in KeywordExtractor.CRYPTO_KEYWORDS)
        return relevant

# ===================================================================
# Sentiment analyzer (simple version, enhanced in ai_analyzer)
# ===================================================================

class SimpleSentimentAnalyzer:
    """Basic sentiment scoring for news"""
    
    POSITIVE_WORDS = {"surge", "rally", "gain", "high", "boom", "bullish", "adoption", "approval", 
                      "partnership", "upgrade", "launch", "profit", "breakthrough", "institutional"}
    NEGATIVE_WORDS = {"crash", "dump", "drop", "low", "bearish", "ban", "fraud", "hack", "scam", 
                      "lawsuit", "fine", "rejection", "sell-off", "volatility", "risk"}
    
    @staticmethod
    def score(text: str) -> float:
        """Return sentiment score from -1 (negative) to +1 (positive)"""
        text_lower = text.lower()
        pos_count = sum(1 for w in SimpleSentimentAnalyzer.POSITIVE_WORDS if w in text_lower)
        neg_count = sum(1 for w in SimpleSentimentAnalyzer.NEGATIVE_WORDS if w in text_lower)
        total = pos_count + neg_count
        if total == 0:
            return 0.0
        return (pos_count - neg_count) / total

# ===================================================================
# Main News Aggregator
# ===================================================================

class NewsAggregator:
    """Main class for fetching and caching news from all sources"""
    
    def __init__(self):
        self.proxy_manager = ProxyManager()
        self.sentiment_analyzer = SimpleSentimentAnalyzer()
        self.keyword_extractor = KeywordExtractor()
        self.cache = OrderedDict()
        self.cache_max_size = 500
        self.cache_ttl = cfg.NEWS_CACHE_MINUTES * 60
        self._last_full_fetch = 0
        self._fetch_lock = asyncio.Lock()
    
    async def fetch_all_sources(self, force_refresh: bool = False) -> List[NewsItem]:
        """Fetch news from all configured sources concurrently"""
        async with self._fetch_lock:
            # Check cache
            if not force_refresh and self._last_full_fetch + self.cache_ttl > time.time():
                cached_items = self._get_cached_items()
                if cached_items:
                    logger.debug("Returning cached news items")
                    return cached_items
            
            # Prepare tasks for each source
            tasks = []
            async with aiohttp.ClientSession() as session:
                for source_name, source_config in NEWS_SOURCES.items():
                    if source_name not in cfg.NEWS_SOURCES:
                        continue
                    
                    source_type = source_config.get("type")
                    if source_type == "rss":
                        tasks.append(RSSParser.parse(session, source_name, source_config, self.proxy_manager))
                    elif source_name == "cryptopanic":
                        tasks.append(CryptoPanicParser.parse(session, self.proxy_manager))
                
                # Add Google News separately
                tasks.append(GoogleNewsParser.parse(session, "cryptocurrency", self.proxy_manager))
                
                # Execute all tasks concurrently
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Collect all news items
                all_items = []
                for result in results:
                    if isinstance(result, list):
                        all_items.extend(result)
                    elif isinstance(result, Exception):
                        logger.error(f"Task failed: {result}")
                
                # Deduplicate by URL or title+source hash
                seen_hashes = set()
                unique_items = []
                for item in all_items:
                    item_hash = item.get_hash()
                    if item_hash not in seen_hashes:
                        seen_hashes.add(item_hash)
                        # Run sentiment and keyword extraction
                        combined_text = f"{item.title} {item.content}"
                        item.sentiment_score = self.sentiment_analyzer.score(combined_text)
                        item.keywords = self.keyword_extractor.extract(combined_text)
                        # Filter relevance
                        if self.keyword_extractor.is_relevant(item):
                            unique_items.append(item)
                
                # Sort by recency
                unique_items.sort(key=lambda x: x.published_at, reverse=True)
                
                # Update cache
                self._update_cache(unique_items)
                self._last_full_fetch = int(time.time())
                
                logger.info(f"Fetched {len(unique_items)} unique news items from all sources")
                return unique_items[:100]  # Limit to 100 most recent
    
    def _get_cached_items(self) -> List[NewsItem]:
        """Retrieve items from cache (simple dict storage)"""
        items = []
        now = time.time()
        for key, item_dict in list(self.cache.items()):
            if now - item_dict.get("parsed_at", 0) < self.cache_ttl:
                # Reconstruct NewsItem
                item = NewsItem(
                    source=item_dict["source"],
                    title=item_dict["title"],
                    content=item_dict["full_content"],
                    url=item_dict["url"],
                    published_at=item_dict["published_at"],
                    author=item_dict.get("author"),
                    categories=item_dict.get("categories", []),
                    image_url=item_dict.get("image_url")
                )
                item.sentiment_score = item_dict.get("sentiment_score")
                item.keywords = item_dict.get("keywords", [])
                item.parsed_at = item_dict.get("parsed_at")
                items.append(item)
            else:
                # Remove expired
                del self.cache[key]
        return items
    
    def _update_cache(self, items: List[NewsItem]):
        """Store items in cache with deduplication"""
        for item in items:
            key = item.get_hash()
            self.cache[key] = item.to_dict()
        # Trim cache to max size
        while len(self.cache) > self.cache_max_size:
            self.cache.popitem(last=False)
    
    async def get_news_by_coin(self, coin_symbol: str, limit: int = 10) -> List[Dict]:
        """Get news filtered by specific coin (BTC, ETH, etc.)"""
        all_items = await self.fetch_all_sources()
        coin_lower = coin_symbol.lower().replace("/usdt", "").replace("usdt", "")
        filtered = []
        for item in all_items:
            combined = f"{item.title} {item.content}".lower()
            if coin_lower in combined or f"${coin_lower.upper()}" in combined:
                filtered.append(item.to_dict())
            if len(filtered) >= limit:
                break
        return filtered
    
    async def get_trending_topics(self, hours: int = 24) -> List[Dict]:
        """Get trending keywords from recent news"""
        all_items = await self.fetch_all_sources()
        cutoff = int(time.time()) - hours * 3600
        recent_items = [i for i in all_items if i.published_at > cutoff]
        
        keyword_count = {}
        for item in recent_items:
            for kw in item.keywords:
                keyword_count[kw] = keyword_count.get(kw, 0) + 1
        
        trending = sorted(keyword_count.items(), key=lambda x: x[1], reverse=True)[:15]
        return [{"keyword": kw, "count": count} for kw, count in trending]
    
    async def get_news_summary(self, limit: int = 20) -> Dict[str, Any]:
        """Get formatted news summary with sentiment aggregates"""
        items = await self.fetch_all_sources()
        items = items[:limit]
        
        positive = sum(1 for i in items if i.sentiment_score > 0.2)
        negative = sum(1 for i in items if i.sentiment_score < -0.2)
        neutral = len(items) - positive - negative
        
        avg_sentiment = sum(i.sentiment_score for i in items) / len(items) if items else 0
        
        return {
            "total_articles": len(items),
            "sentiment": {
                "positive": positive,
                "negative": negative,
                "neutral": neutral,
                "average_score": avg_sentiment
            },
            "top_keywords": await self.get_trending_topics(24),
            "articles": [item.to_dict() for item in items[:10]],
            "last_update": self._last_full_fetch
        }
    
    async def clear_cache(self):
        """Clear news cache"""
        self.cache.clear()
        self._last_full_fetch = 0
        logger.info("News cache cleared")

# ===================================================================
# Singleton instance
# ===================================================================

_news_aggregator: Optional[NewsAggregator] = None

def get_news_aggregator() -> NewsAggregator:
    global _news_aggregator
    if _news_aggregator is None:
        _news_aggregator = NewsAggregator()
    return _news_aggregator

# ===================================================================
# Test / demo
# ===================================================================
if __name__ == "__main__":
    async def test():
        aggregator = get_news_aggregator()
        # Fetch news
        news = await aggregator.fetch_all_sources(force_refresh=True)
        print(f"Fetched {len(news)} total news items")
        if news:
            first = news[0]
            print(f"\nLatest: {first.title}")
            print(f"Source: {first.source}, Sentiment: {first.sentiment_score:.2f}")
            print(f"Keywords: {first.keywords}")
        
        # Get summary
        summary = await aggregator.get_news_summary(10)
        print(f"\nSummary: {summary['sentiment']}")
        print(f"Top keywords: {summary['top_keywords'][:5]}")
        
        # News by coin
        btc_news = await aggregator.get_news_by_coin("BTC", 3)
        print(f"\nBTC-specific news: {len(btc_news)} items")
    
    asyncio.run(test())