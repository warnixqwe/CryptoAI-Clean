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

# В самом верху market_data.py (после импортов)
import logging
from typing import Optional

_logger = logging.getLogger(__name__)
_market_provider = None

def get_market_provider():
    """Ленивая инициализация MarketDataProvider"""
    global _market_provider
    if _market_provider is None:
        try:
            from market_data import MarketDataProvider
            _market_provider = MarketDataProvider()
        except Exception as e:
            _logger.error(f"MarketDataProvider init failed: {e}")
            _market_provider = None
    return _market_provider

# А в классе MarketDataProvider все методы должны корректно обрабатывать None и возвращать мок-данные.