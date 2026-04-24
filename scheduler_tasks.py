import asyncio
import logging
import time
import os
import shutil
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

# Local imports
from config import get_config
from database import get_db
from market_data import get_market_provider
from ai_analyzer import get_analyzer
from news_parser import get_news_aggregator
from payments import get_payment_manager, auto_expire_subscriptions, check_expiring_subscriptions

cfg = get_config()
db = get_db()
market = get_market_provider()
analyzer = get_analyzer()
news = get_news_aggregator()
payment_manager = get_payment_manager()

logger = logging.getLogger(__name__)

# ===================================================================
# Scheduler Instance
# ===================================================================

scheduler = AsyncIOScheduler()

# ===================================================================
# Signal Generation Tasks
# ===================================================================

async def broadcast_daily_signals():
    """
    Generate premium signals for all active subscribers and send via bot.
    Called twice per day (10:00 and 16:00 UTC) by scheduler.
    """
    logger.info("Starting daily signal broadcast to premium users")
    
    # Get all users with active subscription
    async with db.get_cursor() as c:
        now = int(time.time())
        c.execute("SELECT user_id FROM users WHERE subscribed = 1 AND subscribe_until > ?", (now,))
        premium_users = [row[0] for row in c.fetchall()]
    
    if not premium_users:
        logger.info("No premium users to send signals")
        return
    
    # Generate signal for top 5 symbols
    symbols = cfg.get_symbols_as_list()[:5]  # Limit to 5 to avoid too many API calls
    signals = {}
    
    for symbol in symbols:
        try:
            # Get market data
            market_data = await market.get_full_market_data(symbol)
            news_items = await news.get_news_by_coin(symbol.split('/')[0], 5)
            price_data = {
                "prices": await market.get_historical_prices(symbol, "1h", 60),
                "volumes": [],
                "price_changes": []
            }
            signal = await analyzer.get_signal(symbol, price_data, news_items)
            signals[symbol] = signal
            await asyncio.sleep(0.5)  # Rate limit between symbols
        except Exception as e:
            logger.error(f"Failed to generate signal for {symbol}: {e}")
    
    # Send signals to each premium user
    from aiogram import Bot
    bot = Bot(token=cfg.API_TOKEN)
    
    success_count = 0
    fail_count = 0
    
    for user_id in premium_users:
        try:
            # Send combined signal message for all symbols
            message_text = "📊 *Daily Crypto Signals* 📊\n\n"
            for symbol, signal in signals.items():
                message_text += (
                    f"{signal['action_emoji']} *{symbol}*: {signal['action']} "
                    f"(Confidence: {signal['confidence']}%)\n"
                    f"Price: ${signal['current_price']:,.2f}\n\n"
                )
            message_text += "Use /signal for detailed analysis.\n\n_Not financial advice_"
            
            await bot.send_message(user_id, message_text, parse_mode="Markdown")
            success_count += 1
            await asyncio.sleep(0.05)  # Avoid flood wait
        except Exception as e:
            logger.warning(f"Failed to send daily signal to {user_id}: {e}")
            fail_count += 1
    
    await bot.session.close()
    logger.info(f"Daily signal broadcast completed. Sent to {success_count}, failed {fail_count}")

async def generate_signal_cache():
    """Pre-generate signals for all symbols and store in cache for quick responses"""
    logger.info("Pre-generating signal cache")
    symbols = cfg.get_symbols_as_list()
    
    for symbol in symbols[:10]:  # Limit to 10 to reduce load
        try:
            market_data = await market.get_full_market_data(symbol)
            news_items = await news.get_news_by_coin(symbol.split('/')[0], 3)
            price_data = {
                "prices": await market.get_historical_prices(symbol, "1h", 60),
                "volumes": [],
                "price_changes": []
            }
            signal = await analyzer.get_signal(symbol, price_data, news_items)
            # Store in database cache
            await db.cache_signal(
                symbol, 
                signal["action"], 
                signal["reasoning"][:500], 
                signal["confidence"], 
                signal["current_price"]
            )
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"Cache generation failed for {symbol}: {e}")
    
    logger.info("Signal cache generation completed")

