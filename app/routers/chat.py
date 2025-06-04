# app/routers/chat.py
from fastapi import APIRouter, Depends, HTTPException, status
from datetime import datetime, date
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import RateLimit, User, Session as SessionModel, Message
from app.utils.usage import get_global_limit, query_usage_all

from app.routers.auth import get_current_username
from app.utils.ollama import chat

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_and_increment_limit(db: Session, username: str):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_admin:
        return  # админ без ограничений

    today = date.today()
    rl = (
        db.query(RateLimit)
        .filter(RateLimit.username == username, RateLimit.date == today)
        .first()
    )
    if not rl:
        rl = RateLimit(username=username, date=today, count=0)
        db.add(rl)
        db.commit()
        db.refresh(rl)

    user_limit = user.daily_limit if user.daily_limit is not None else 1000
    if rl.count >= user_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily request limit reached",
        )

    global_limit = get_global_limit()
    if global_limit:
        day_total = query_usage_all(db, today)
        if day_total >= global_limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Global daily request limit reached",
            )

    rl.count += 1
    db.commit()


@router.post("/{session_id}")
def send_message(
    session_id: str,
    payload: dict,
    username: str = Depends(get_current_username),
    db: Session = Depends(get_db),
):
    # Проверяем и инкрементируем лимит перед запросом к модели
    check_and_increment_limit(db, username)

    # Создаем новую сессию, если её ещё нет
    session = (
        db.query(SessionModel)
        .filter(
            SessionModel.session_id == session_id, SessionModel.username == username
        )
        .first()
    )
    if not session:
        session = SessionModel(
            session_id=session_id, username=username, title=payload["prompt"]
        )
        db.add(session)
        db.commit()
    elif session.title is None:
        session.title = payload["prompt"]
        db.commit()

    # Сохраняем сообщение пользователя
    user_msg = Message(
        username=username,
        session_id=session_id,
        role="user",
        model=payload["model"],
        content=payload["prompt"],
    )
    db.add(user_msg)
    db.commit()

    # Запрос к модели
    response_text = chat(
        session_id=session_id, model=payload["model"], prompt=payload["prompt"]
    )

    # Сохраняем ответ модели
    bot_msg = Message(
        username=username,
        session_id=session_id,
        role="assistant",
        model=payload["model"],
        content=response_text,
    )
    db.add(bot_msg)
    db.commit()

    return {"response": response_text}
