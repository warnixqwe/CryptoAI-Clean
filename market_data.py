import logging
from typing import Optional

_logger = logging.getLogger(__name__)
_market_provider = None

# В самом верху market_data.py, перед классом MarketDataProvider
import logging
from typing import Optional

_logger = logging.getLogger(__name__)
_market_provider = None

def get_market_provider():
    global _market_provider
    if _market_provider is None:
        try:
            from market_data import MarketDataProvider
            _market_provider = MarketDataProvider()
        except Exception as e:
            _logger.error(f"MarketDataProvider init failed: {e}")
            _market_provider = None
    return _market_provider

def get_market_provider():
    global _market_provider
    if _market_provider is None:
        try:
            from market_data import MarketDataProvider
            _market_provider = MarketDataProvider()
        __all__ = ["MarketDataProvider", "get_market_provider"]