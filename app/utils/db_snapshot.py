# app/utils/db_snapshot.py
"""Utility functions to create a snapshot of database state.

This module provides helpers for serialising SQLAlchemy models and for
collecting a full snapshot consisting of users, chat sessions and
statistics.
"""

from typing import Dict
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import SessionLocal
from app.models import User, Session as SessionModel, Message, RateLimit


def serialize_user(user: User) -> Dict[str, object]:
    """Return a JSON serialisable representation of a ``User``."""
    return {
        "username": user.username,
        "is_admin": user.is_admin,
        "daily_limit": user.daily_limit,
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
        usage_rows = (
            db.query(RateLimit.username, func.sum(RateLimit.count).label("count"))
            .group_by(RateLimit.username)
            .all()
        )
        usage = [{"username": r.username, "count": r.count} for r in usage_rows]
        return {
            "users": users,
            "sessions": sessions,
            "messages": messages,
            "usage": usage,
        }
    finally:
        db.close()
