# app/utils/db_snapshot.py
"""Utility functions to create a snapshot of database state.

This module provides helpers for serialising SQLAlchemy models and for
collecting a full snapshot consisting of users, chat sessions and
statistics.
"""

from typing import Dict, List
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
        "title": session.title,
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


def collect_chat_messages(db: Session, session: SessionModel) -> Dict[str, object]:
    """Return session info with its messages and last message timestamp."""
    msgs = (
        db.query(Message)
        .filter(
            Message.session_id == session.session_id,
            Message.username == session.username,
        )
        .order_by(Message.timestamp.asc())
        .all()
    )
    serialized_msgs = [serialize_message(m) for m in msgs]
    last = max((m.timestamp for m in msgs), default=None)
    return {
        **serialize_session(session),
        "messages": serialized_msgs,
        "last_message": last.isoformat() if last else None,
    }


def collect_snapshot() -> Dict[str, object]:
    """Collect snapshot of users, sessions with messages and usage."""
    db: Session = SessionLocal()
    try:
        users = [serialize_user(u) for u in db.query(User).all()]
        sessions = [
            collect_chat_messages(db, s) for s in db.query(SessionModel).all()
        ]
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
