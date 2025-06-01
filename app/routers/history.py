# app/routers/history.py
"""
Эндпоинты для управления историей чатов:
- Получение списка сессий
- Получение сообщений конкретной сессии
- Удаление сессии и всех её сообщений
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.routers.auth import get_current_username, get_db
from app.models import Session as SessionModel, Message
from pydantic import BaseModel

router = APIRouter()

class SessionInfo(BaseModel):
    session_id: str
    created_at: str  # ISO datetime as string

class MessageInfo(BaseModel):
    role: str
    model: str
    content: str
    timestamp: str  # ISO datetime as string

@router.get("/sessions", response_model=List[SessionInfo])
def list_sessions(username: str = Depends(get_current_username), db: Session = Depends(get_db)):
    """Возвращает список всех сессий чатов"""
    sessions = db.query(SessionModel).order_by(SessionModel.created_at.desc()).all()
    return [SessionInfo(session_id=s.session_id, created_at=s.created_at.isoformat()) for s in sessions]

@router.get("/{session_id}", response_model=List[MessageInfo])
def get_session_messages(
    session_id: str,
    username: str = Depends(get_current_username),
    db: Session = Depends(get_db),
) -> List[MessageInfo]:
    """Возвращает список сообщений для указанной сессии"""
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    messages = db.query(Message).filter(Message.session_id == session_id).order_by(Message.timestamp.asc()).all()
    return [
        MessageInfo(
            role=m.role,
            model=m.model,
            content=m.content,
            timestamp=m.timestamp.isoformat()
        ) for m in messages
    ]

@router.delete("/{session_id}")
def delete_session(
    session_id: str,
    username: str = Depends(get_current_username),
    db: Session = Depends(get_db),
):
    """Удаляет сессию и все её сообщения"""
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    # Удалить сообщения
    db.query(Message).filter(Message.session_id == session_id).delete()
    # Удалить саму сессию
    db.delete(session)
    db.commit()
    return {"message": f"Session '{session_id}' and its messages have been deleted."}
