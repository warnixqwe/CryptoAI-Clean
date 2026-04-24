import re
import json
import time
import random
import string
import hashlib
import hmac
import base64
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple, Union
from functools import wraps
from decimal import Decimal, ROUND_DOWN

# ===================================================================
# Formatting Functions
# ===================================================================

def format_price(price: float, currency: str = "$") -> str:
    """Format price with appropriate decimal places"""
    if price is None:
        return "N/A"
    if price < 0.000001:
        return f"{currency}{price:.10f}".rstrip('0').rstrip('.')
    elif price < 0.0001:
        return f"{currency}{price:.8f}".rstrip('0').rstrip('.')
    elif price < 0.01:
        return f"{currency}{price:.6f}".rstrip('0').rstrip('.')
    elif price < 1:
        return f"{currency}{price:.4f}".rstrip('0').rstrip('.')
    elif price < 10000:
        return f"{currency}{price:,.2f}"
    else:
        return f"{currency}{price:,.0f}"

def format_large_number(num: float) -> str:
    """Convert large numbers to K/M/B/T format"""
    if num is None:
        return "0"
    if num >= 1_000_000_000_000:
        return f"{num/1_000_000_000_000:.2f}T"
    elif num >= 1_000_000_000:
        return f"{num/1_000_000_000:.2f}B"
    elif num >= 1_000_000:
        return f"{num/1_000_000:.2f}M"
    elif num >= 1_000:
        return f"{num/1_000:.2f}K"
    else:
        return str(round(num, 2))

def format_percentage(value: float, include_sign: bool = True) -> str:
    """Format percentage with sign and 2 decimals"""
    if value is None:
        return "N/A"
    sign = "+" if include_sign and value > 0 else ""
    return f"{sign}{value:.2f}%"

