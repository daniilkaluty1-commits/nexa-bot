from fastapi import FastAPI, HTTPException, Header, Request
from backend.database import SessionLocal, User, Withdrawal, Setting, ReferralEarning, Task, UserTask
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import hashlib, hmac, urllib.parse, os, json
import requests
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID", "0")
TON_API_KEY = "AHGTYS7LYHXDJMAAAAAHFQJ5ORKVTAOVKTV7KU3N7U2RSFZFNROETBHJDM3IRBYYRM2HEEA"
TOKEN_CONTRACT = "EQCuxWmM9HG_T7i6B7PErsltrX8UohL-IUH7OSOWoXp_f8Tb"

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

price_cache = {"price": 0.0, "last_update": 0}
balance_cache = {}

def send_telegram_message(chat_id: int, text: str):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=5)
    except: pass

def get_token_price():
    now = datetime.utcnow().timestamp()
    if now - price_cache["last_update"] < 15: return price_cache["price"]
    try:
        res = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{TOKEN_CONTRACT}", timeout=5)
        data = res.json()
        if data.get('pairs'):
            price_cache["price"] = float(data['pairs'][0]['priceUsd'])
            price_cache["last_update"] = now
    except: pass
    return price_cache["price"]

def get_real_wallet_balance(wallet):
    if not wallet or wallet == TOKEN_CONTRACT: return 0.0
    now = datetime.utcnow().timestamp()
    if wallet in balance_cache and now - balance_cache[wallet]["last_update"] < 10: return balance_cache[wallet]["balance"]
    try:
        res = requests.get(f"https://tonapi.io/v2/accounts/{wallet}/jettons/{TOKEN_CONTRACT}", headers={"Authorization": f"Bearer {TON_API_KEY}"}, timeout=5)
        if res.status_code == 200:
            data = res.json()
            bal = int(data['balance']) / (10 ** int(data['jetton']['decimals']))
            balance_cache[wallet] = {"balance": bal, "last_update": now}
            return bal
        elif res.status_code == 404: return 0.0
    except: pass
    return 0.0

def get_wallet_transactions(wallet):
    if not wallet or wallet == TOKEN_CONTRACT: return []
    try:
        res = requests.get(f"https://tonapi.io/v2/accounts/{wallet}/jettons/{TOKEN_CONTRACT}/history?limit=5", headers={"Authorization": f"Bearer {TON_API_KEY}"}, timeout=5)
        if res.status_code == 200:
            events = res.json().get('events', [])
            txs = []
            for e in events:
                action = e['actions'][0]['simple_preview']['description']
                txs.append({"time": datetime.fromtimestamp(e['timestamp']).strftime("%d.%m %H:%M"), "text": action})
            return txs
    except: pass
    return []

def verify_telegram_data(init_data: str):
    try:
        parsed_data = dict(urllib.parse.parse_qsl(init_data))
        if "hash" not in parsed_data: return None, None
        hash_str = parsed_data.pop("hash")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed_data.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if calculated_hash == hash_str:
            return json.loads(parsed_data["user"]), parsed_data.get("start_param")
    except: pass
    return None, None

class WalletRequest(BaseModel): wallet: str
class WithdrawRequest(BaseModel): amount: float; withdraw_wallet: str 
class AdminAction(BaseModel): wd_id: int; action: str; tx_hash: str = None
class AdminEditBalance(BaseModel): target_id: int; amount: float; is_add: bool
class AdminChangeRole(BaseModel): target_id: int; is_admin: bool
class AdminSettings(BaseModel): maintenance: bool; base_income: float; level_bonus: float
class AdminResetWallet(BaseModel): target_id: int
# Новые модели для заданий
class AdminAddTask(BaseModel): title: str; url: str; reward: float
class AdminDelTask(BaseModel): task_id: int
class ClaimTask(BaseModel): task_id: int

