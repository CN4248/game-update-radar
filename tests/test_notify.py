import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.notify import Notification, send_channel, send_with_retries, validate_channel


NOTE = Notification(
    game="KARDS",
    title="KARDS 更新",
    summary="平衡性调整",
    url="https://example.com/news/1",
    published="2026-10-15T03:36:05+00:00",
    reason="命中更新关键词：更新",
)


def test_required_fields():
    with pytest.raises(ValueError):
        validate_channel("email", {"host": "smtp.example.com"})
    validate_channel("console", {})


def test_console_channel(monkeypatch):
    monkeypatch.setattr("app.notify.log_event", lambda *args, **kwargs: None)
    result = send_channel({"id": 1, "name": "console", "type": "console", "config": {}}, NOTE)
    assert result["ok"] is True
    assert result["status"] == "sent"


def test_unknown_and_disabled_never_raise():
    unknown = send_channel({"id": 2, "name": "x", "type": "nope", "config": {}}, NOTE)
    disabled = send_channel(
        {"id": 3, "name": "console", "type": "console", "enabled": False, "config": {}}, NOTE
    )
    assert unknown["ok"] is False
    assert disabled["status"] == "skipped"


def test_webhook_payload(monkeypatch):
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            received.update(json.loads(self.rfile.read(length)))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr("app.notify.proxy_url_for", lambda *args, **kwargs: None)
        channel = {
            "id": 9,
            "name": "hook",
            "type": "webhook",
            "config": {"url": f"http://127.0.0.1:{server.server_port}/hook"},
        }
        result = send_with_retries(channel, NOTE)
        assert result["ok"] is True
        assert received["event"] == "game_update"
        assert received["game"] == "KARDS"
        assert received["title"] == "KARDS 更新"
        assert received["url"].endswith("/news/1")
    finally:
        server.shutdown()
