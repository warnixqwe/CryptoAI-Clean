import asyncio
import logging
import random
import time
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# ========== Ленивая инициализация ==========
_news_aggregator = None

def get_news_aggregator():
    global _news_aggregator
    if _news_aggregator is None:
        try:
            from news_parser import NewsAggregator
            _news_aggregator = NewsAggregator()
        except Exception as e:
            logger.error(f"NewsAggregator init failed: {e}")
            _news_aggregator = None
    return _news_aggregator

# ========== Классы ==========
class NewsItem:
    def __init__(self, source, title, content, url, published_at, author=None, categories=None):
        self.source = source
        self.title = title
        self.content = content
        self.url = url
        self.published_at = published_at
        self.author = author
        self.categories = categories or []
        self.sentiment_score = random.uniform(-0.5, 0.5)
        self.keywords = []

class NewsAggregator:
    def __init__(self):
        self.cache = []
        self.last_fetch = 0
    
    async def fetch_all_sources(self, force_refresh=False) -> List[NewsItem]:
        if not force_refresh and self.cache and time.time() - self.last_fetch < 300:
            return self.cache
        items = []
        templates = [
            ("Bitcoin surges to new high", "BTC reached $70k as institutional inflow continues"),
            ("Ethereum upgrade successful", "ETH gas fees drop after successful upgrade"),
            ("Solana faces network congestion", "Solana outage resolved, validators update"),
            ("Dogecoin rallies on Elon Musk tweet", "DOGE up 20% after CEO endorsement"),
            ("Crypto regulations update", "New framework proposed in EU")
        ]
        for i, (title, content) in enumerate(templates):
            items.append(NewsItem(
                source="mock",
                title=title,
                content=content,
                url="https://example.com/news/" + str(i),
                published_at=int(time.time()) - i*3600
            ))
        self.cache = items
        self.last_fetch = int(time.time())
        return items
    
    async def get_news_summary(self, limit=10) -> Dict:
        items = await self.fetch_all_sources()
        sentiments = [i.sentiment_score for i in items[:limit]]
        pos = sum(1 for s in sentiments if s > 0.2)
        neg = sum(1 for s in sentiments if s < -0.2)
        neut = len(sentiments) - pos - neg
        avg = sum(sentiments)/len(sentiments) if sentiments else 0
        return {
            "total_articles": len(items),
            "sentiment": {"positive": pos, "negative": neg, "neutral": neut, "average_score": avg},
            "articles": [{"title": i.title, "url": i.url, "sentiment_score": i.sentiment_score} for i in items[:limit]]
        }
    
    async def get_news_by_coin(self, coin: str, limit=5) -> List[Dict]:
        items = await self.fetch_all_sources()
        filtered = [i for i in items if coin.lower() in i.title.lower()]
        return [{"title": i.title, "url": i.url, "source": i.source, "published_at": i.published_at} for i in filtered[:limit]]
    
    async def get_trending_topics(self, hours=24) -> List[Dict]:
        return [{"keyword": "Bitcoin", "count": 10}, {"keyword": "Ethereum", "count": 8}, {"keyword": "SOL", "count": 5}]

__all__ = ["NewsAggregator", "get_news_aggregator"]