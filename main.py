import asyncio
import logging
import signal
import sys
import os
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, BotCommandScopeDefault
from aiogram.fsm.storage.memory import MemoryStorage

# Load configuration and initialize modules
from config import get_config, validate_config_or_exit
from logger import setup_logging, get_logger
from database import get_db
from market_data import get_market_provider
from ai_analyzer import get_analyzer
from news_parser import get_news_aggregator
from payments import get_payment_manager
from scheduler_tasks import start_scheduler, stop_scheduler
import bot_handlers
import admin_panel

# ===================================================================
# Global instances
# ===================================================================

cfg = None
bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None
logger = None

# ===================================================================
# Bot command menu setup
# ===================================================================

async def set_bot_commands(bot_instance: Bot):
    """Set Telegram bot command menu"""
    commands = [
        BotCommand(command="start", description="Start the bot / register"),
        BotCommand(command="menu", description="Main menu"),
        BotCommand(command="signal", description="Get BTC signal"),
        BotCommand(command="signal_custom", description="Get signal for custom pair"),
        BotCommand(command="price", description="Get current price"),
        BotCommand(command="market", description="Market summary"),
        BotCommand(command="news", description="Latest crypto news"),
        BotCommand(command="news_coin", description="News for specific coin"),
        BotCommand(command="subscribe", description="Buy premium subscription"),
        BotCommand(command="referral", description="Invite friends and earn"),
        BotCommand(command="balance", description="Check bonus balance"),
        BotCommand(command="profile", description="Your profile"),
        BotCommand(command="support", description="Contact support"),
        BotCommand(command="feedback", description="Send feedback"),
        BotCommand(command="help", description="Help menu"),
        BotCommand(command="cancel", description="Cancel current operation"),
    ]
    # Add admin commands if user is admin (they are still shown but only work for admins)
    commands.append(BotCommand(command="admin", description="Admin panel"))
    commands.append(BotCommand(command="stats", description="Bot statistics"))
    commands.append(BotCommand(command="send", description="Send message to user"))
    
    await bot_instance.set_my_commands(commands, scope=BotCommandScopeDefault())
    logger.info("Bot commands set")

# ===================================================================
# Startup and shutdown events
# ===================================================================

async def on_startup(bot_instance: Bot):
    """Actions to perform when bot starts"""
    logger.info("Bot is starting up...")
    
    # Initialize database connections (already done in get_db)
    db = get_db()
    logger.info("Database ready")
    
    # Warm up caches
    try:
        market = get_market_provider()
        await market.get_market_summary()
        logger.info("Market cache warmed up")
    except Exception as e:
        logger.warning(f"Market warm-up failed: {e}")
    
    try:
        news = get_news_aggregator()
        await news.get_news_summary(5)
        logger.info("News cache warmed up")
    except Exception as e:
        logger.warning(f"News warm-up failed: {e}")
    
    # Start background scheduler
    start_scheduler()
    logger.info("Background scheduler started")
    
    # Set bot commands
    await set_bot_commands(bot_instance)
    
    # Log startup completion
    logger.info("Bot started successfully")
    
    # Notify admins
    for admin_id in cfg.ADMIN_IDS:
        try:
            await bot_instance.send_message(
                admin_id,
                f"🤖 *CryptoPulse AI Bot Started*\n"
                f"Time: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Mode: {'Webhook' if cfg.USE_WEBHOOK else 'Polling'}",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin_id}: {e}")

async def on_shutdown(bot_instance: Bot):
    """Actions to perform when bot stops"""
    logger.info("Bot is shutting down...")
    
    # Stop background scheduler
    stop_scheduler()
    logger.info("Scheduler stopped")
    
    # Close database connections (if any)
    # Database module uses context managers, no explicit close needed
    
    # Close bot session
    await bot_instance.session.close()
    logger.info("Bot session closed")
    
    # Notify admins
    for admin_id in cfg.ADMIN_IDS:
        try:
            await bot_instance.send_message(
                admin_id,
                f"🛑 *CryptoPulse AI Bot Stopped*\n"
                f"Time: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                parse_mode="Markdown"
            )
        except:
            pass
    
    logger.info("Shutdown complete")

# ===================================================================
# Webhook setup (if configured)
# ===================================================================