@app.post("/api/login")
def login(request: Request, x_init_data: str = Header(None)):
    tg_data, start_param = verify_telegram_data(x_init_data)
    if not tg_data: raise HTTPException(status_code=401, detail="Auth error")
    
    user_id = tg_data["id"]
    username = tg_data.get("username", "")
    ip = request.headers.get("x-forwarded-for", request.client.host).split(",")[0].strip()
    
    db = SessionLocal()
    user = db.query(User).filter(User.id == user_id).first()
    is_main_admin = str(user_id) == str(ADMIN_ID)

    if not user:
        ref_id = None
        if start_param and start_param.isdigit():
            ref_id = int(start_param)
            if ref_id == user_id: ref_id = None
        user = User(id=user_id, username=username, ip_address=ip, is_admin=is_main_admin, referrer_id=ref_id)
        db.add(user)
    else:
        user.ip_address = ip
        if username: user.username = username
        if is_main_admin: user.is_admin = True
    
    if user.is_banned: 
        db.close()
        raise HTTPException(status_code=403, detail="banned")
    
    settings = db.query(Setting).first()
    if settings.maintenance and not user.is_admin:
        db.close()
        raise HTTPException(status_code=403, detail="maintenance")
    
    real_balance = get_real_wallet_balance(user.wallet_address)
    new_level = int(real_balance / 50000) + 1
    if new_level > 1000: new_level = 1000
    user.level = new_level
    
    pending_reward = 0
    if user.is_farming and not settings.maintenance:
        elapsed = (datetime.utcnow() - user.start_time).total_seconds()
        if elapsed > 28800: elapsed = 28800
        multiplier = 1.0 + (user.level - 1) * settings.level_bonus
        pending_reward = elapsed * settings.base_income * multiplier
        
    db.commit()
    res = {
        "user_id": user.id, "balance": user.balance, "level": user.level,
        "wallet": user.wallet_address, "real_balance": real_balance,
        "is_farming": user.is_farming, "pending_reward": pending_reward, 
        "is_admin": user.is_admin, "price": get_token_price(),
        "maintenance": settings.maintenance,
        "base_income": settings.base_income, "level_bonus": settings.level_bonus
    }
    db.close()
    return res

# ... (Эндпоинты start_farm, claim, set_wallet, unlink_wallet, withdraw, history ОСТАЮТСЯ БЕЗ ИЗМЕНЕНИЙ) ...

@app.post("/api/start_farm")
def start_farm(x_init_data: str = Header(None)):
    tg_data, _ = verify_telegram_data(x_init_data)
    user_id = tg_data["id"]
    db = SessionLocal()
    settings = db.query(Setting).first()
    if settings.maintenance: 
        db.close()
        raise HTTPException(status_code=400, detail="Технические работы на ферме!")
    user = db.query(User).filter(User.id == user_id).first()
    if not user.is_farming:
        user.is_farming = True
        user.start_time = datetime.utcnow()
        db.commit()
    db.close()
    return {"status": "ok"}

@app.post("/api/claim")
def claim(x_init_data: str = Header(None)):
    tg_data, _ = verify_telegram_data(x_init_data)
    user_id = tg_data["id"]
    db = SessionLocal()
    settings = db.query(Setting).first()
    user = db.query(User).filter(User.id == user_id).first()
    if user.is_farming:
        elapsed = (datetime.utcnow() - user.start_time).total_seconds()
        if elapsed > 28800: elapsed = 28800
        multiplier = 1.0 + (user.level - 1) * settings.level_bonus
        earned = elapsed * settings.base_income * multiplier
        user.balance += earned
        if user.referrer_id:
            ref_earn = earned * 0.10
            referrer = db.query(User).filter(User.id == user.referrer_id).first()
            if referrer:
                referrer.balance += ref_earn
                db.add(ReferralEarning(referrer_id=referrer.id, referred_id=user.id, amount=ref_earn))
        user.is_farming = False
        user.start_time = None
        db.commit()
    db.close()
    return {"status": "ok"}

@app.post("/api/set_wallet")
def set_wallet(req: WalletRequest, x_init_data: str = Header(None)):
    tg_data, _ = verify_telegram_data(x_init_data)
    user_id = tg_data["id"]
    if req.wallet == TOKEN_CONTRACT: raise HTTPException(status_code=400, detail="Ошибка: токен контракт!")
    db = SessionLocal()
    user = db.query(User).filter(User.id == user_id).first()
    user.wallet_address = req.wallet
    db.commit()
    db.close()
    return {"status": "ok"}

