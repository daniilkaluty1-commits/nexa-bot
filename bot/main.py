import asyncio
import os
import aiohttp
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 8080))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❄️ Играть в NEXA ❄️", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])
    await message.answer(f"Привет, {message.from_user.first_name}!\nДобро пожаловать в зимнюю ферму NEXA. Нажми кнопку ниже, чтобы начать фармить токены.", reply_markup=kb)

@dp.message(Command("price"))
async def cmd_price(message: types.Message):
    # Здесь можно сделать запрос к API твоего бэкенда, чтобы получить курс
    # Но проще стукнуться напрямую в DexScreener
    contract = "EQCuxWmM9HG_T7i6B7PErsltrX8UohL-IUH7OSOWoXp_f8Tb"
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.dexscreener.com/latest/dex/tokens/{contract}") as resp:
            data = await resp.json()
            if data.get('pairs'):
                price = data['pairs'][0]['priceUsd']
                await message.answer(f"💎 **Курс NEXA:** ${float(price):.6f}\n\n[Купить на STON.fi](https://app.ston.fi/swap?ft=TON&tt={contract})", parse_mode="Markdown")
            else:
                await message.answer("Не удалось получить курс. Попробуйте позже.")

async def on_startup(bot: Bot):
    webhook_path = f"{WEBHOOK_URL}/webhook"
    await bot.set_webhook(webhook_path)
    print(f"Бот запущен. Вебхук установлен на: {webhook_path}")

async def on_shutdown(bot: Bot):
    await bot.delete_webhook()

def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    
    print(f"Запуск веб-сервера на порту {PORT}...")
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
