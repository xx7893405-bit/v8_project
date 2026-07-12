"""Tiny read-only dashboard for the Oracle paper-strategy jobs."""

from __future__ import annotations

import json
import os
import subprocess
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).parent / "dashboard"
HOST = os.getenv("V8_DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.getenv("V8_DASHBOARD_PORT", "8787"))
SSH_HOST = os.getenv("V8_SSH_HOST", "ubuntu@140.245.87.238")
SSH_KEY = Path(os.getenv("V8_SSH_KEY", "~/Downloads/ssh-key-2026-07-10.key")).expanduser()
REMOTE_COMMAND = r"""python3 - <<'PY'
import glob, json, subprocess
timers = {}
for name in ('nfe-v2-strategy.timer', 'nfe-v4-strategy.timer'):
    show = subprocess.run(
        ['systemctl', 'show', name, '--property=ActiveState,SubState,NextElapseUSecRealtime'],
        text=True, capture_output=True
    )
    timers[name] = dict(line.split('=', 1) for line in show.stdout.splitlines() if '=' in line)
accounts = []
for path in glob.glob('/opt/v8_project/runtime/accounts/*/state.json'):
    try:
        with open(path) as handle: accounts.append(json.load(handle))
    except (OSError, json.JSONDecodeError): pass
print(json.dumps({'timers': timers, 'accounts': accounts}))
PY"""


def remote_status() -> dict:
    if not SSH_KEY.exists():
        raise RuntimeError(f"找不到 SSH 金鑰：{SSH_KEY}")
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12", "-i", str(SSH_KEY), SSH_HOST, REMOTE_COMMAND],
        text=True, capture_output=True, timeout=20,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "SSH 連線失敗")
    return json.loads(result.stdout)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self) -> None:
        if self.path != "/api/status":
            return super().do_GET()
        try:
            self.send_json({"ok": True, **remote_status()})
        except Exception as error:
            self.send_json({"ok": False, "error": str(error)}, 502)

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print(f"V8 dashboard: http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
