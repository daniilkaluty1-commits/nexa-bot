from fastapi import FastAPI, HTTPException, Header
from backend.database import SessionLocal, User, Withdrawal
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import hashlib, hmac, urllib.parse, os, json
import requests
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

TON_API_KEY = "AHGTYS7LYHXDJMAAAAAHFQJ5ORKVTAOVKTV7KU3N7U2RSFZFNROETBHJDM3IRBYYRM2HEEA"
TOKEN_CONTRACT = "EQCuxWmM9HG_T7i6B7PErsltrX8UohL-IUH7OSOWoXp_f8Tb"

app = FastAPI()
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"status": "ok", "message": "NEXA API is running"}

price_cache = {"price": 0.0, "last_update": 0}
balance_cache = {}

def get_token_price():
    now = datetime.utcnow().timestamp()
    if now - price_cache["last_update"] < 60: 
        return price_cache["price"]
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{TOKEN_CONTRACT}"
        res = requests.get(url, timeout=5)
        data = res.json()
        if data.get('pairs'):
            price_cache["price"] = float(data['pairs'][0]['priceUsd'])
            price_cache["last_update"] = now
    except Exception as e:
        print(f"ОШИБКА DexScreener: {e}")
    return price_cache["price"]

def get_real_wallet_balance(wallet_address):
    if not wallet_address: return 0.0
    now = datetime.utcnow().timestamp()
    if wallet_address in balance_cache and now - balance_cache[wallet_address]["last_update"] < 60:
        return balance_cache[wallet_address]["balance"]
        
    try:
        url = f"https://tonapi.io/v2/accounts/{wallet_address}/jettons/{TOKEN_CONTRACT}"
        headers = {"Authorization": f"Bearer {TON_API_KEY}"}
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            decimals = int(data['jetton']['decimals'])
            bal = int(data['balance']) / (10 ** decimals)
            balance_cache[wallet_address] = {"balance": bal, "last_update": now}
            print(f"DEBUG: Кошелек {wallet_address} | Баланс: {bal}")
            return bal
        elif res.status_code == 404:
            return 0.0
        else:
            print(f"DEBUG TonAPI Ошибка: {res.status_code} - {res.text}")
    except Exception as e:
        print(f"ОШИБКА TonAPI: {e}")
    return 0.0

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
    except: pass
    return None

class WalletRequest(BaseModel): wallet: str
class WithdrawRequest(BaseModel): amount: float
class AdminAction(BaseModel): wd_id: int; action: str

@app.post("/api/login")
def login(x_init_data: str = Header(None)):
    user_id = verify_telegram_data(x_init_data)
    if not user_id: raise HTTPException(status_code=401, detail="Auth error")
    
    db = SessionLocal()
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        user = User(id=user_id)
        db.add(user)
        db.commit()
    
    if user.is_banned: 
        db.close()
        raise HTTPException(status_code=403, detail="Вы забанены")
    
    real_balance = get_real_wallet_balance(user.wallet_address)
    
    new_level = int(real_balance / 50000) + 1
    if new_level > 1000: new_level = 1000
    user.level = new_level
    
    pending_reward = 0
    if user.is_farming:
        now = datetime.utcnow()
        elapsed = (now - user.start_time).total_seconds()
        if elapsed > 28800: elapsed = 28800
        multiplier = 1.0 + (user.level - 1) * 0.05
        pending_reward = elapsed * 0.000057 * multiplier
        
    db.commit()
    
    # СОБИРАЕМ ДАННЫЕ ДО ЗАКРЫТИЯ БАЗЫ
    response_data = {
        "user_id": user.id, "balance": user.balance, "level": user.level,
        "wallet": user.wallet_address, "real_balance": real_balance,
        "is_farming": user.is_farming, "pending_reward": pending_reward, 
        "is_admin": user.id == ADMIN_ID, "price": get_token_price()
    }
    db.close()
    
    return response_data

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
    if req.amount < 50000: raise HTTPException(status_code=400, detail="Мин. 50 000 NEXA")
        
    db = SessionLocal()
    user = db.query(User).filter(User.id == user_id).first()
    
    real_balance = get_real_wallet_balance(user.wallet_address)
    required_hold = req.amount * 0.2
    if real_balance < required_hold:
        db.close()
        raise HTTPException(status_code=400, detail=f"Нужно холдить {required_hold:.0f} NEXA. У вас: {real_balance:.0f}")
        
    if user.balance < req.amount: 
        db.close()
        raise HTTPException(status_code=400, detail="Недостаточно игровых средств")
    if not user.wallet_address: 
        db.close()
        raise HTTPException(status_code=400, detail="Кошелек не привязан")
        
    user.balance -= req.amount
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
    
    res = [{"id": w.id, "amount": w.amount, "status": w.status, "date": w.created_at.strftime("%d.%m.%Y %H:%M")} for w in wds]
    db.close()
    return res

@app.get("/api/admin/withdrawals")
def admin_wds(x_init_data: str = Header(None)):
    user_id = verify_telegram_data(x_init_data)
    if user_id != ADMIN_ID: raise HTTPException(status_code=403, detail="Нет доступа")
    db = SessionLocal()
    wds = db.query(Withdrawal).filter(Withdrawal.status == "pending").all()
    
    res = [{"id": w.id, "user_id": w.user_id, "amount": w.amount, "wallet": w.wallet, "date": w.created_at.strftime("%d.%m %H:%M")} for w in wds]
    db.close()
    return res

@app.post("/api/admin/action")
def admin_action(req: AdminAction, x_init_data: str = Header(None)):
    user_id = verify_telegram_data(x_init_data)
    if user_id != ADMIN_ID: raise HTTPException(status_code=403, detail="Нет доступа")
    db = SessionLocal()
    wd = db.query(Withdrawal).filter(Withdrawal.id == req.wd_id).first()
    if wd:
        if req.action == "approve": wd.status = "approved"
        else:
            wd.status = "rejected"
            usr = db.query(User).filter(User.id == wd.user_id).first()
            if usr: usr.balance += wd.amount
        db.commit()
    db.close()
    return {"status": "ok"}
