# app/utils/db_snapshot.py
"""Utility functions to create a snapshot of database state.

This module provides helpers for serialising SQLAlchemy models and for
collecting a full snapshot consisting of users, chat sessions and
statistics.
"""

from typing import Dict
from sqlalchemy.orm import Session
from datetime import date

from app.database import SessionLocal
from app.models import User, Session as SessionModel, Message
from .usage import query_usage


def serialize_user(user: User) -> Dict[str, object]:
    """Return a JSON serialisable representation of a ``User``."""
    return {
        "username": user.username,
        "is_admin": user.is_admin,
        "daily_limit": user.daily_limit,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def serialize_session(session: SessionModel) -> Dict[str, object]:
    """Return a JSON serialisable representation of a ``Session``."""
    return {
        "session_id": session.session_id,
        "username": session.username,
        "created_at": session.created_at.isoformat() if session.created_at else None,
    }


def serialize_message(message: Message) -> Dict[str, object]:
    """Return a JSON serialisable representation of a ``Message``."""
    return {
        "id": message.id,
        "session_id": message.session_id,
        "username": message.username,
        "role": message.role,
        "model": message.model,
        "content": message.content,
        "timestamp": message.timestamp.isoformat() if message.timestamp else None,
    }


def collect_snapshot() -> Dict[str, object]:
    """Collect complete snapshot of users, sessions, messages and usage."""
    db: Session = SessionLocal()
    try:
        users = [serialize_user(u) for u in db.query(User).all()]
        sessions = [serialize_session(s) for s in db.query(SessionModel).all()]
        messages = [serialize_message(m) for m in db.query(Message).all()]
        usage = []
        today = date.today()
        for u in db.query(User).all():
            usage.append(
                {
                    "username": u.username,
                    "day": query_usage(db, u.username, today),
                    "total": query_usage(db, u.username, None),
                }
            )
        return {
            "users": users,
            "sessions": sessions,
            "messages": messages,
            "usage": usage,
        }
    finally:
        db.close()