async def setup_webhook(bot_instance: Bot, webhook_url: str, webhook_path: str):
    """Configure Telegram webhook"""
    await bot_instance.delete_webhook(drop_pending_updates=True)
    await bot_instance.set_webhook(
        url=f"{webhook_url}{webhook_path}",
        allowed_updates=cfg.ALLOWED_UPDATES,
        drop_pending_updates=True
    )
    logger.info(f"Webhook set to {webhook_url}{webhook_path}")
    
    # Start aiohttp webhook server for payments (separate)
    from payments import start_webhook_server
    payment_runner = await start_webhook_server(bot_instance, "/cryptopulse_webhook", cfg.WEBHOOK_PORT)
    logger.info(f"Payment webhook server started on port {cfg.WEBHOOK_PORT}")
    return payment_runner

# ===================================================================
# Polling mode runner
# ===================================================================

async def run_polling():
    """Run bot in polling mode (default)"""
    logger.info("Starting bot in polling mode")
    
    # Create bot and dispatcher
    bot_instance = Bot(token=cfg.API_TOKEN, parse_mode="HTML")
    storage = MemoryStorage()
    dispatcher = Dispatcher(storage=storage)
    
    # Include routers
    dispatcher.include_router(bot_handlers.router)
    dispatcher.include_router(admin_panel.router)
    
    # Register startup/shutdown
    dispatcher.startup.register(on_startup)
    dispatcher.shutdown.register(on_shutdown)
    
    # Start polling
    try:
        await dispatcher.start_polling(
            bot_instance,
            allowed_updates=cfg.ALLOWED_UPDATES,
            skip_updates=True
        )
    except Exception as e:
        logger.critical(f"Polling failed: {e}")
        raise
    finally:
        await bot_instance.session.close()

# ===================================================================
# Webhook mode runner
# ===================================================================

async def run_webhook():
    """Run bot in webhook mode"""
    logger.info("Starting bot in webhook mode")
    
    from aiohttp import web
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
    
    bot_instance = Bot(token=cfg.API_TOKEN, parse_mode="HTML")
    storage = MemoryStorage()
    dispatcher = Dispatcher(storage=storage)
    
    # Include routers
    dispatcher.include_router(bot_handlers.router)
    dispatcher.include_router(admin_panel.router)
    
    # Register startup/shutdown
    dispatcher.startup.register(on_startup)
    dispatcher.shutdown.register(on_shutdown)
    
    # Setup webhook
    webhook_url = cfg.WEBHOOK_URL
    webhook_path = cfg.WEBHOOK_PATH
    
    await bot_instance.delete_webhook(drop_pending_updates=True)
    await bot_instance.set_webhook(
        url=f"{webhook_url}{webhook_path}",
        allowed_updates=cfg.ALLOWED_UPDATES,
        drop_pending_updates=True,
        secret_token=cfg.CRYPTOBOT_TOKEN[:32] if cfg.CRYPTOBOT_TOKEN else None
    )
    
    # Setup aiohttp app
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dispatcher,
        bot=bot_instance,
        secret_token=cfg.CRYPTOBOT_TOKEN[:32] if cfg.CRYPTOBOT_TOKEN else None
    )
    webhook_requests_handler.register(app, path=webhook_path)
    setup_application(app, dispatcher, bot=bot_instance)
    
    # Start payment webhook server (separate port or same app)
    from payments import start_webhook_server
    payment_runner = await start_webhook_server(bot_instance, "/cryptopulse_payment", cfg.WEBHOOK_PORT + 1)
    
    # Start main webhook server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", cfg.WEBHOOK_PORT)
    await site.start()
    
    logger.info(f"Webhook server running on port {cfg.WEBHOOK_PORT}")
    
    # Keep running
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        await runner.cleanup()
        await payment_runner.cleanup()
        await bot_instance.session.close()

from aiohttp import web
import json

