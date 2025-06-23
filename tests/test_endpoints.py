import os
import importlib
import multiprocessing
import socket
import sys
import time
from unittest.mock import patch, MagicMock

import pytest
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# Helper to get a random free port for running test servers

def _get_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _run_server(app, port: int) -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)


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

    api_port = _get_free_port()
    admin_port = _get_free_port()

    api_proc = multiprocessing.Process(target=_run_server, args=(app.api_app.app, api_port))
    admin_proc = multiprocessing.Process(target=_run_server, args=(app.admin_app.app, admin_port))
    api_proc.start()
    admin_proc.start()
    time.sleep(1)

    yield f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{admin_port}"

    api_proc.terminate()
    admin_proc.terminate()
    api_proc.join()
    admin_proc.join()
    for p in patchers:
        p.stop()


def test_api_endpoints(clients):
    api, _ = clients
    auth = ("user", "user")

    resp = requests.get(api + "/ping", auth=auth)
    assert resp.status_code == 200
    assert resp.json()["message"] == "pong"

    resp = requests.post(api + "/chat/123", json={"model": "m", "prompt": "hi"}, auth=auth)
    assert resp.status_code == 200
    assert resp.json()["response"] == "hi"

    resp = requests.get(api + "/history/sessions", auth=auth)
    assert resp.status_code == 200
    sessions = resp.json()
    assert len(sessions) == 1

    resp = requests.get(api + "/history/123", auth=auth)
    assert resp.status_code == 200
    messages = resp.json()
    assert len(messages) == 2

    resp = requests.get(api + "/limits", auth=auth)
    assert resp.status_code == 200
    assert resp.json()["daily_limit"] == 5


def test_admin_endpoints(clients):
    api, admin = clients
    user_auth = ("user", "user")
    admin_auth = ("admin", "admin")

    requests.post(api + "/chat/abc", json={"model": "m", "prompt": "hello"}, auth=user_auth)

    resp = requests.get(admin + "/admin/api/users", auth=admin_auth)
    assert resp.status_code == 200
    assert any(u["username"] == "user" for u in resp.json())

    resp = requests.get(admin + "/admin/api/users/user", auth=admin_auth)
    assert resp.status_code == 200
    assert resp.json()["username"] == "user"

    resp = requests.post(
        admin + "/admin/api/users",
        json={"username": "temp", "password": "x", "daily_limit": 1},
        auth=admin_auth,
    )
    assert resp.status_code == 200

    resp = requests.delete(admin + "/admin/api/users/temp", auth=admin_auth)
    assert resp.status_code == 200

    resp = requests.get(admin + "/admin/api/config", auth=admin_auth)
    assert resp.status_code == 200
    resp = requests.post(
        admin + "/admin/api/config",
        json={"port": "8000", "daily_limit": "10"},
        auth=admin_auth,
    )
    assert resp.status_code == 200
    assert requests.get(admin + "/admin/api/models", auth=admin_auth).json() == ["m"]
    assert requests.get(admin + "/admin/api/models/available", auth=admin_auth).json() == ["m"]
    assert requests.get(admin + "/admin/api/models/m/variants", auth=admin_auth).json() == ["m:latest"]
    assert requests.post(admin + "/admin/api/models/m/install", auth=admin_auth).status_code == 200
    assert requests.delete(admin + "/admin/api/models/m", auth=admin_auth).status_code == 200

    resp = requests.get(admin + "/admin/api/sessions", auth=admin_auth)
    assert resp.status_code == 200
    assert any(s["session_id"] == "abc" for s in resp.json())

    resp = requests.get(admin + "/admin/api/sessions/abc", auth=admin_auth)
    assert resp.status_code == 200
    resp = requests.delete(admin + "/admin/api/sessions/abc", auth=admin_auth)
    assert resp.status_code == 200

    assert requests.post(admin + "/admin/api/restart", auth=admin_auth).status_code == 200
    assert requests.get(admin + "/admin/api/status", auth=admin_auth).status_code == 200
    assert "log" in requests.get(admin + "/admin/api/logs", auth=admin_auth).text
    assert requests.get(admin + "/admin/api/usage", auth=admin_auth).status_code == 200
