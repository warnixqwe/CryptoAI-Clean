import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from config import get_config, validate_config_or_exit
from logger import setup_logging
from database import get_db
from scheduler_tasks import start_scheduler, stop_scheduler

cfg = get_config()
logger = logging.getLogger(__name__)

bot: Bot = None
dp: Dispatcher = None

async def set_bot_commands(bot_instance: Bot):
    from aiogram.types import BotCommand, BotCommandScopeDefault
    commands = [
        BotCommand(command="start", description="Start bot"),
        BotCommand(command="menu", description="Main menu"),
        BotCommand(command="signal", description="Get BTC signal"),
        BotCommand(command="price", description="Price check"),
        BotCommand(command="market", description="Market summary"),
        BotCommand(command="news", description="Latest news"),
        BotCommand(command="subscribe", description="Buy premium"),
        BotCommand(command="referral", description="Invite friends"),
        BotCommand(command="balance", description="Bonus balance"),
        BotCommand(command="profile", description="Your profile"),
        BotCommand(command="help", description="Help"),
        BotCommand(command="admin", description="Admin panel")
    ]
    await bot_instance.set_my_commands(commands, scope=BotCommandScopeDefault())
    logger.info("Bot commands set")

async def on_startup(dispatcher):
    logger.info("Starting up...")
    get_db()
    # Неблокирующий прогрев кэша
    try:
        from market_data import get_market_provider
        market = get_market_provider()
        if market:
            await market.get_market_summary()
            logger.info("Market cache warmed")
    except Exception as e:
        logger.warning(f"Market warm-up failed: {e}")
    try:
        from news_parser import get_news_aggregator
        news = get_news_aggregator()
        if news:
            await news.get_news_summary(5)
            logger.info("News cache warmed")
    except Exception as e:
        logger.warning(f"News warm-up failed: {e}")
    try:
        start_scheduler()
        logger.info("Scheduler started")
    except Exception as e:
        logger.warning(f"Scheduler failed: {e}")
    await set_bot_commands(bot)
    for aid in cfg.ADMIN_IDS:
        try:
            await bot.send_message(aid, "✅ CryptoPulse AI bot started (full version)")
        except:
            pass
    logger.info("Startup complete")

async def on_shutdown(dispatcher):
    logger.info("Shutting down...")
    try:
        stop_scheduler()
    except:
        pass
    await bot.session.close()
    logger.info("Shutdown complete")

async def run_polling():
    global bot, dp
    bot = Bot(token=cfg.API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())
    try:
        from bot_handlers import router as bot_router
        dp.include_router(bot_router)
        logger.info("Bot handlers registered")
    except Exception as e:
        logger.error(f"Bot handlers load error: {e}")
    try:
        from admin_panel import router as admin_router
        dp.include_router(admin_router)
        logger.info("Admin panel registered")
    except Exception as e:
        logger.error(f"Admin panel load error: {e}")
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Polling started")
    await dp.start_polling(bot, allowed_updates=cfg.ALLOWED_UPDATES)

async def run_webhook():
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
    from aiohttp import web
    global bot, dp
    bot = Bot(token=cfg.API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())
    try:
        from bot_handlers import router as bot_router
        dp.include_router(bot_router)
    except:
        pass
    try:
        from admin_panel import router as admin_router
        dp.include_router(admin_router)
    except:
        pass
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    await bot.set_webhook(url=f"{cfg.WEBHOOK_URL}{cfg.WEBHOOK_PATH}", secret_token=cfg.CRYPTOBOT_TOKEN[:32] if cfg.CRYPTOBOT_TOKEN else None)
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=cfg.WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", cfg.WEBHOOK_PORT)
    await site.start()
    logger.info(f"Webhook listening on port {cfg.WEBHOOK_PORT}")
    await asyncio.Event().wait()

async def main():
    validate_config_or_exit()
    setup_logging(log_level=cfg.LOG_LEVEL, log_file=cfg.LOG_FILE)
    logger.info("Starting CryptoPulse AI Ultimate")
    if cfg.USE_WEBHOOK:
        await run_webhook()
    else:
        await run_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        logger.critical(f"Fatal: {e}")
        sys.exit(1)