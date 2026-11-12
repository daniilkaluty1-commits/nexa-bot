from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime
import os

os.makedirs('/data', exist_ok=True)
DATABASE_URL = "sqlite:////data/nexa.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True) # TG ID
    username = Column(String, nullable=True)
    balance = Column(Float, default=0.0)
    level = Column(Integer, default=1)
    wallet_address = Column(String, nullable=True)
    is_farming = Column(Boolean, default=False)
    start_time = Column(DateTime, nullable=True)
    is_banned = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    ip_address = Column(String, nullable=True)
    
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
    base_income = Column(Float, default=0.000057) # Базовая ставка в сек
    level_bonus = Column(Float, default=0.05) # +5% за уровень

Base.metadata.create_all(bind=engine)

# Создаем дефолтные настройки, если их нет
db = SessionLocal()
if not db.query(Setting).first():
    db.add(Setting(maintenance=False, base_income=0.000057, level_bonus=0.05))
    db.commit()
db.close()