# ===================================================================
# Subscription Management Tasks
# ===================================================================

async def check_subscription_expiry():
    """Daily task to check and expire subscriptions"""
    await auto_expire_subscriptions()
    logger.info("Subscription expiry check completed")

async def send_subscription_reminders():
    """Send reminders to users whose subscriptions expire in 3 days or less"""
    from aiogram import Bot
    bot = Bot(token=cfg.API_TOKEN)
    await check_expiring_subscriptions(bot)
    await bot.session.close()
    logger.info("Subscription reminders sent")

# ===================================================================
# Backup Tasks
# ===================================================================

async def create_database_backup():
    """Create automated database backup"""
    backup_dir = "backups"
    os.makedirs(backup_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"crypto_pulse_{timestamp}.db"
    backup_path = os.path.join(backup_dir, backup_name)
    
    try:
        shutil.copy2(cfg.DB_PATH, backup_path)
        # Delete old backups older than 14 days
        cutoff = time.time() - 14 * 86400
        for f in os.listdir(backup_dir):
            if f.startswith("crypto_pulse_") and f.endswith(".db"):
                file_path = os.path.join(backup_dir, f)
                if os.path.getctime(file_path) < cutoff:
                    os.remove(file_path)
        logger.info(f"Database backup created: {backup_name}")
    except Exception as e:
        logger.error(f"Backup failed: {e}")

# ===================================================================
# News Cache Refresh
# ===================================================================

async def refresh_news_cache():
    """Periodically fetch latest news to keep cache fresh"""
    logger.info("Refreshing news cache")
    try:
        await news.fetch_all_sources(force_refresh=True)
        logger.info("News cache refreshed successfully")
    except Exception as e:
        logger.error(f"News cache refresh failed: {e}")

# ===================================================================
# Market Data Refresh
# ===================================================================

async def refresh_market_data():
    """Warm up market data cache by fetching all symbols"""
    logger.info("Pre-fetching market data for all symbols")
    try:
        await market.get_all_symbols_data()
        logger.info("Market data cache warmed up")
    except Exception as e:
        logger.error(f"Market data refresh failed: {e}")

# ===================================================================
# Statistics Aggregation
# ===================================================================

async def aggregate_daily_stats():
    """Calculate and store daily statistics for analytics"""
    logger.info("Aggregating daily statistics")
    
    today = datetime.now().strftime("%Y-%m-%d")
    async with db.get_cursor() as c:
        # Count new users registered today
        day_start = int(datetime.now().replace(hour=0, minute=0, second=0).timestamp())
        c.execute("SELECT COUNT(*) FROM users WHERE registered_at > ?", (day_start,))
        new_users = c.fetchone()[0]
        
        # Count new subscriptions today
        c.execute("SELECT COUNT(*) FROM payments WHERE status='paid' AND paid_at > ?", (day_start,))
        new_subs = c.fetchone()[0]
        
        # Calculate revenue today
        c.execute("SELECT SUM(amount) FROM payments WHERE status='paid' AND paid_at > ?", (day_start,))
        revenue = c.fetchone()[0] or 0.0
        
        # Count active users (any action today)
        c.execute("SELECT COUNT(DISTINCT user_id) FROM user_actions WHERE timestamp > ?", (day_start,))
        active_users = c.fetchone()[0]
        
        # Update or insert daily stats
        c.execute('''
            INSERT INTO daily_stats (date, new_users, active_users, subscriptions_sold, revenue_usd)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                new_users = excluded.new_users,
                active_users = excluded.active_users,
                subscriptions_sold = excluded.subscriptions_sold,
                revenue_usd = excluded.revenue_usd
        ''', (today, new_users, active_users, new_subs, revenue))
    
    logger.info(f"Daily stats aggregated: {new_users} new users, ${revenue:.2f} revenue")

# ===================================================================
# Cleanup Tasks
# ===================================================================

async def cleanup_old_logs():
    """Remove logs older than 30 days from database"""
    await db.cleanup_old_logs(days=30)
    logger.info("Old logs cleaned up")

async def cleanup_temp_files():
    """Remove temporary files older than 1 day"""
    temp_dir = "temp"
    if os.path.exists(temp_dir):
        now = time.time()
        for f in os.listdir(temp_dir):
            file_path = os.path.join(temp_dir, f)
            if os.path.isfile(file_path) and now - os.path.getmtime(file_path) > 86400:
                os.remove(file_path)
                logger.debug(f"Removed old temp file: {f}")

async def optimize_database():
    """Run VACUUM to optimize database size"""
    logger.info("Optimizing database")
    try:
        await db.vacuum()
        logger.info("Database VACUUM completed")
    except Exception as e:
        logger.error(f"Database optimization failed: {e}")

# ===================================================================
# Health Check Task
# ===================================================================

async def health_check():
    """Periodic health check to ensure all services are running"""
    issues = []
    
    # Check database
    try:
        async with db.get_cursor() as c:
            c.execute("SELECT 1")
    except Exception as e:
        issues.append(f"Database: {e}")
    
    # Check exchange connectivity
    try:
        health = await market.check_exchange_health()
        if not any(health.values()):
            issues.append("All exchanges unreachable")
    except Exception as e:
        issues.append(f"Market data: {e}")
    
    # Check OpenAI (if configured)
    if cfg.OPENAI_API_KEY:
        try:
            import openai
            openai.api_key = cfg.OPENAI_API_KEY
            # Don't make actual API call, just check key format
            if len(cfg.OPENAI_API_KEY) < 20:
                issues.append("OpenAI API key seems invalid")
        except:
            issues.append("OpenAI module error")
    
    if issues:
        logger.warning(f"Health check found issues: {'; '.join(issues)}")
        # Optionally notify admin
        await notify_admin_about_health_issues(issues)
    else:
        logger.info("Health check passed")

async def notify_admin_about_health_issues(issues: List[str]):
    """Send health issue notification to admins"""
    from aiogram import Bot
    if not cfg.ADMIN_IDS:
        return
    
    bot = Bot(token=cfg.API_TOKEN)
    text = "⚠️ *System Health Alert*\n\n" + "\n".join(f"• {issue}" for issue in issues)
    for admin_id in cfg.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="Markdown")
        except:
            pass
    await bot.session.close()

