from fastapi import FastAPI, HTTPException, Header
from database import SessionLocal, User, Withdrawal
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
import hashlib, hmac, urllib.parse, os
from dotenv import load_dotenv
import json

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Проверка подписи Telegram (чтобы нельзя было подделать юзера)
def verify_telegram_data(init_data: str):
    try:
        parsed_data = dict(urllib.parse.parse_qsl(init_data))
        if "hash" not in parsed_data:
            return None
        hash_str = parsed_data.pop("hash")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed_data.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        if calculated_hash == hash_str:
            user_data = json.loads(parsed_data["user"])
            return user_data["id"]
    except:
        pass
    return None

class WithdrawRequest(BaseModel):
    amount: float
    wallet: str

class WalletRequest(BaseModel):
    wallet: str

@app.post("/api/login")
def login(x_init_data: str = Header(None)):
    user_id = verify_telegram_data(x_init_data)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid auth")
    
    db = SessionLocal()
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        user = User(id=user_id)
        db.add(user)
        db.commit()
    
    # Считаем накопленное, если фармит
    pending_reward = 0
    if user.is_farming:
        now = datetime.utcnow()
        elapsed = (now - user.start_time).total_seconds()
        if elapsed > 28800: elapsed = 28800 # 8 часов лимит
        multiplier = 1.0 + (user.level - 1) * 0.05
        pending_reward = elapsed * 0.000057 * multiplier
        
    db.close()
    return {
        "user_id": user.id, "balance": user.balance, "level": user.level,
        "wallet": user.wallet_address, "is_farming": user.is_farming,
        "pending_reward": pending_reward
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
        earned = elapsed * 0.000057 * multiplier
        user.balance += earned
        user.is_farming = False
        user.start_time = None
        
        # Обновляем уровень (1 уровень = 50к токенов на балансе)
        # Формула: level = (balance / 50000) + 1. Максимум 1000.
        new_level = int(user.balance / 50000) + 1
        if new_level > 1000: new_level = 1000
        user.level = new_level
        
        db.commit()
    db.close()
    return {"status": "ok", "new_balance": user.balance, "level": user.level}

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
        raise HTTPException(status_code=400, detail="Min 50000 NEXA")
        
    db = SessionLocal()
    user = db.query(User).filter(User.id == user_id).first()
    
    if user.balance < req.amount:
        raise HTTPException(status_code=400, detail="Not enough balance")
    if not user.wallet_address:
        raise HTTPException(status_code=400, detail="No wallet linked")
        
    user.balance -= req.amount # Списываем сразу
    wd = Withdrawal(user_id=user.id, amount=req.amount, wallet=user.wallet_address)
    db.add(wd)
    db.commit()
    db.close()
    return {"status": "ok"}