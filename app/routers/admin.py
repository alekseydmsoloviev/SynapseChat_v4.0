import os
import sys
import subprocess
import secrets
import base64
import asyncio
import psutil
from typing import Optional, Set

from fastapi import APIRouter, Request, Depends, Form, status, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import (
    RedirectResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
)
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from dotenv import load_dotenv, dotenv_values, set_key
from sqlalchemy import func
from sqlalchemy.orm import Session
from datetime import date

from app.utils.db_snapshot import collect_chat_summary
from app.utils.usage import query_usage, query_usage_all, get_global_limit

from app.database import SessionLocal
from app.models import User, RateLimit, Session as SessionModel, Message
from app.utils.ollama import (
    list_installed_models,
    remove_model,
    list_remote_base_models,
    list_model_variants,
    install_model,
)


router = APIRouter()
templates = Jinja2Templates(directory="templates")
ENV_PATH = os.path.join(os.getcwd(), ".env")
load_dotenv(ENV_PATH)
LOG_PATH = os.getenv("LOG_PATH", os.path.join(os.getcwd(), "app.log"))
security = HTTPBasic()

# Глобальный процесс API
# Active API process
api_process: Optional[subprocess.Popen] = None
# Основной event loop приложения
event_loop: Optional[asyncio.AbstractEventLoop] = None
# Подключённые WebSocket-клиенты администратора
ws_clients: Set[WebSocket] = set()


async def broadcast_progress(message: str) -> None:
    """Send progress line to all connected admin WebSocket clients."""
    for ws in list(ws_clients):
        try:
            await ws.send_json({"type": "progress", "data": message})
        except Exception:
            ws_clients.discard(ws)


def get_current_admin(creds: HTTPBasicCredentials = Depends(security)):
    db: Session = SessionLocal()
    user = db.query(User).filter(User.username == creds.username).first()
    db.close()
    if not user or not secrets.compare_digest(creds.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверные креденшлы"
        )
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Только администратор"
        )
    return user.username


@router.on_event("startup")
def start_api_server():
    """Запуск API-процесса при старте админ-приложения."""
    global api_process, event_loop
    event_loop = asyncio.get_event_loop()
    # Создаём файл логов, если его ещё нет
    try:
        open(LOG_PATH, "a").close()
    except Exception:
        pass
    # Если API уже запущен, не запускаем второй процесс
    if api_process is not None:
        return
    load_dotenv(ENV_PATH)
    port = os.getenv("PORT", "8000")
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.api_app:app",
        "--host",
        "0.0.0.0",
        "--port",
        port,
    ]
    api_process = subprocess.Popen(cmd)


@router.get("/admin", response_class=HTMLResponse)
def dashboard(request: Request, admin: str = Depends(get_current_admin)):
    cfg = dotenv_values(ENV_PATH)
    port = cfg.get("PORT", os.getenv("PORT", "8000"))
    limit = cfg.get("DAILY_LIMIT", os.getenv("DAILY_LIMIT", "1000"))

    db: Session = SessionLocal()
    try:
        users = db.query(User).all()
        models = list_installed_models()
        sessions = db.query(SessionModel).order_by(SessionModel.created_at.desc()).all()
        msg_counts = {
            s.session_id: db.query(Message)
            .filter(
                Message.session_id == s.session_id,
                Message.username == s.username,
            )
            .count()
            for s in sessions
        }
    finally:
        db.close()

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "port": port,
            "limit": limit,
            "users": users,
            "models": models,
            "sessions": sessions,
            "msg_counts": msg_counts,
        },
    )


@router.post("/admin/config")
def update_config(
    port: str = Form(...),
    limit: str = Form(...),
    admin: str = Depends(get_current_admin),
):
    open(ENV_PATH, "a").close()
    set_key(ENV_PATH, "PORT", port)
    set_key(ENV_PATH, "DAILY_LIMIT", limit)
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/user")
def create_or_update_user(
    username_new: str = Form(...),
    password_new: str = Form(...),
    daily_limit: int = Form(...),
    admin: str = Depends(get_current_admin),
):
    db: Session = SessionLocal()
    try:
        u = db.query(User).filter(User.username == username_new).first()
        if u:
            u.password_hash = password_new
            u.daily_limit = daily_limit
        else:
            u = User(
                username=username_new,
                password_hash=password_new,
                is_admin=False,
                daily_limit=daily_limit,
            )
            db.add(u)
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/user/delete")
def delete_user(username_del: str = Form(...), admin: str = Depends(get_current_admin)):
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
def clear_database(admin: str = Depends(get_current_admin)):
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
def restart_api_server(admin: str = Depends(get_current_admin)):
    """Перезапуск API-сервера на новом порту из .env."""
    global api_process

    # Убить процессы, слушающие старый порт
    old_cfg = dotenv_values(ENV_PATH)
    old_port = old_cfg.get("PORT", "8000")
    try:
        out = subprocess.check_output(
            f"netstat -ano | findstr :{old_port}", shell=True, text=True
        )
        for line in out.splitlines():
            pid = line.split()[-1]
            subprocess.run(
                f"taskkill /PID {pid} /F",
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except subprocess.CalledProcessError:
        pass

    # Завершаем текущий процесс API
    if api_process and api_process.poll() is None:
        api_process.kill()
        api_process.wait(timeout=5)
        api_process = None

    # Запуск API на новом порту
    new_cfg = dotenv_values(ENV_PATH)
    new_port = new_cfg.get("PORT", "8000")
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.api_app:app",
        "--host",
        "0.0.0.0",
        "--port",
        new_port,
    ]
    api_process = subprocess.Popen(cmd)
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