@app.post("/api/unlink_wallet")
def unlink_wallet(x_init_data: str = Header(None)):
    tg_data, _ = verify_telegram_data(x_init_data)
    user_id = tg_data["id"]
    db = SessionLocal()
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.wallet_address = None
        db.commit()
        if user.wallet_address in balance_cache: del balance_cache[user.wallet_address]
    db.close()
    return {"status": "ok"}

@app.post("/api/withdraw")
def withdraw(req: WithdrawRequest, x_init_data: str = Header(None)):
    tg_data, _ = verify_telegram_data(x_init_data)
    user_id = tg_data["id"]
    if req.amount < 50000: raise HTTPException(status_code=400, detail="Мин. 50 000")
    if not req.withdraw_wallet: raise HTTPException(status_code=400, detail="Введите адрес")
    db = SessionLocal()
    user = db.query(User).filter(User.id == user_id).first()
    if not user.wallet_address: 
        db.close()
        raise HTTPException(status_code=400, detail="Кошелек не привязан")
    real_balance = get_real_wallet_balance(user.wallet_address)
    required_hold = req.amount * 0.2
    if real_balance < required_hold:
        db.close()
        raise HTTPException(status_code=400, detail=f"Нужен холд {required_hold:.0f} NEXA")
    if user.balance < req.amount: 
        db.close()
        raise HTTPException(status_code=400, detail="Мало средств")
    user.balance -= req.amount
    db.add(Withdrawal(user_id=user.id, amount=req.amount, wallet=req.withdraw_wallet))
    db.commit()
    db.close()
    return {"status": "ok"}

@app.get("/api/history")
def history(x_init_data: str = Header(None)):
    tg_data, _ = verify_telegram_data(x_init_data)
    user_id = tg_data["id"]
    db = SessionLocal()
    wds = db.query(Withdrawal).filter(Withdrawal.user_id == user_id).order_by(Withdrawal.id.desc()).all()
    res = [{"id": w.id, "amount": w.amount, "status": w.status, "date": w.created_at.strftime("%d.%m.%Y %H:%M")} for w in wds]
    db.close()
    return res

# ================= ЗАДАНИЯ (ЮЗЕР) =================

@app.get("/api/tasks")
def get_tasks(x_init_data: str = Header(None)):
    tg_data, _ = verify_telegram_data(x_init_data)
    user_id = tg_data["id"]
    db = SessionLocal()
    
    all_tasks = db.query(Task).all()
    completed_task_ids = [ut.task_id for ut in db.query(UserTask).filter(UserTask.user_id == user_id).all()]
    
    res = []
    for t in all_tasks:
        res.append({
            "id": t.id, "title": t.title, "url": t.url, "reward": t.reward,
            "completed": t.id in completed_task_ids
        })
    db.close()
    return res

@app.post("/api/tasks/claim")
def claim_task(req: ClaimTask, x_init_data: str = Header(None)):
    tg_data, _ = verify_telegram_data(x_init_data)
    user_id = tg_data["id"]
    
    db = SessionLocal()
    task = db.query(Task).filter(Task.id == req.task_id).first()
    if not task:
        db.close()
        raise HTTPException(status_code=404, detail="Задание не найдено")
        
    already_done = db.query(UserTask).filter(UserTask.user_id == user_id, UserTask.task_id == task.id).first()
    if already_done:
        db.close()
        raise HTTPException(status_code=400, detail="Вы уже выполнили это задание")
        
    user = db.query(User).filter(User.id == user_id).first()
    user.balance += task.reward
    
    db.add(UserTask(user_id=user_id, task_id=task.id, status="completed"))
    db.commit()
    db.close()
    return {"status": "ok"}

# ================= АДМИНКА =================

def check_admin(x_init_data: str):
    tg_data, _ = verify_telegram_data(x_init_data)
    if not tg_data: return False
    db = SessionLocal()
    u = db.query(User).filter(User.id == tg_data["id"]).first()
    is_adm = u.is_admin if u else False
    db.close()
    return is_adm

