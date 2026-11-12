import asyncio
import os
import sys
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# Добавляем путь к папке backend, чтобы импортировать базу
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))
from database import SessionLocal, Withdrawal, User

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
WEBAPP_URL = os.getenv("WEBAPP_URL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
# Порт, который требует Amvera
PORT = int(os.getenv("PORT", 8080))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= ОБРАБОТЧИКИ =================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❄️ Играть в NEXA ❄️", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])
    await message.answer(f"Привет, {message.from_user.first_name}!\nДобро пожаловать в зимнюю ферму NEXA. Нажми кнопку ниже, чтобы начать фармить токены.", reply_markup=kb)

@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    db = SessionLocal()
    reqs = db.query(Withdrawal).filter(Withdrawal.status == "pending").all()
    db.close()
    
    if not reqs:
        await message.answer("Нет активных заявок на вывод.")
        return
        
    for r in reqs:
        text = f"Заявка #{r.id}\nЮзер: {r.user_id}\nСумма: {r.amount} NEXA\nКошелек: {r.wallet}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Выплачено", callback_data=f"app_{r.id}"),
             InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rej_{r.id}")]
        ])
        await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("app_"))
async def approve_wd(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    wd_id = int(call.data.split("_")[1])
    db = SessionLocal()
    wd = db.query(Withdrawal).filter(Withdrawal.id == wd_id).first()
    if wd:
        wd.status = "approved"
        db.commit()
    db.close()
    await call.message.edit_text(call.message.text + "\n\n✅ ВЫПЛАЧЕНО")

@dp.callback_query(F.data.startswith("rej_"))
async def reject_wd(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    wd_id = int(call.data.split("_")[1])
    db = SessionLocal()
    wd = db.query(Withdrawal).filter(Withdrawal.id == wd_id).first()
    if wd:
        wd.status = "rejected"
        user = db.query(User).filter(User.id == wd.user_id).first()
        if user:
            user.balance += wd.amount # Возвращаем баланс
        db.commit()
    db.close()
    await call.message.edit_text(call.message.text + "\n\n❌ ОТКЛОНЕНО (средства возвращены)")

# ================= ВЕБХУК И ЗАПУСК =================

async def on_startup(bot: Bot):
    # Устанавливаем вебхук при запуске
    webhook_path = f"{WEBHOOK_URL}/webhook"
    await bot.set_webhook(webhook_path)
    print(f"Бот запущен. Вебхук установлен на: {webhook_path}")

async def on_shutdown(bot: Bot):
    # Удаляем вебхук при выключении
    await bot.delete_webhook()

def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    app = web.Application()
    
    # Регистрируем обработчик вебхука
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path="/webhook")
    
    setup_application(app, dp, bot=bot)
    
    print(f"Запуск веб-сервера на порту {PORT}...")
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()