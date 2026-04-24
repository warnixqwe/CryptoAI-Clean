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

_news_aggregator = None

def get_news_aggregator():
    global _news_aggregator
    if _news_aggregator is None:
        try:
            from news_parser import NewsAggregator
            _news_aggregator = NewsAggregator()
        except Exception as e:
            logging.error(f"NewsAggregator init failed: {e}")
            _news_aggregator = None
    return _news_aggregator