def format_timestamp(ts: int, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Convert Unix timestamp to readable date/time"""
    if not ts:
        return "N/A"
    return datetime.fromtimestamp(ts).strftime(fmt)

def format_duration(seconds: int) -> str:
    """Format seconds into human readable duration"""
    if seconds < 60:
        return f"{seconds} sec"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} h {minutes % 60} min"
    days = hours // 24
    return f"{days} d {hours % 24} h"

def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Truncate text to max length and add suffix"""
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix

def escape_markdown(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2"""
    special_chars = r'_*[]()~`>#+-=|{}.!'
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

def escape_html(text: str) -> str:
    """Escape HTML special characters"""
    if not text:
        return ""
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#39;"))

# ===================================================================
# Validation Functions
# ===================================================================

def is_valid_email(email: str) -> bool:
    """Basic email validation"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def is_valid_phone(phone: str) -> bool:
    """Basic international phone validation (digits only, min 8)"""
    cleaned = re.sub(r'\D', '', phone)
    return len(cleaned) >= 8

def is_valid_crypto_address(address: str, currency: str = "USDT") -> bool:
    """
    Validate cryptocurrency address based on currency.
    Basic checks only, not full blockchain validation.
    """
    if not address:
        return False
    currency = currency.upper()
    if currency == "USDT" or currency == "TRC20":
        # TRC20 addresses start with 'T' and are 34 chars
        return address.startswith('T') and len(address) == 34
    elif currency == "BTC":
        # Starts with 1, 3, or bc1
        return (address.startswith('1') or address.startswith('3') or address.startswith('bc1')) and len(address) >= 26
    elif currency == "ETH" or currency == "ERC20":
        # Starts with 0x and length 42
        return address.startswith('0x') and len(address) == 42
    elif currency == "BNB":
        # BSC addresses same as ETH
        return address.startswith('0x') and len(address) == 42
    elif currency == "SOL":
        # Solana addresses are base58 encoded, usually 32-44 chars
        return 32 <= len(address) <= 44 and address.isalnum()
    else:
        # Generic: not empty, alphanumeric + some special chars
        return bool(re.match(r'^[a-zA-Z0-9]+$', address)) and len(address) >= 8

def is_valid_amount(amount: float, min_amount: float = 0.01, max_amount: float = 100000) -> bool:
    """Check if amount is within valid range"""
    return isinstance(amount, (int, float)) and min_amount <= amount <= max_amount

def is_valid_user_id(user_id: int) -> bool:
    """Check if user_id is plausible (positive integer)"""
    return isinstance(user_id, int) and user_id > 0

# ===================================================================
# Random Generation
# ===================================================================

def generate_random_string(length: int = 8, use_digits: bool = True, use_letters: bool = True) -> str:
    """Generate random alphanumeric string"""
    chars = ""
    if use_letters:
        chars += string.ascii_letters
    if use_digits:
        chars += string.digits
    if not chars:
        chars = string.ascii_letters
    return ''.join(random.choices(chars, k=length))

def generate_promo_code(prefix: str = "", length: int = 8) -> str:
    """Generate a unique promo code"""
    code = generate_random_string(length, use_digits=True, use_letters=True).upper()
    if prefix:
        code = f"{prefix}_{code}"
    return code

def generate_referral_code(user_id: int) -> str:
    """Generate deterministic referral code from user_id"""
    # Encode user_id to base36
    def to_base36(num):
        alphabet = string.digits + string.ascii_lowercase
        result = ""
        while num:
            num, rem = divmod(num, 36)
            result = alphabet[rem] + result
        return result or "0"
    
    base = to_base36(user_id)
    # Add a checksum character
    checksum = sum(ord(c) for c in base) % 36
    checksum_char = string.digits + string.ascii_lowercase[checksum]
    return f"{base}{checksum_char}".upper()

def generate_order_id(prefix: str = "CP") -> str:
    """Generate unique order ID"""
    timestamp = int(time.time() * 1000)
    random_part = random.randint(1000, 9999)
    return f"{prefix}{timestamp}{random_part}"

# ===================================================================
# Cryptographic Utilities
# ===================================================================

def hash_string(text: str, algorithm: str = "sha256") -> str:
    """Hash a string using specified algorithm"""
    h = hashlib.new(algorithm)
    h.update(text.encode('utf-8'))
    return h.hexdigest()

def verify_webhook_signature(payload: str, signature: str, secret: str) -> bool:
    """Verify HMAC-SHA512 signature for webhook authenticity"""
    expected = hmac.new(
        secret.encode('utf-8'),
        payload.encode('utf-8'),
        hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(expected, signature)

def encode_base64(data: Union[str, bytes]) -> str:
    """Base64 encode data"""
    if isinstance(data, str):
        data = data.encode('utf-8')
    return base64.b64encode(data).decode('utf-8')

def decode_base64(encoded: str) -> str:
    """Base64 decode"""
    return base64.b64decode(encoded).decode('utf-8')

# ===================================================================
# Time / Date Helpers
# ===================================================================

def get_current_timestamp() -> int:
    """Return current Unix timestamp"""
    return int(time.time())

def get_timestamp_days_ago(days: int) -> int:
    """Return timestamp for N days ago"""
    return int((datetime.now() - timedelta(days=days)).timestamp())

def get_timestamp_hours_ago(hours: int) -> int:
    """Return timestamp for N hours ago"""
    return int((datetime.now() - timedelta(hours=hours)).timestamp())

def is_within_timeframe(ts: int, hours: int) -> bool:
    """Check if timestamp is within last N hours"""
    return (get_current_timestamp() - ts) <= hours * 3600

def parse_iso_date(date_str: str) -> Optional[int]:
    """Parse ISO datetime string to timestamp"""
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return int(dt.timestamp())
    except:
        return None

# ===================================================================
# Text Processing
# ===================================================================

def extract_hashtags(text: str) -> List[str]:
    """Extract all hashtags from text"""
    return re.findall(r'#(\w+)', text)

def extract_mentions(text: str) -> List[str]:
    """Extract @mentions from text"""
    return re.findall(r'@(\w+)', text)

def extract_urls(text: str) -> List[str]:
    """Extract all URLs from text"""
    return re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[/\w\.-]*', text)

def slugify(text: str) -> str:
    """Convert text to slug (lowercase, hyphenated)"""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text

def remove_emoji(text: str) -> str:
    """Remove emoji characters from string"""
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F"  # emoticons
        u"\U0001F300-\U0001F5FF"  # symbols & pictographs
        u"\U0001F680-\U0001F6FF"  # transport & map symbols
        u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
        u"\U00002702-\U000027B0"
        u"\U000024C2-\U0001F251"
        "]+", flags=re.UNICODE)
    return emoji_pattern.sub(r'', text)

# ===================================================================
# Crypto / Math Utilities
# ===================================================================

def round_down(value: float, decimals: int = 2) -> float:
    """Round down to specified decimal places"""
    factor = 10 ** decimals
    return float(Decimal(str(value)).quantize(Decimal('1.' + '0' * decimals), rounding=ROUND_DOWN))

def calculate_change(old_value: float, new_value: float) -> float:
    """Calculate percentage change between two values"""
    if old_value == 0:
        return 0.0
    return ((new_value - old_value) / old_value) * 100

def moving_average(values: List[float], window: int) -> List[float]:
    """Calculate simple moving average"""
    if len(values) < window:
        return []
    result = []
    for i in range(len(values) - window + 1):
        avg = sum(values[i:i+window]) / window
        result.append(avg)
    return result

def standard_deviation(values: List[float]) -> float:
    """Calculate standard deviation of a list"""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return variance ** 0.5

# ===================================================================
# Geolocation (mock, for potential feature)
# ===================================================================

def get_country_from_ip(ip_address: str) -> Optional[str]:
    """
    Mock geolocation. In production, use ip-api.com or similar.
    Returns country code or None.
    """
    # This is a placeholder - would normally call an API
    # For demo purposes, return None
    return None

# ===================================================================
# Rate Limiting Helper (in-memory fallback)
# ===================================================================

class SimpleRateLimiter:
    """Simple in-memory rate limiter (alternative to database)"""
    
    def __init__(self, default_limit: int = 10, default_window: int = 60):
        self.default_limit = default_limit
        self.default_window = default_window
        self.records = {}
    
    def is_allowed(self, key: str, limit: int = None, window: int = None) -> Tuple[bool, int]:
        """
        Returns (allowed, retry_after_seconds)
        """
        limit = limit or self.default_limit
        window = window or self.default_window
        now = time.time()
        
        if key not in self.records:
            self.records[key] = [now]
            return True, 0
        
        # Clean old records
        self.records[key] = [t for t in self.records[key] if now - t < window]
        
        if len(self.records[key]) >= limit:
            # Calculate retry after
            oldest = min(self.records[key])
            retry_after = int(window - (now - oldest)) + 1
            return False, retry_after
        
        self.records[key].append(now)
        return True, 0
    
    def clear(self, key: str = None):
        if key:
            self.records.pop(key, None)
        else:
            self.records.clear()

# ===================================================================
# Decorators
# ===================================================================

def retry(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0, exceptions: tuple = (Exception,)):
    """Retry decorator for async functions"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_delay = delay
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_attempts - 1:
                        raise
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff
            return None
        return wrapper
    return decorator

def log_execution_time(logger):
    """Decorator to log function execution time"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                elapsed = time.time() - start
                logger.debug(f"{func.__name__} executed in {elapsed:.2f}s")
                return result
            except Exception as e:
                elapsed = time.time() - start
                logger.error(f"{func.__name__} failed after {elapsed:.2f}s: {e}")
                raise
        return wrapper
    return decorator

def require_premium(func):
    """Decorator to check if user has premium subscription (used in handlers)"""
    # Actual implementation would need access to database and user_id
    # This is a placeholder, usually implemented inside handlers
    return func

# ===================================================================
# JSON Helpers
# ===================================================================

def safe_json_loads(json_str: str, default: Any = None) -> Any:
    """Safely parse JSON, return default on error"""
    try:
        return json.loads(json_str)
    except:
        return default

def safe_json_dumps(obj: Any, indent: int = None) -> str:
    """Safely dump JSON, return empty string on error"""
    try:
        return json.dumps(obj, indent=indent)
    except:
        return ""

# ===================================================================
# Environment / Platform Detection
# ===================================================================

def is_running_in_docker() -> bool:
    """Detect if running inside Docker container"""
    return os.path.exists('/.dockerenv')

def get_machine_id() -> str:
    """Get unique machine identifier (for licensing)"""
    import uuid
    try:
        with open('/etc/machine-id', 'r') as f:
            return f.read().strip()
    except:
        return str(uuid.getnode())

# ===================================================================
# Import needed for async decorator
# ===================================================================
import asyncio
import os

# ===================================================================
# Export
# ===================================================================
__all__ = [
    "format_price",
    "format_large_number",
    "format_percentage",
    "format_timestamp",
    "format_duration",
    "truncate_text",
    "escape_markdown",
    "escape_html",
    "is_valid_email",
    "is_valid_phone",
    "is_valid_crypto_address",
    "is_valid_amount",
    "is_valid_user_id",
    "generate_random_string",
    "generate_promo_code",
    "generate_referral_code",
    "generate_order_id",
    "hash_string",
    "verify_webhook_signature",
    "encode_base64",
    "decode_base64",
    "get_current_timestamp",
    "get_timestamp_days_ago",
    "get_timestamp_hours_ago",
    "is_within_timeframe",
    "parse_iso_date",
    "extract_hashtags",
    "extract_mentions",
    "extract_urls",
    "slugify",
    "remove_emoji",
    "round_down",
    "calculate_change",
    "moving_average",
    "standard_deviation",
    "SimpleRateLimiter",
    "retry",
    "log_execution_time",
    "safe_json_loads",
    "safe_json_dumps",
    "is_running_in_docker",
    "get_machine_id"
]