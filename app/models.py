# app/models.py
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func
from .database import Base

class User(Base):
    __tablename__ = "users"
    username      = Column(String,  primary_key=True, index=True)
    password_hash = Column(String,  nullable=False)
    is_admin      = Column(Boolean, default=False)
    daily_limit   = Column(Integer, default=1000)

class RateLimit(Base):
    __tablename__ = "rate_limits"
    username = Column(String, ForeignKey("users.username"), primary_key=True)
    date     = Column(String,               primary_key=True)  # YYYY-MM-DD
    count    = Column(Integer, default=0)

class Session(Base):
    __tablename__ = "sessions"
    session_id = Column(String, server_default=func.random(), primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Message(Base):
    __tablename__ = "messages"
    id         = Column(Integer, primary_key=True, index=True)
    session_id = Column(String,  nullable=False, index=True)
    role       = Column(String,  nullable=False)
    model      = Column(String,  nullable=False)
    content    = Column(String,  nullable=False)
    timestamp  = Column(DateTime(timezone=True), server_default=func.now())
