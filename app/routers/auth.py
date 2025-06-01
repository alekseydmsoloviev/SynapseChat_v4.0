# app/routers/auth.py

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
import secrets

from app.database import SessionLocal
from app.models import User

router = APIRouter()
security = HTTPBasic()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_username(
    credentials: HTTPBasicCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> str:
    """
    Проверяет Basic Auth данные и возвращает имя пользователя.
    """
    user = db.query(User).filter(User.username == credentials.username).first()
    if not user or not secrets.compare_digest(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверные имя пользователя или пароль",
            headers={"WWW-Authenticate": "Basic"},
        )
    return user.username


@router.get("/ping")
def ping(username: str = Depends(get_current_username)):
    """Простой эндпоинт для проверки доступности сервиса и авторизации"""
    return {"message": "pong", "user": username}
