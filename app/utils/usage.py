# app/utils/usage.py
"""Helper for aggregating user request counts."""
from __future__ import annotations

from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import RateLimit


def query_usage(db: Session, username: str, since: date | None) -> int:
    """Return total requests made by ``username`` since the given date.

    If ``since`` is ``None``, all records are aggregated.
    """
    q = db.query(func.sum(RateLimit.count)).filter(RateLimit.username == username)
    if since is not None:
        q = q.filter(RateLimit.date >= since)
    result = q.scalar()
    return int(result or 0)


def query_usage_all(db: Session, since: date | None) -> int:
    """Return total requests made by all users since the given date."""
    q = db.query(func.sum(RateLimit.count))
    if since is not None:
        q = q.filter(RateLimit.date >= since)
    result = q.scalar()
    return int(result or 0)