# ----- JSON API Endpoints -----


@router.get("/admin/api/users")
def api_list_users(admin: str = Depends(get_current_admin)):
    """Return list of users."""
    db: Session = SessionLocal()
    try:
        users = db.query(User).all()
        payload = [
            {
                "username": u.username,
                "is_admin": u.is_admin,
                "daily_limit": u.daily_limit,
            }
            for u in users
        ]
        return JSONResponse(payload)
    finally:
        db.close()


@router.get("/admin/api/users/{username}")
def api_get_user(username: str, admin: str = Depends(get_current_admin)):
    """Return detailed information for a single user."""
    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        chat_count = db.query(SessionModel).filter(SessionModel.username == username).count()
        today = date.today()
        payload = {
            "username": user.username,
            "password": user.password_hash,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "daily_limit": user.daily_limit,
            "is_admin": user.is_admin,
            "chat_count": chat_count,
            "day": query_usage(db, username, today),
            "total": query_usage(db, username, None),
        }
        return JSONResponse(payload)
    finally:
        db.close()


@router.post("/admin/api/users")
def api_create_or_update_user(payload: dict, admin: str = Depends(get_current_admin)):
    """Create or update a user."""
    username = payload.get("username")
    password = payload.get("password")
    limit_val = payload.get("daily_limit")
    daily_limit = int(limit_val) if limit_val is not None else 1000
    if not username or not password:
        raise HTTPException(status_code=400, detail="username and password required")
    db: Session = SessionLocal()
    try:
        u = db.query(User).filter(User.username == username).first()
        if u:
            u.password_hash = password
            u.daily_limit = daily_limit
        else:
            u = User(
                username=username,
                password_hash=password,
                is_admin=False,
                daily_limit=daily_limit,
            )
            db.add(u)
        db.commit()
    finally:
        db.close()
    return JSONResponse({"message": f"User '{username}' created/updated."})


@router.delete("/admin/api/users/{username}")
def api_delete_user(username: str, admin: str = Depends(get_current_admin)):
    """Delete a non-admin user."""
    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if user.is_admin:
            raise HTTPException(status_code=403, detail="Cannot delete admin user")
        db.delete(user)
        db.commit()
    finally:
        db.close()
    return JSONResponse({"message": f"User '{username}' deleted."})


@router.get("/admin/api/config")
def api_get_config(admin: str = Depends(get_current_admin)):
    """Return server configuration from .env."""
    cfg = dotenv_values(ENV_PATH)
    port = cfg.get("PORT", os.getenv("PORT", "8000"))
    limit = cfg.get("DAILY_LIMIT", os.getenv("DAILY_LIMIT", "1000"))
    return JSONResponse({"port": port, "daily_limit": limit})


@router.post("/admin/api/config")
def api_update_config(payload: dict, admin: str = Depends(get_current_admin)):
    """Update configuration values in .env."""
    port = str(payload.get("port", "8000"))
    limit = str(payload.get("daily_limit", "1000"))
    open(ENV_PATH, "a").close()
    set_key(ENV_PATH, "PORT", port)
    set_key(ENV_PATH, "DAILY_LIMIT", limit)
    # propagate new limit to all non-admin users
    db: Session = SessionLocal()
    try:
        db.query(User).filter(User.is_admin == False).update({User.daily_limit: int(limit)})
        db.commit()
    finally:
        db.close()
    return JSONResponse({"message": "Configuration updated."})


@router.get("/admin/api/models")
def api_installed_models(admin: str = Depends(get_current_admin)):
    """List installed models."""
    try:
        models = list_installed_models()
        return JSONResponse(models)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/api/models/available")
def api_available_models(admin: str = Depends(get_current_admin)):
    """List base models available for installation."""
    try:
        models = list_remote_base_models()
        return JSONResponse(models)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/api/models/{name}/variants")
def api_model_variants(name: str, admin: str = Depends(get_current_admin)):
    """List variants for a specific model."""
    try:
        variants = list_model_variants(name)
        return JSONResponse(variants)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/api/models/{name}/install")
def api_install_model(name: str, admin: str = Depends(get_current_admin)):
    """Install a model from the registry."""
    def _progress(line: str) -> None:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
        if event_loop:
            event_loop.call_soon_threadsafe(asyncio.create_task, broadcast_progress(line))

    try:
        install_model(name, progress_callback=_progress)
        return JSONResponse({"message": f"Model '{name}' installed."})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/admin/api/models/{name}")
