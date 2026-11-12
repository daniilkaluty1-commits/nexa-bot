from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime
import os

# Создаем папку /data, если ее нет
os.makedirs('/data', exist_ok=True)

DATABASE_URL = "sqlite:////data/nexa.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    balance = Column(Float, default=0.0)
    level = Column(Integer, default=1)
    wallet_address = Column(String, nullable=True)
    is_farming = Column(Boolean, default=False)
    start_time = Column(DateTime, nullable=True)
    is_banned = Column(Boolean, default=False)
    
class Withdrawal(Base):
    __tablename__ = "withdrawals"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer)
    amount = Column(Float)
    wallet = Column(String)
    status = Column(String, default="pending") 
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

Base.metadata.create_all(bind=engine)
