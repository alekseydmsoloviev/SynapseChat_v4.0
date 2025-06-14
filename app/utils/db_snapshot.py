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


def collect_chat_summary(db: Session, session: SessionModel) -> Dict[str, object]:
    """Return session info with message count and last timestamp."""
    last_msg = (
        db.query(Message)
        .filter(
            Message.session_id == session.session_id,
            Message.username == session.username,
        )
        .order_by(Message.timestamp.desc())
        .first()
    )
    count = (
        db.query(Message)
        .filter(
            Message.session_id == session.session_id,
            Message.username == session.username,
        )
        .count()
    )
    last_ts = last_msg.timestamp.isoformat() if last_msg else None
    title = session.title
    if title is None:
        first_msg = (
            db.query(Message)
            .filter(
                Message.session_id == session.session_id,
                Message.username == session.username,
                Message.role == "user",
            )
            .order_by(Message.timestamp.asc())
            .first()
        )
        if first_msg:
            title = first_msg.content
    return {
        "session_id": session.session_id,
        "username": session.username,
        "title": title,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "message_count": count,
        "last_message": last_ts,
    }


def collect_overview() -> Dict[str, object]:
    """Return snapshot with detailed user info and chat summaries."""
    db: Session = SessionLocal()
    try:
        today = date.today()
        users: List[Dict[str, object]] = []
        for u in db.query(User).all():
            chat_count = (
                db.query(SessionModel)
                .filter(SessionModel.username == u.username)
                .count()
            )
            users.append(
                {
                    "username": u.username,
                    "password": u.password_hash,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                    "daily_limit": u.daily_limit,
                    "is_admin": u.is_admin,
                    "chat_count": chat_count,
                    "day": query_usage(db, u.username, today),
                    "total": query_usage(db, u.username, None),
                }
            )

        chats = [
            collect_chat_summary(db, s) for s in db.query(SessionModel).all()
        ]

        return {"users": users, "chats": chats}
    finally:
        db.close()


def collect_detailed_snapshot() -> Dict[str, object]:
    """Backward-compatible alias for ``collect_overview``."""
    return collect_overview()