# ===================================================================
# Payment Polling Task (if no webhook)
# ===================================================================

async def poll_pending_payments():
    """Poll pending payments from external gateways (fallback if no webhook)"""
    async with db.get_cursor() as c:
        c.execute("SELECT payment_id, user_id FROM payments WHERE status='pending' AND created_at > ?", 
                  (int(time.time()) - 3600,))  # Only last hour
        pending = c.fetchall()
    
    for payment_id, user_id in pending:
        status = await payment_manager.check_payment(payment_id)
        if status == "paid":
            await db.activate_subscription(user_id, payment_id=payment_id)
            logger.info(f"Payment {payment_id} auto-verified via polling")
        await asyncio.sleep(0.1)

# ===================================================================
# Scheduler Setup
# ===================================================================

def setup_scheduler():
    """Configure and start all scheduled jobs"""
    
    # Signal broadcasts (daily at 10:00 and 16:00 UTC)
    scheduler.add_job(
        broadcast_daily_signals,
        trigger=CronTrigger(hour=10, minute=0),
        id="morning_signals",
        replace_existing=True
    )
    scheduler.add_job(
        broadcast_daily_signals,
        trigger=CronTrigger(hour=16, minute=0),
        id="afternoon_signals",
        replace_existing=True
    )
    
    # Signal cache pre-generation (every 2 hours)
    scheduler.add_job(
        generate_signal_cache,
        trigger=IntervalTrigger(hours=2),
        id="signal_cache",
        replace_existing=True
    )
    
    # Subscription checks (daily at 00:30)
    scheduler.add_job(
        check_subscription_expiry,
        trigger=CronTrigger(hour=0, minute=30),
        id="expiry_check",
        replace_existing=True
    )
    
    # Subscription reminders (daily at 09:00)
    scheduler.add_job(
        send_subscription_reminders,
        trigger=CronTrigger(hour=9, minute=0),
        id="reminders",
        replace_existing=True
    )
    
    # Database backup (daily at 02:00)
    scheduler.add_job(
        create_database_backup,
        trigger=CronTrigger(hour=2, minute=0),
        id="backup",
        replace_existing=True
    )
    
    # News cache refresh (every 30 minutes)
    scheduler.add_job(
        refresh_news_cache,
        trigger=IntervalTrigger(minutes=30),
        id="news_refresh",
        replace_existing=True
    )
    
    # Market data cache refresh (every 15 minutes)
    scheduler.add_job(
        refresh_market_data,
        trigger=IntervalTrigger(minutes=15),
        id="market_refresh",
        replace_existing=True
    )
    
    # Daily statistics aggregation (at 23:55)
    scheduler.add_job(
        aggregate_daily_stats,
        trigger=CronTrigger(hour=23, minute=55),
        id="daily_stats",
        replace_existing=True
    )
    
    # Cleanup old logs (daily at 03:00)
    scheduler.add_job(
        cleanup_old_logs,
        trigger=CronTrigger(hour=3, minute=0),
        id="log_cleanup",
        replace_existing=True
    )
    
    # Cleanup temp files (every 6 hours)
    scheduler.add_job(
        cleanup_temp_files,
        trigger=IntervalTrigger(hours=6),
        id="temp_cleanup",
        replace_existing=True
    )
    
    # Database optimization (weekly on Sunday at 04:00)
    scheduler.add_job(
        optimize_database,
        trigger=CronTrigger(day_of_week='sun', hour=4, minute=0),
        id="db_optimize",
        replace_existing=True
    )
    
    # Health check (every 30 minutes)
    scheduler.add_job(
        health_check,
        trigger=IntervalTrigger(minutes=30),
        id="health_check",
        replace_existing=True
    )
    
    # Payment polling (every 5 minutes, optional)
    if not cfg.USE_WEBHOOK:
        scheduler.add_job(
            poll_pending_payments,
            trigger=IntervalTrigger(minutes=5),
            id="payment_polling",
            replace_existing=True
        )
    
    logger.info("Scheduler configured with {} jobs".format(len(scheduler.get_jobs())))