async def webapp_api(request):
    """Обработчик API вызовов из WebApp"""
    data = await request.json()
    method = data.get('method')
    params = data.get('params', {})
    user_id = data.get('user_id')
    
    # Проверим пользователя в БД
    db = get_db()
    user = await db.get_user(user_id)
    if not user:
        return web.json_response({"ok": False, "error": "User not found"})
    
    result = None
    try:
        if method == 'getSymbols':
            result = cfg.get_symbols_as_list()
        elif method == 'getSignal':
            symbol = params.get('symbol', 'BTC/USDT')
            market = get_market_provider()
            analyzer = get_analyzer()
            news_agg = get_news_aggregator()
            price_data = {"prices": await market.get_historical_prices(symbol, "1h", 60), "volumes": [], "price_changes": []}
            news_items = await news_agg.get_news_by_coin(symbol.split('/')[0], 3)
            signal = await analyzer.get_signal(symbol, price_data, news_items)
            # Добавим флаг премиум
            has_premium = await db.has_active_subscription(user_id)
            signal['is_premium'] = has_premium
            result = signal
        elif method == 'getPriceHistory':
            symbol = params.get('symbol', 'BTC/USDT')
            timeframe = params.get('timeframe', '1h')
            limit = params.get('limit', 50)
            market = get_market_provider()
            ohlcv = await market.get_historical_prices(symbol, timeframe, limit)
            # Преобразуем в список словарей
            result = [{"timestamp": int(idx*3600 + time.time()-limit*3600), "close": price} for idx, price in enumerate(ohlcv)]
        elif method == 'getProfile':
            user_data = await db.get_user(user_id)
            has_sub = await db.has_active_subscription(user_id)
            expiry = await db.get_subscription_expiry(user_id)
            stats = await db.get_referral_stats(user_id)
            result = {
                "user_id": user_id,
                "username": user_data.get('username'),
                "has_subscription": has_sub,
                "expiry_date": datetime.fromtimestamp(expiry).strftime('%Y-%m-%d') if expiry else None,
                "balance": user_data.get('balance', 0),
                "referral_count": stats['direct_count']
            }
        elif method == 'createPaymentLink':
            payment_manager = get_payment_manager()
            payment_id = await db.create_payment(user_id, cfg.SUBSCRIPTION_PRICE_USD, "USDT")
            link = await payment_manager.create_invoice(cfg.SUBSCRIPTION_PRICE_USD, "USDT", payment_id)
            if not link:
                return web.json_response({"ok": False, "error": "Payment gateway error"})
            result = link
        elif method == 'getReferralLink':
            link = await db.get_referral_link(user_id)
            result = link
        else:
            return web.json_response({"ok": False, "error": "Unknown method"})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})
    
    return web.json_response({"ok": True, "result": result})

# В функцию on_startup или main добавь маршрут для aiohttp (если используешь вебхук)
# Пример:
# app.router.add_post('/api', webapp_api)

# ===================================================================
# Signal handlers for graceful shutdown
# ===================================================================

def handle_shutdown_signal(signum, frame):
    """Handle SIGTERM/SIGINT"""
    logger.info(f"Received signal {signum}, initiating shutdown...")
    # Cancel all running tasks
    for task in asyncio.all_tasks():
        task.cancel()
    logger.info("All tasks cancelled")

def register_signal_handlers():
    """Register signal handlers for graceful shutdown"""
    signal.signal(signal.SIGINT, handle_shutdown_signal)
    signal.signal(signal.SIGTERM, handle_shutdown_signal)

# ===================================================================
# Initialization and main entry
# ===================================================================

async def main():
    """Main async entry point"""
    global cfg, logger
    
    # Load and validate configuration
    cfg = validate_config_or_exit()
    
    # Setup logging
    logger = setup_logging(
        log_level=cfg.LOG_LEVEL,
        log_file=cfg.LOG_FILE,
        json_format=False,
        console_output=True
    )
    logger.info("=" * 60)
    logger.info("CryptoPulse AI Ultimate Bot Starting")
    logger.info(f"Version: 3.2.0")
    logger.info(f"Debug mode: {cfg.DEBUG_MODE}")
    logger.info(f"Admin IDs: {cfg.ADMIN_IDS}")
    logger.info("=" * 60)
    
    # Initialize database (creates tables)
    db = get_db()
    logger.info("Database initialized")
    
    # Check for required API keys
    if not cfg.OPENAI_API_KEY:
        logger.warning("OpenAI API key not set. AI signals will be limited.")
    if not cfg.CRYPTOBOT_TOKEN:
        logger.warning("CryptoBot token not set. Crypto payments disabled.")
    
    # Register signal handlers
    register_signal_handlers()
    
    # Run in appropriate mode
    try:
        if cfg.USE_WEBHOOK:
            await run_webhook()
        else:
            await run_polling()
    except asyncio.CancelledError:
        logger.info("Main task cancelled")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("Bot stopped")

# ===================================================================
# Entry point
# ===================================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)