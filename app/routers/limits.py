# app/routers/limits.py
"""Endpoints for viewing the current user's rate limits."""

from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.routers.auth import get_current_username, get_db
from app.models import User, RateLimit

router = APIRouter()


class LimitInfo(BaseModel):
    daily_limit: int
    used: int
    remaining: int


@router.get("", response_model=LimitInfo)
def get_limits(
    username: str = Depends(get_current_username),
    db: Session = Depends(get_db),
) -> LimitInfo:
    """Return the authenticated user's daily request limit and usage."""
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_admin:
        return LimitInfo(daily_limit=0, used=0, remaining=0)

    today = date.today()
    rl = (
        db.query(RateLimit)
        .filter(
            RateLimit.username == username,
            RateLimit.date == today,
        )
        .first()
    )
    used = rl.count if rl else 0
    remaining = max(0, user.daily_limit - used)
    return LimitInfo(daily_limit=user.daily_limit, used=used, remaining=remaining)
