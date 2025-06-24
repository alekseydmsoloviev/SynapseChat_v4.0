import os
import importlib
import sys
import base64
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import WebSocketDisconnect, HTTPException

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

@pytest.fixture(scope="module")
def clients(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("data")
    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["LOG_PATH"] = str(tmp_path / "test.log")

    import app.database as database
    importlib.reload(database)
    from app.database import Base, engine, SessionLocal
    from app import models  # ensure models are registered

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    from app.models import User

    db = SessionLocal()
    db.add(User(username="admin", password_hash="admin", is_admin=True, daily_limit=0))
    db.add(User(username="user", password_hash="user", is_admin=False, daily_limit=5))
    db.commit()
    db.close()

    patchers = [
        patch("app.utils.ollama.chat", return_value="hi"),
        patch("app.utils.ollama.list_installed_models", return_value=["m"]),
        patch("app.utils.ollama.list_remote_base_models", return_value=["m"]),
        patch("app.utils.ollama.list_model_variants", return_value=["m:latest"]),
        patch("app.utils.ollama.install_model"),
        patch("app.utils.ollama.remove_model"),
        patch("app.routers.admin.start_api_server"),
        patch("app.routers.admin.restart_api_server"),
        patch("app.routers.admin.set_key"),
        patch("app.routers.admin._tail_log", return_value="log"),
        patch("app.routers.admin.subprocess.Popen", MagicMock()),
        patch("app.routers.admin.subprocess.check_output", return_value=""),
        patch("app.routers.admin.subprocess.run", return_value=MagicMock(returncode=0)),
    ]
    for p in patchers:
        p.start()

    import app.api_app
    import app.admin_app
    importlib.reload(app.api_app)
    importlib.reload(app.admin_app)

    api_client = TestClient(app.api_app.app)
    admin_client = TestClient(app.admin_app.app)

    yield api_client, admin_client

    api_client.close()
    admin_client.close()
    for p in patchers:
        p.stop()


def test_api_endpoints(clients):
    api, _ = clients
    auth = ("user", "user")

    resp = api.get("/ping", auth=auth)
    assert resp.status_code == 200
    assert resp.json()["message"] == "pong"

    resp = api.post("/chat/123", json={"model": "m", "prompt": "hi"}, auth=auth)
    assert resp.status_code == 200
    assert resp.json()["response"] == "hi"

    resp = api.get("/history/sessions", auth=auth)
    assert resp.status_code == 200
    sessions = resp.json()
    assert len(sessions) == 1

    resp = api.get("/history/123", auth=auth)
    assert resp.status_code == 200
    messages = resp.json()
    assert len(messages) == 2

    resp = api.get("/limits", auth=auth)
    assert resp.status_code == 200
    assert resp.json()["daily_limit"] == 5


def test_admin_endpoints(clients):
    api, admin = clients
    user_auth = ("user", "user")
    admin_auth = ("admin", "admin")

    api.post("/chat/abc", json={"model": "m", "prompt": "hello"}, auth=user_auth)

    resp = admin.get("/admin/api/users", auth=admin_auth)
    assert resp.status_code == 200
    assert any(u["username"] == "user" for u in resp.json())

    resp = admin.get("/admin/api/users/user", auth=admin_auth)
    assert resp.status_code == 200
    assert resp.json()["username"] == "user"

    resp = admin.post(
        "/admin/api/users",
        json={"username": "temp", "password": "x", "daily_limit": 1},
        auth=admin_auth,
    )
    assert resp.status_code == 200

    resp = admin.delete("/admin/api/users/temp", auth=admin_auth)
    assert resp.status_code == 200

    resp = admin.get("/admin/api/config", auth=admin_auth)
    assert resp.status_code == 200
    resp = admin.post(
        "/admin/api/config",
        json={"port": "8000", "daily_limit": "10"},
        auth=admin_auth,
    )
    assert resp.status_code == 200

    assert admin.get("/admin/api/models", auth=admin_auth).json() == ["m"]
    assert admin.get("/admin/api/models/available", auth=admin_auth).json() == ["m"]
    assert admin.get("/admin/api/models/m/variants", auth=admin_auth).json() == ["m:latest"]
    assert admin.post("/admin/api/models/m/install", auth=admin_auth).status_code == 200
    assert admin.delete("/admin/api/models/m", auth=admin_auth).status_code == 200

    resp = admin.get("/admin/api/sessions", auth=admin_auth)
    assert resp.status_code == 200
    assert any(s["session_id"] == "abc" for s in resp.json())

    resp = admin.get("/admin/api/sessions/abc", auth=admin_auth)
    assert resp.status_code == 200
    resp = admin.delete("/admin/api/sessions/abc", auth=admin_auth)
    assert resp.status_code == 200

    assert admin.post("/admin/api/restart", auth=admin_auth).status_code == 200
    assert admin.get("/admin/api/status", auth=admin_auth).status_code == 200
    assert "log" in admin.get("/admin/api/logs", auth=admin_auth).text
    assert admin.get("/admin/api/usage", auth=admin_auth).status_code == 200


def test_admin_wrong_password(clients):
    _, admin = clients
    resp = admin.get("/admin/api/users", auth=("admin", "wrong"))
    assert resp.status_code == 401


def test_admin_non_admin_user(clients):
    _, admin = clients
    resp = admin.get("/admin/api/users", auth=("user", "user"))
    assert resp.status_code == 403

def test_delete_history_session(clients):
    api, _ = clients
    auth = ("user", "user")

    session_id = "deltest"
    # Create a new chat session
    resp = api.post(f"/chat/{session_id}", json={"model": "m", "prompt": "hi"}, auth=auth)
    assert resp.status_code == 200

    # Ensure session exists
    resp = api.get(f"/history/{session_id}", auth=auth)
    assert resp.status_code == 200

    # Delete the session
    resp = api.delete(f"/history/{session_id}", auth=auth)
    assert resp.status_code == 200

    # Verify session and messages removed
    resp = api.get(f"/history/{session_id}", auth=auth)
    assert resp.status_code == 404
    resp = api.get("/history/sessions", auth=auth)
    assert resp.status_code == 200
    assert session_id not in [s["session_id"] for s in resp.json()]


def test_daily_rate_limit(clients):
    api, _ = clients
    auth = ("user", "user")

    from datetime import date
    from app.database import SessionLocal
    from app.models import RateLimit, User

    db = SessionLocal()
    user = db.query(User).filter(User.username == "user").first()
    limit = user.daily_limit
    rl = (
        db.query(RateLimit)
        .filter(RateLimit.username == "user", RateLimit.date == date.today())
        .first()
    )
    start = rl.count if rl else 0
    db.close()

    for i in range(limit - start):
        resp = api.post(f"/chat/limit{i}", json={"model": "m", "prompt": "hi"}, auth=auth)
        assert resp.status_code == 200

    resp = api.post("/chat/overflow", json={"model": "m", "prompt": "hi"}, auth=auth)
    assert resp.status_code == 429


def test_global_rate_limit(clients):
    api, _ = clients

    from app.database import SessionLocal
    from app.models import User
    from unittest.mock import patch

    db = SessionLocal()
    db.add(User(username="glob", password_hash="glob", is_admin=False, daily_limit=100))
    db.commit()
    db.close()

    auth = ("glob", "glob")

    with patch("app.routers.chat.get_global_limit", return_value=6):
        resp = api.post("/chat/g1", json={"model": "m", "prompt": "hi"}, auth=auth)
        assert resp.status_code == 200

        resp = api.post("/chat/g2", json={"model": "m", "prompt": "hi"}, auth=auth)
        assert resp.status_code == 429


def test_admin_ws(clients):
    _, admin = clients
    auth = base64.b64encode(b"admin:admin").decode()
    net1 = MagicMock(bytes_sent=0, bytes_recv=0)
    net2 = MagicMock(bytes_sent=1024, bytes_recv=2048)

    async def fake_sleep(_):
        raise WebSocketDisconnect()

    with (
        patch("app.routers.admin.psutil.cpu_percent", return_value=1.0),
        patch("app.routers.admin.psutil.virtual_memory", return_value=MagicMock(percent=2.0)),
        patch("app.routers.admin.psutil.disk_usage", return_value=MagicMock(percent=3.0)),
        patch("app.routers.admin.psutil.net_io_counters", side_effect=[net1, net2]),
        patch("app.routers.admin.asyncio.sleep", side_effect=fake_sleep),
    ):
        with admin.websocket_connect(
            "/admin/ws", headers={"Authorization": f"Basic {auth}"}
        ) as ws:
            data = ws.receive_json()

    assert data["type"] == "metrics"
    for field in [
        "cpu",
        "memory",
        "network",
        "disk",
        "day_total",
        "total",
        "users",
        "models",
        "port",
    ]:
        assert field in data


def test_mobile_ws(clients):
    api, _ = clients
    async def fake_sleep(_):
        raise WebSocketDisconnect()

    with patch("app.routers.mobile.asyncio.sleep", side_effect=fake_sleep):
        with api.websocket_connect("/ws/mobile") as ws:
            data = ws.receive_json()

    assert "users" in data
    assert "chats" in data


def test_admin_logs_not_found(clients, tmp_path):
    _, admin = clients
    auth = ("admin", "admin")

    missing = tmp_path / "no.log"
    prev = os.environ.get("LOG_PATH")
    os.environ["LOG_PATH"] = str(missing)

    def real_tail(path: str, lines: int) -> str:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                data = f.readlines()
            return "".join(data[-lines:])
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Log file not found")

    with patch("app.routers.admin._tail_log", new=real_tail):
        resp = admin.get("/admin/api/logs", auth=auth)

    if prev is not None:
        os.environ["LOG_PATH"] = prev
    else:
        os.environ.pop("LOG_PATH", None)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Log file not found"


def test_model_install_error(clients):
    _, admin = clients
    auth = ("admin", "admin")
    with patch("app.routers.admin.install_model", side_effect=RuntimeError("boom")):
        resp = admin.post("/admin/api/models/m/install", auth=auth)

    assert resp.status_code == 500
    assert resp.json()["detail"] == "boom"


def test_model_remove_error(clients):
    _, admin = clients
    auth = ("admin", "admin")
    with patch("app.routers.admin.remove_model", side_effect=RuntimeError("boom")):
        resp = admin.delete("/admin/api/models/m", auth=auth)

    assert resp.status_code == 500
    assert resp.json()["detail"] == "boom"
