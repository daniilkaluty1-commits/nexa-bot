from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError
import datetime
import os

os.makedirs('/data', exist_ok=True)
DATABASE_URL = "sqlite:////data/nexa.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=True)
    balance = Column(Float, default=0.0)
    level = Column(Integer, default=1)
    wallet_address = Column(String, nullable=True)
    is_farming = Column(Boolean, default=False)
    start_time = Column(DateTime, nullable=True)
    is_banned = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    ip_address = Column(String, nullable=True)
    referrer_id = Column(Integer, nullable=True)
    # Новые поля для времени
    play_time = Column(Integer, default=0) # в секундах
    last_heartbeat = Column(DateTime, nullable=True)
    
class Withdrawal(Base):
    __tablename__ = "withdrawals"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer)
    amount = Column(Float)
    wallet = Column(String)
    status = Column(String, default="pending") 
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Setting(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True, index=True)
    maintenance = Column(Boolean, default=False)
    base_income = Column(Float, default=0.000057)
    level_bonus = Column(Float, default=0.05)

class ReferralEarning(Base):
    __tablename__ = "referral_earnings"
    id = Column(Integer, primary_key=True, index=True)
    referrer_id = Column(Integer)
    referred_id = Column(Integer)
    amount = Column(Float)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    url = Column(String, nullable=True)      # Для подписки
    chat_id = Column(String, nullable=True)  # Больше не используется, но оставим
    reward = Column(Float)
    # Новые поля для типов заданий
    task_type = Column(String, default="subscribe") # subscribe, coins, time, level
    target_value = Column(Float, default=0.0)       # Сколько нужно накопить/отыграть

class UserTask(Base):
    __tablename__ = "user_tasks"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer)
    task_id = Column(Integer)
    status = Column(String, default="completed")

Base.metadata.create_all(bind=engine)

# Безопасная миграция базы
try:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN referrer_id INTEGER"))
except OperationalError: pass

try:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN play_time INTEGER DEFAULT 0"))
        conn.execute(text("ALTER TABLE users ADD COLUMN last_heartbeat DATETIME"))
except OperationalError: pass

try:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE tasks ADD COLUMN task_type VARCHAR DEFAULT 'subscribe'"))
        conn.execute(text("ALTER TABLE tasks ADD COLUMN target_value FLOAT DEFAULT 0.0"))
except OperationalError: pass

db = SessionLocal()
if not db.query(Setting).first():
    db.add(Setting(maintenance=False, base_income=0.000057, level_bonus=0.05))
    db.commit()
db.close()
