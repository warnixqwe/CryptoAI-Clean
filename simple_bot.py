import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from config import get_config

logging.basicConfig(level=logging.INFO)
cfg = get_config()

bot = Bot(token=cfg.API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("✅ Бот работает! Команда /start получена.")

@dp.message()
async def echo(message: types.Message):
    await message.answer(f"Я получил: {message.text}")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Starting polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())