@app.get("/api/admin/withdrawals")
def admin_wds(x_init_data: str = Header(None)):
    if not check_admin(x_init_data): raise HTTPException(status_code=403)
    db = SessionLocal()
    wds = db.query(Withdrawal).filter(Withdrawal.status == "pending").all()
    res = [{"id": w.id, "user_id": w.user_id, "amount": w.amount, "wallet": w.wallet, "date": w.created_at.strftime("%d.%m %H:%M")} for w in wds]
    db.close()
    return res

@app.get("/api/admin/all_withdrawals")
def admin_all_wds(search: str = "", x_init_data: str = Header(None)):
    if not check_admin(x_init_data): raise HTTPException(status_code=403)
    db = SessionLocal()
    query = db.query(Withdrawal)
    if search:
        query = query.filter((Withdrawal.user_id == search) | (Withdrawal.wallet.like(f"%{search}%")))
    wds = query.order_by(Withdrawal.id.desc()).all()
    res = [{"id": w.id, "user_id": w.user_id, "amount": w.amount, "wallet": w.wallet, "status": w.status, "date": w.created_at.strftime("%d.%m.%Y %H:%M")} for w in wds]
    db.close()
    return res

@app.get("/api/admin/referrals")
def admin_referrals(search: str = "", x_init_data: str = Header(None)):
    if not check_admin(x_init_data): raise HTTPException(status_code=403)
    db = SessionLocal()
    query = db.query(ReferralEarning)
    if search:
        query = query.filter((ReferralEarning.referrer_id == search) | (ReferralEarning.referred_id == search))
    refs = query.order_by(ReferralEarning.id.desc()).all()
    res = [{"id": r.id, "referrer_id": r.referrer_id, "referred_id": r.referred_id, "amount": r.amount, "date": r.created_at.strftime("%d.%m.%Y %H:%M")} for r in refs]
    db.close()
    return res

@app.post("/api/admin/action")
def admin_action(req: AdminAction, x_init_data: str = Header(None)):
    if not check_admin(x_init_data): raise HTTPException(status_code=403)
    db = SessionLocal()
    wd = db.query(Withdrawal).filter(Withdrawal.id == req.wd_id).first()
    if wd:
        if req.action == "approve":
            if not req.tx_hash:
                db.close()
                raise HTTPException(status_code=400, detail="Необходимо вставить ссылку на транзакцию")
            wd.status = "approved"
            msg = f"✅ <b>Вывод NEXA выполнен.</b>\n\nСумма: <b>{wd.amount} NEXA</b>\nАдрес: <code>{wd.wallet}</code>\nПроверка: {req.tx_hash}"
            send_telegram_message(wd.user_id, msg)
        else:
            wd.status = "rejected"
            usr = db.query(User).filter(User.id == wd.user_id).first()
            if usr: usr.balance += wd.amount
            msg = f"❌ <b>Вывод NEXA отклонен.</b>\n\nСумма: <b>{wd.amount} NEXA</b>\nСредства возвращены на баланс."
            send_telegram_message(wd.user_id, msg)
        db.commit()
    db.close()
    return {"status": "ok"}

@app.get("/api/admin/search_user")
def admin_search_user(query: str, x_init_data: str = Header(None)):
    if not check_admin(x_init_data): raise HTTPException(status_code=403)
    db = SessionLocal()
    user = db.query(User).filter((User.id == query) | (User.wallet_address == query)).first()
    if not user: 
        db.close()
        return {"found": False}
    real_bal = get_real_wallet_balance(user.wallet_address)
    txs = get_wallet_transactions(user.wallet_address)
    last_wd = db.query(Withdrawal).filter(Withdrawal.user_id == user.id).order_by(Withdrawal.id.desc()).first()
    res = {
        "found": True, "id": user.id, "username": user.username, "ip": user.ip_address,
        "wallet": user.wallet_address, "game_balance": user.balance, "real_balance": real_bal,
        "is_banned": user.is_banned, "is_admin": user.is_admin, "txs": txs, 
        "referrer_id": user.referrer_id, "last_withdraw_wallet": last_wd.wallet if last_wd else "-"
    }
    db.close()
    return res

