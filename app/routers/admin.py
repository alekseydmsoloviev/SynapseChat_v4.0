import os
import sys
import subprocess
import secrets

from fastapi import (
    APIRouter, Request, Depends, Form,
    status, HTTPException
)
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from dotenv import load_dotenv, dotenv_values, set_key
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import User, RateLimit, Session as SessionModel, Message
from app.utils.ollama import list_installed_models, remove_model

router = APIRouter()
templates = Jinja2Templates(directory="templates")
ENV_PATH = os.path.join(os.getcwd(), ".env")
security = HTTPBasic()

# Глобальный процесс API
api_process: subprocess.Popen = None


def get_current_admin(
    creds: HTTPBasicCredentials = Depends(security)
):
    db: Session = SessionLocal()
    user = db.query(User).filter(User.username == creds.username).first()
    db.close()
    if not user or not secrets.compare_digest(creds.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверные креденшлы"
        )
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только администратор"
        )
    return user.username


@router.on_event("startup")
def start_api_server():
    """Запуск API-процесса при старте админ-приложения."""
    global api_process
    # Если API уже запущен, не запускаем второй процесс
    if api_process is not None:
        return
    load_dotenv(ENV_PATH)
    port = os.getenv("PORT", "8000")
    cmd = [
        sys.executable, "-m", "uvicorn",
        "app.api_app:app", "--host", "0.0.0.0", "--port", port
    ]
    api_process = subprocess.Popen(cmd)


@router.get("/admin", response_class=HTMLResponse)
def dashboard(
    request: Request,
    admin: str = Depends(get_current_admin)
):
    cfg    = dotenv_values(ENV_PATH)
    port   = cfg.get("PORT", os.getenv("PORT", "8000"))
    limit  = cfg.get("DAILY_LIMIT", os.getenv("DAILY_LIMIT", "1000"))

    db: Session = SessionLocal()
    try:
        users     = db.query(User).all()
        models    = list_installed_models()
        sessions  = db.query(SessionModel).order_by(SessionModel.created_at.desc()).all()
        msg_counts = {
            s.session_id: db.query(Message)
                             .filter(Message.session_id == s.session_id)
                             .count()
            for s in sessions
        }
    finally:
        db.close()

    return templates.TemplateResponse("admin.html", {
        "request":    request,
        "port":       port,
        "limit":      limit,
        "users":      users,
        "models":     models,
        "sessions":   sessions,
        "msg_counts": msg_counts,
    })


@router.post("/admin/config")
def update_config(
    port: str = Form(...),
    limit: str = Form(...),
    admin: str  = Depends(get_current_admin)
):
    open(ENV_PATH, "a").close()
    set_key(ENV_PATH, "PORT", port)
    set_key(ENV_PATH, "DAILY_LIMIT", limit)
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/user")
def create_or_update_user(
    username_new: str = Form(...),
    password_new: str = Form(...),
    daily_limit: int   = Form(...),
    admin: str         = Depends(get_current_admin)
):
    db: Session = SessionLocal()
    try:
        u = db.query(User).filter(User.username == username_new).first()
        if u:
            u.password_hash = password_new
            u.daily_limit   = daily_limit
        else:
            u = User(
                username=username_new,
                password_hash=password_new,
                is_admin=False,
                daily_limit=daily_limit
            )
            db.add(u)
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/user/delete")
def delete_user(
    username_del: str = Form(...),
    admin: str        = Depends(get_current_admin)
):
    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username_del).first()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        if user.is_admin:
            raise HTTPException(status_code=403, detail="Нельзя удалять администратора")
        db.delete(user)
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/clear")
def clear_database(
    admin: str = Depends(get_current_admin)
):
    """Очистить всю БД и удалить все установленные модели."""
    db: Session = SessionLocal()
    try:
        db.query(Message).delete()
        db.query(SessionModel).delete()
        db.query(RateLimit).delete()
        db.query(User).delete()
        db.commit()
    finally:
        db.close()

    for model in list_installed_models():
        try:
            remove_model(model)
        except Exception:
            pass
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/restart")
def restart_api_server(
    admin: str = Depends(get_current_admin)
):
    """Перезапуск API-сервера на новом порту из .env."""
    global api_process

    # Убить процессы, слушающие старый порт
    old_cfg  = dotenv_values(ENV_PATH)
    old_port = old_cfg.get("PORT", "8000")
    try:
        out = subprocess.check_output(f'netstat -ano | findstr :{old_port}', shell=True, text=True)
        for line in out.splitlines():
            pid = line.split()[-1]
            subprocess.run(
                f'taskkill /PID {pid} /F', shell=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
    except subprocess.CalledProcessError:
        pass

    # Завершаем текущий процесс API
    if api_process and api_process.poll() is None:
        api_process.kill()
        api_process.wait(timeout=5)
        api_process = None

    # Запуск API на новом порту
    new_cfg  = dotenv_values(ENV_PATH)
    new_port = new_cfg.get("PORT", "8000")
    cmd = [
        sys.executable, "-m", "uvicorn",
        "app.api_app:app", "--host", "0.0.0.0", "--port", new_port
    ]
    api_process = subprocess.Popen(cmd)
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)