def api_remove_model(name: str, admin: str = Depends(get_current_admin)):
    """Remove an installed model."""
    try:
        remove_model(name)
        return JSONResponse({"message": f"Model '{name}' removed."})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/api/sessions")
def api_list_sessions(admin: str = Depends(get_current_admin)):
    """Return list of chat sessions with message counts."""
    db: Session = SessionLocal()
    try:
        sessions = db.query(SessionModel).order_by(SessionModel.created_at.desc()).all()
        payload = [collect_chat_summary(db, s) for s in sessions]
        return JSONResponse(payload)
    finally:
        db.close()


@router.get("/admin/api/sessions/{session_id}")
def api_get_session(session_id: str, admin: str = Depends(get_current_admin)):
    """Return full chat history for the given session."""
    db: Session = SessionLocal()
    try:
        session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return JSONResponse(collect_chat_messages(db, session))
    finally:
        db.close()


@router.post("/admin/api/restart")
def api_restart_server(admin: str = Depends(get_current_admin)):
    """Restart the API server and return JSON response."""
    # Reuse the logic from the HTML version but return JSON
    restart_api_server(admin)
    return JSONResponse({"message": "API server restarted."})


@router.get("/admin/api/status")
def api_status(admin: str = Depends(get_current_admin)):
    """Return API port, running state and session count."""
    load_dotenv(ENV_PATH)
    port = os.getenv("PORT", "8000")
    process_state = (
        "running" if api_process and api_process.poll() is None else "stopped"
    )
    db: Session = SessionLocal()
    try:
        session_count = db.query(SessionModel).count()
    finally:
        db.close()
    return JSONResponse(
        {
            "port": port,
            "process": process_state,
            "sessions": session_count,
        }
    )


def _tail_log(path: str, lines: int) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            data = f.readlines()
        return "".join(data[-lines:])
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Log file not found")


@router.get("/admin/api/logs")
def api_logs(
    lines: int = 100, admin: str = Depends(get_current_admin)
):
    """Return last N lines from the log file."""
    load_dotenv(ENV_PATH)
    log_path = os.getenv("LOG_PATH", LOG_PATH)
    content = _tail_log(log_path, lines)
    return PlainTextResponse(content)


@router.get("/admin/api/usage")
def api_usage(admin: str = Depends(get_current_admin)):
    """Return usage counts for each user for today and total."""
    db: Session = SessionLocal()
    try:
        today = date.today()
        users = db.query(User).all()
        payload = [
            {
                "username": u.username,
                "day": query_usage(db, u.username, today),
                "total": query_usage(db, u.username, None),
            }
            for u in users
        ]
        return JSONResponse(payload)
    finally:
        db.close()


@router.websocket("/admin/ws")
async def admin_ws(websocket: WebSocket):
    """WebSocket connection providing live server metrics."""
    auth = websocket.headers.get("authorization")
    username = password = None
    if auth and auth.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(auth.split()[1]).decode("utf-8")
            username, password = decoded.split(":", 1)
        except Exception:
            pass
    if not username:
        username = websocket.query_params.get("username")
        password = websocket.query_params.get("password")

    if not username or not password:
        await websocket.close(code=1008)
        return

    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
    finally:
        db.close()

    if (
        not user
        or not secrets.compare_digest(password, user.password_hash)
        or not user.is_admin
    ):
        await websocket.close(code=1008)
        return

    await websocket.accept()
    ws_clients.add(websocket)
    try:
        prev_net = psutil.net_io_counters()
        interval = 5
        while True:
            cpu = psutil.cpu_percent()
            memory = psutil.virtual_memory().percent
            disk = psutil.disk_usage("/").percent
            net = psutil.net_io_counters()
            byte_diff = (net.bytes_sent - prev_net.bytes_sent) + (
                net.bytes_recv - prev_net.bytes_recv
            )
            prev_net = net
            net_mbps = byte_diff * 8 / (1_000_000 * interval)
            net_mbps = round(net_mbps, 2)
            db: Session = SessionLocal()
            try:
                users = [u.username for u in db.query(User).all()]
                today = date.today()
                day_total = query_usage_all(db, today)
                all_total = query_usage_all(db, None)
            finally:
                db.close()
            try:
                models = list_installed_models()
            except Exception:
                models = []

            load_dotenv(ENV_PATH, override=True)
            port = os.getenv("PORT", "8000")
            await websocket.send_json(
                {
                    "type": "metrics",
                    "cpu": cpu,
                    "memory": memory,
                    "network": net_mbps,
                    "disk": disk,
                    "day_total": day_total,
                    "total": all_total,
                    "users": users,
                    "models": models,
                    "port": port,
                }
            )
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(websocket)


@router.on_event("shutdown")
def cleanup_on_shutdown():
    """Terminate API process and remove log file."""
    global api_process
    if api_process and api_process.poll() is None:
        try:
            api_process.terminate()
            api_process.wait(timeout=5)
        except Exception:
            pass
        api_process = None
    if os.path.exists(LOG_PATH):
        try:
            os.remove(LOG_PATH)
        except Exception:
            pass