@app.post("/api/admin/edit_balance")
def admin_edit_balance(req: AdminEditBalance, x_init_data: str = Header(None)):
    if not check_admin(x_init_data): raise HTTPException(status_code=403)
    db = SessionLocal()
    user = db.query(User).filter(User.id == req.target_id).first()
    if user:
        if req.is_add: user.balance += req.amount
        else: user.balance -= req.amount
        db.commit()
    db.close()
    return {"status": "ok"}

@app.post("/api/admin/toggle_ban")
def admin_toggle_ban(req: AdminChangeRole, x_init_data: str = Header(None)):
    if not check_admin(x_init_data): raise HTTPException(status_code=403)
    if str(req.target_id) == str(ADMIN_ID): raise HTTPException(status_code=403, detail="Главного админа нельзя забанить")
    db = SessionLocal()
    user = db.query(User).filter(User.id == req.target_id).first()
    if user:
        user.is_banned = not user.is_banned
        db.commit()
    db.close()
    return {"status": "ok"}

@app.post("/api/admin/toggle_admin")
def admin_toggle_admin(req: AdminChangeRole, x_init_data: str = Header(None)):
    if not check_admin(x_init_data): raise HTTPException(status_code=403)
    if str(req.target_id) == str(ADMIN_ID): raise HTTPException(status_code=403, detail="Нельзя снять права")
    db = SessionLocal()
    user = db.query(User).filter(User.id == req.target_id).first()
    if user:
        user.is_admin = req.is_admin
        db.commit()
    db.close()
    return {"status": "ok"}

@app.post("/api/admin/reset_wallet")
def admin_reset_wallet(req: AdminResetWallet, x_init_data: str = Header(None)):
    if not check_admin(x_init_data): raise HTTPException(status_code=403)
    db = SessionLocal()
    user = db.query(User).filter(User.id == req.target_id).first()
    if user:
        if user.wallet_address in balance_cache: del balance_cache[user.wallet_address]
        user.wallet_address = None
        db.commit()
    db.close()
    return {"status": "ok"}

@app.get("/api/admin/settings")
def admin_get_settings(x_init_data: str = Header(None)):
    if not check_admin(x_init_data): raise HTTPException(status_code=403)
    db = SessionLocal()
    s = db.query(Setting).first()
    res = {"maintenance": s.maintenance, "base_income": s.base_income, "level_bonus": s.level_bonus}
    db.close()
    return res

@app.post("/api/admin/settings")
def admin_set_settings(req: AdminSettings, x_init_data: str = Header(None)):
    if not check_admin(x_init_data): raise HTTPException(status_code=403)
    db = SessionLocal()
    s = db.query(Setting).first()
    s.maintenance = req.maintenance
    s.base_income = req.base_income
    s.level_bonus = req.level_bonus
    db.commit()
    db.close()
    return {"status": "ok"}

# ================= УПРАВЛЕНИЕ ЗАДАНИЯМИ (АДМИН) =================

@app.get("/api/admin/tasks")
def admin_get_tasks(x_init_data: str = Header(None)):
    if not check_admin(x_init_data): raise HTTPException(status_code=403)
    db = SessionLocal()
    tasks = db.query(Task).all()
    res = [{"id": t.id, "title": t.title, "url": t.url, "reward": t.reward} for t in tasks]
    db.close()
    return res

@app.post("/api/admin/tasks/add")
def admin_add_task(req: AdminAddTask, x_init_data: str = Header(None)):
    if not check_admin(x_init_data): raise HTTPException(status_code=403)
    db = SessionLocal()
    t = Task(title=req.title, url=req.url, reward=req.reward)
    db.add(t)
    db.commit()
    db.close()
    return {"status": "ok"}

@app.post("/api/admin/tasks/delete")
def admin_del_task(req: AdminDelTask, x_init_data: str = Header(None)):
    if not check_admin(x_init_data): raise HTTPException(status_code=403)
    db = SessionLocal()
    task = db.query(Task).filter(Task.id == req.task_id).first()
    if task:
        db.query(UserTask).filter(UserTask.task_id == task.id).delete()
        db.delete(task)
        db.commit()
    db.close()
    return {"status": "ok"}
