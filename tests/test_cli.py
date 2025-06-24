import os
import sys
import subprocess
import sqlite3
from pathlib import Path


def test_cli_initial_setup(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    db_file = tmp_path / "test.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_file}"
    env["LOG_PATH"] = str(tmp_path / "app.log")
    env["PYTHONPATH"] = str(repo_root)

    code = f"""
import runpy, typer, subprocess, webbrowser
inputs = iter(['admin', 'pass', '8123', '8124'])
typer.prompt = lambda *a, **k: next(inputs)
class Dummy:
    def wait(self): pass
    def poll(self): return 0
    def terminate(self): pass
subprocess.Popen = lambda *a, **k: Dummy()
webbrowser.open = lambda *a, **k: None
runpy.run_path('{str(repo_root / 'cli.py').replace('\\', '\\\\')}', run_name='__main__')
"""

    subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, check=True)

    env_file = tmp_path / ".env"
    assert env_file.exists()
    content = env_file.read_text()
    assert "ADMIN_PORT='8123'" in content
    assert "PORT='8124'" in content

    conn = sqlite3.connect(db_file)
    row = conn.execute("SELECT username, is_admin FROM users").fetchone()
    conn.close()
    assert row[0] == 'admin'
    assert bool(row[1]) is True

    env_file.unlink()
    db_file.unlink()
    log_path = tmp_path / "app.log"
    if log_path.exists():
        log_path.unlink()