def start_scheduler():
    """Start the async scheduler"""
    setup_scheduler()
    scheduler.start()
    logger.info("Scheduler started")

def stop_scheduler():
    """Stop the scheduler gracefully"""
    scheduler.shutdown()
    logger.info("Scheduler stopped")

# ===================================================================
# Manual trigger functions (for admin commands)
# ===================================================================

async def manual_trigger_broadcast():
    """Allow admin to manually trigger daily broadcast"""
    await broadcast_daily_signals()

async def manual_trigger_backup():
    """Allow admin to manually trigger backup"""
    await create_database_backup()

# ===================================================================
# Export
# ===================================================================

__all__ = [
    "scheduler",
    "start_scheduler",
    "stop_scheduler",
    "setup_scheduler",
    "broadcast_daily_signals",
    "generate_signal_cache",
    "check_subscription_expiry",
    "send_subscription_reminders",
    "create_database_backup",
    "refresh_news_cache",
    "refresh_market_data",
    "aggregate_daily_stats",
    "cleanup_old_logs",
    "health_check",
    "poll_pending_payments"
]

# ===================================================================
# Test (if run directly)
# ===================================================================
if __name__ == "__main__":
    import asyncio
    async def test():
        setup_scheduler()
        print("Scheduler jobs:")
        for job in scheduler.get_jobs():
            print(f"  - {job.id}: {job.trigger}")
        scheduler.start()
        await asyncio.sleep(2)
        scheduler.shutdown()
    asyncio.run(test())