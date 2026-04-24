import logging
import logging.handlers
import sys
import os
from typing import Optional

# Import configuration (lazy to avoid circular)
from config import get_config

# ===================================================================
# Log formatters
# ===================================================================

class CustomFormatter(logging.Formatter):
    """Custom formatter with color coding for console output"""
    
    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
        'RESET': '\033[0m'
    }
    
    def __init__(self, fmt: str, use_colors: bool = True):
        super().__init__(fmt)
        self.use_colors = use_colors
    
    def format(self, record: logging.LogRecord) -> str:
        if self.use_colors and record.levelname in self.COLORS:
            record.levelname = f"{self.COLORS[record.levelname]}{record.levelname}{self.COLORS['RESET']}"
        return super().format(record)

# ===================================================================
# JSON formatter for structured logging (for file output)
# ===================================================================

class JsonFormatter(logging.Formatter):
    """Format logs as JSON for easier parsing"""
    
    def format(self, record: logging.LogRecord) -> str:
        import json
        import datetime
        
        log_entry = {
            "timestamp": datetime.datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields from 'extra' dict
        if hasattr(record, 'user_id'):
            log_entry['user_id'] = record.user_id
        if hasattr(record, 'request_id'):
            log_entry['request_id'] = record.request_id
        
        return json.dumps(log_entry, ensure_ascii=False)

# ===================================================================
# Logger setup function
# ===================================================================

def setup_logging(
    log_level: Optional[str] = None,
    log_file: Optional[str] = None,
    json_format: bool = False,
    console_output: bool = True,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5
) -> logging.Logger:
    """
    Configure logging for the entire application.
    
    Args:
        log_level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file (optional)
        json_format: Use JSON formatting for file logs
        console_output: Output to console
        max_bytes: Max size of log file before rotation
        backup_count: Number of backup files to keep
    
    Returns:
        Root logger instance
    """
    cfg = get_config()
    
    if log_level is None:
        log_level = cfg.LOG_LEVEL
    if log_file is None:
        log_file = cfg.LOG_FILE
    
    # Convert string level to int
    level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Remove existing handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)
    
    # Create formatters
    console_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    console_formatter = CustomFormatter(console_format, use_colors=True)
    
    file_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    if json_format:
        file_formatter = JsonFormatter()
    else:
        file_formatter = logging.Formatter(file_format)
    
    # Console handler
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
    
    # File handlers
    if log_file:
        # Ensure directory exists
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        # Main log file (rotating)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
        
        # Separate error log file (only ERROR and above)
        error_log_file = log_file.replace('.log', '_error.log')
        error_handler = logging.handlers.RotatingFileHandler(
            error_log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(file_formatter)
        root_logger.addHandler(error_handler)
        
        # Optional: JSON log file for structured logs
        if not json_format:
            json_log_file = log_file.replace('.log', '_json.log')
            json_handler = logging.handlers.RotatingFileHandler(
                json_log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            json_handler.setLevel(logging.INFO)
            json_handler.setFormatter(JsonFormatter())
            root_logger.addHandler(json_handler)
    
    # Suppress noisy third-party loggers
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("ccxt").setLevel(logging.WARNING)
    
    # Optional: Sentry integration (if DSN provided)
    if cfg.SENTRY_DSN:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.logging import LoggingIntegration
            
            sentry_logging = LoggingIntegration(
                level=logging.ERROR,      # Capture errors and above
                event_level=logging.ERROR
            )
            sentry_sdk.init(
                dsn=cfg.SENTRY_DSN,
                integrations=[sentry_logging],
                environment="production" if not cfg.DEBUG_MODE else "development",
                traces_sample_rate=0.1
            )
            root_logger.info("Sentry integration enabled")
        except ImportError:
            root_logger.warning("sentry-sdk not installed, skipping Sentry integration")
        except Exception as e:
            root_logger.error(f"Failed to initialize Sentry: {e}")
    
    # Log startup message
    root_logger.info(f"Logging initialized | Level: {log_level} | File: {log_file}")
    
    return root_logger

# ===================================================================
# Contextual logging helpers (for adding user_id, request_id)
# ===================================================================

class LoggerAdapter(logging.LoggerAdapter):
    """Adapter to inject extra context (user_id, request_id) into logs"""
    
    def process(self, msg, kwargs):
        context = ' '.join(f'{k}={v}' for k, v in self.extra.items() if v is not None)
        return f"[{context}] {msg}" if context else msg, kwargs

def get_logger(name: str, user_id: Optional[int] = None, request_id: Optional[str] = None) -> logging.LoggerAdapter:
    """
    Get a logger with optional context (user_id, request_id)
    
    Usage:
        logger = get_logger(__name__, user_id=123456)
        logger.info("User action")
    """
    logger = logging.getLogger(name)
    if user_id is not None or request_id is not None:
        extra = {'user_id': user_id, 'request_id': request_id}
        return LoggerAdapter(logger, extra)
    return logger  # type: ignore

# ===================================================================
# Rotation cleanup function
# ===================================================================

def cleanup_old_logs(log_dir: str = "logs", days_to_keep: int = 30):
    """Delete log files older than specified days"""
    import time
    if not os.path.exists(log_dir):
        return
    
    now = time.time()
    cutoff = now - (days_to_keep * 86400)
    
    for filename in os.listdir(log_dir):
        filepath = os.path.join(log_dir, filename)
        if os.path.isfile(filepath) and filename.endswith('.log'):
            if os.path.getmtime(filepath) < cutoff:
                try:
                    os.remove(filepath)
                    logging.getLogger(__name__).info(f"Removed old log: {filename}")
                except Exception as e:
                    logging.getLogger(__name__).warning(f"Failed to remove {filename}: {e}")

# ===================================================================
# Function to get logger instance (compatibility with rest of code)
# ===================================================================

def get_logger_instance(name: str) -> logging.Logger:
    """Simple logger getter without context"""
    return logging.getLogger(name)

# ===================================================================
# Test
# ===================================================================
if __name__ == "__main__":
    # Test logging setup
    logger = setup_logging(log_level="DEBUG", console_output=True)
    test_logger = get_logger("test")
    test_logger.info("Test info message")
    test_logger.warning("Test warning")
    test_logger.error("Test error")
    
    # Test with context
    contextual_logger = get_logger("test.user", user_id=123456)
    contextual_logger.info("User clicked button")