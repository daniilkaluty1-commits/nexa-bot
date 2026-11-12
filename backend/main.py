from fastapi import FastAPI, HTTPException, Header
from database import SessionLocal, User, Withdrawal
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
import hashlib, hmac, urllib.parse, os, json
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

app = FastAPI()

# Исправленный CORS для Telegram WebApp
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False, # ВАЖНО: False, иначе браузер блокирует запрос
    allow_methods=["*"],
    allow_headers=["*"],
)

# Проверка подписи Telegram (чтобы нельзя было подделать юзера)
def verify_telegram_data(init_data: str):
    try:
        parsed_data = dict(urllib.parse.parse_qsl(init_data))
        if "hash" not in parsed_data: return None
        hash_str = parsed_data.pop("hash")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed_data.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        if calculated_hash == hash_str:
            user_data = json.loads(parsed_data["user"])
            return user_data["id"]
    except Exception as e:
        print(f"Auth error: {e}")
    return None

class WithdrawRequest(BaseModel):
    amount: float
    wallet: str

class WalletRequest(BaseModel):
    wallet: str

class AdminAction(BaseModel):
    wd_id: int
    action: str # approve или reject

@app.post("/api/login")
def login(x_init_data: str = Header(None)):
    user_id = verify_telegram_data(x_init_data)
    if not user_id: 
        raise HTTPException(status_code=401, detail="Ошибка авторизации Telegram")
    
    db = SessionLocal()
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        user = User(id=user_id)
        db.add(user)
        db.commit()
    
    if user.is_banned:
        db.close()
        raise HTTPException(status_code=403, detail="Вы забанены в NEXA")
    
    pending_reward = 0
    if user.is_farming:
        now = datetime.utcnow()
        elapsed = (now - user.start_time).total_seconds()
        if elapsed > 28800: elapsed = 28800 # Максимум 8 часов
        multiplier = 1.0 + (user.level - 1) * 0.05
        pending_reward = elapsed * 0.000057 * multiplier
        
    db.close()
    return {
        "user_id": user.id, 
        "balance": user.balance, 
        "level": user.level,
        "wallet": user.wallet_address, 
        "is_farming": user.is_farming,
        "pending_reward": pending_reward, 
        "is_admin": user.id == ADMIN_ID
    }

@app.post("/api/start_farm")
def start_farm(x_init_data: str = Header(None)):
    user_id = verify_telegram_data(x_init_data)
    db = SessionLocal()
    user = db.query(User).filter(User.id == user_id).first()
    if not user.is_farming:
        user.is_farming = True
        user.start_time = datetime.utcnow()
        db.commit()
    db.close()
    return {"status": "ok"}

@app.post("/api/claim")
def claim(x_init_data: str = Header(None)):
    user_id = verify_telegram_data(x_init_data)
    db = SessionLocal()
    user = db.query(User).filter(User.id == user_id).first()
    if user.is_farming:
        now = datetime.utcnow()
        elapsed = (now - user.start_time).total_seconds()
        if elapsed > 28800: elapsed = 28800
        
        multiplier = 1.0 + (user.level - 1) * 0.05
        user.balance += elapsed * 0.000057 * multiplier
        user.is_farming = False
        user.start_time = None
        
        # Обновляем уровень (1 уровень = 50к токенов)
        new_level = int(user.balance / 50000) + 1
        if new_level > 1000: new_level = 1000
        user.level = new_level
        
        db.commit()
    db.close()
    return {"status": "ok"}

@app.post("/api/set_wallet")
def set_wallet(req: WalletRequest, x_init_data: str = Header(None)):
    user_id = verify_telegram_data(x_init_data)
    db = SessionLocal()
    user = db.query(User).filter(User.id == user_id).first()
    user.wallet_address = req.wallet
    db.commit()
    db.close()
    return {"status": "ok"}

@app.post("/api/withdraw")
def withdraw(req: WithdrawRequest, x_init_data: str = Header(None)):
    user_id = verify_telegram_data(x_init_data)
    if req.amount < 50000: 
        raise HTTPException(status_code=400, detail="Минимальная сумма вывода: 50 000 NEXA")
        
    db = SessionLocal()
    user = db.query(User).filter(User.id == user_id).first()
    
    if user.balance < req.amount: 
        raise HTTPException(status_code=400, detail="Недостаточно средств на балансе")
    if not user.wallet_address: 
        raise HTTPException(status_code=400, detail="Сначала привяжите кошелек TON")
        
    user.balance -= req.amount # Списываем баланс
    wd = Withdrawal(user_id=user.id, amount=req.amount, wallet=user.wallet_address)
    db.add(wd)
    db.commit()
    db.close()
    return {"status": "ok"}

@app.get("/api/history")
def history(x_init_data: str = Header(None)):
    user_id = verify_telegram_data(x_init_data)
    db = SessionLocal()
    wds = db.query(Withdrawal).filter(Withdrawal.user_id == user_id).order_by(Withdrawal.id.desc()).all()
    db.close()
    return [{"id": w.id, "amount": w.amount, "status": w.status, "date": w.created_at.strftime("%d.%m.%Y %H:%M")} for w in wds]

# ================= АДМИН ЭНДПОИНТЫ =================

@app.get("/api/admin/withdrawals")
def admin_wds(x_init_data: str = Header(None)):
    user_id = verify_telegram_data(x_init_data)
    if user_id != ADMIN_ID: 
        raise HTTPException(status_code=403, detail="Нет доступа")
        
    db = SessionLocal()
    wds = db.query(Withdrawal).filter(Withdrawal.status == "pending").all()
    db.close()
    return [{"id": w.id, "user_id": w.user_id, "amount": w.amount, "wallet": w.wallet, "date": w.created_at.strftime("%d.%m %H:%M")} for w in wds]

@app.post("/api/admin/action")
def admin_action(req: AdminAction, x_init_data: str = Header(None)):
    user_id = verify_telegram_data(x_init_data)
    if user_id != ADMIN_ID: 
        raise HTTPException(status_code=403, detail="Нет доступа")
        
    db = SessionLocal()
    wd = db.query(Withdrawal).filter(Withdrawal.id == req.wd_id).first()
    if wd:
        if req.action == "approve":
            wd.status = "approved"
        else:
            wd.status = "rejected"
            # Возвращаем баланс, если отклонили
            usr = db.query(User).filter(User.id == wd.user_id).first()
            if usr: usr.balance += wd.amount
        db.commit()
    db.close()
    return {"status": "ok"}
