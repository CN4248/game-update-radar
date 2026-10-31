"""AI strategy repair: declarative candidates must be proven before saving."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app.scanner import repair as repair_mod

PAGE = """<!doctype html><html><head><title>测试新闻</title></head><body>
  <div class="row"><span class="t">版本更新 1.0</span><span class="u" data-url="/news/1"></span><time>2026-10-01</time></div>
  <div class="row"><span class="t">周末活动公告</span><span class="u" data-url="/news/2"></span><time>2026-10-02</time></div>
</body></html>"""

CANDIDATE = {
    "action": "try",
    "strategy": "html",
    "reason": "列表没有 a 标签，必须使用 data-url",
    "confidence": 0.9,
    "selectors": {
        "item": ".row", "title": ".t", "link": ".u",
        "link_attr": "data-url", "date": "time",
    },
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


@pytest.fixture()
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/news"
    finally:
        server.shutdown()
        server.server_close()


def test_custom_html_selectors_with_data_url():
    from app.scanner.extract import extract_items

    result = extract_items(PAGE, "https://example.com/news", "html", CANDIDATE["selectors"])
    assert result.strategy == "html"
    assert [i.title for i in result.items] == ["周末活动公告", "版本更新 1.0"]
    newest = next(i for i in result.items if i.title == "周末活动公告")
    assert newest.url == "https://example.com/news/2"
    assert newest.published_at.isoformat() == "2026-10-01T16:00:00+00:00"

    # AI often omits link_attr; common data-* attributes must still work.
    no_attr = {k: v for k, v in CANDIDATE["selectors"].items() if k != "link_attr"}
    fallback = extract_items(PAGE, "https://example.com/news", "html", no_attr)
    assert [i.url for i in fallback.items] == [
        "https://example.com/news/2", "https://example.com/news/1",
    ]


def test_repair_saves_only_a_proven_strategy(tmp_path, monkeypatch, site):
    from app import db, main, settings

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "radar.db")
    monkeypatch.setattr(settings, "SECRET_PATH", tmp_path / "secret.key")
    db.init_db()

    class FakeAI:
        configured = True
        model = "fake-model"

        def __init__(self, *_args, **_kwargs):
            pass

        def chat(self, *_args, **_kwargs):
            return json.dumps(CANDIDATE, ensure_ascii=False)

    monkeypatch.setattr(repair_mod, "AIClient", FakeAI)
    monkeypatch.setattr(repair_mod, "ai_settings", lambda: {
        "enabled": True, "api_key": "sk-test", "auto_repair": True,
        "repair_max_attempts": 3, "repair_cooldown_minutes": 360,
    })
    monkeypatch.setattr(main.scheduler, "reconcile", lambda: None)
    monkeypatch.setattr(main.scheduler, "scan_now", lambda _sid: True)
    client = TestClient(main.app)

    created = client.post("/api/sources", json={
        "name": "本地测试站", "url": site, "strategy": "auto",
        "interval_minutes": 60, "enabled": False,
    })
    assert created.status_code == 201, created.text
    source_id = created.json()["id"]

    response = client.post(f"/api/sources/{source_id}/repair")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ok"] is True, data
    assert data["items_found"] == 2
    assert data["queued"] is True

    saved = db.get_source(source_id)
    assert saved["strategy"] == "html"
    selectors = db.json_load(saved["selectors"], {})
    assert selectors["item"] == ".row"
    assert selectors["_repair"]["items_found"] == 2

    # A real scan now uses the saved strategy and establishes a baseline.
    from app.scanner.engine import scan_source
    result = scan_source(source_id)
    assert result["ok"] is True, result
    assert result["items_found"] == 2
    assert result["baseline"] is True
    row = next(s for s in db.list_sources() if s["id"] == source_id)
    assert row["item_count"] == 2


def test_scan_triggers_auto_repair_when_generic_extraction_is_empty(tmp_path, monkeypatch, site):
    from app import db, settings
    from app.scanner.engine import scan_source

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "radar.db")
    monkeypatch.setattr(settings, "SECRET_PATH", tmp_path / "secret.key")
    db.init_db()

    class FakeAI:
        configured = True
        model = "fake-model"

        def __init__(self, *_args, **_kwargs):
            pass

        def chat(self, *_args, **_kwargs):
            return json.dumps(CANDIDATE, ensure_ascii=False)

    monkeypatch.setattr(repair_mod, "AIClient", FakeAI)
    monkeypatch.setattr(repair_mod, "ai_settings", lambda: {
        "enabled": True, "api_key": "sk-test", "auto_repair": True,
        "repair_max_attempts": 2, "repair_cooldown_minutes": 360,
    })
    with db.get_conn() as conn:
        source_id = conn.execute(
            "INSERT INTO sources(name,url,strategy,interval_minutes,enabled,use_proxy,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("本地测试站", site, "auto", 60, 0, 0, "2026-10-21T00:00:00Z", "2026-10-21T00:00:00Z"),
        ).lastrowid

    result = scan_source(source_id)
    assert result["ok"] is True, result
    assert result["baseline"] is True
    assert result["items_found"] == 2
    assert result.get("repair", {}).get("ok") is True
    saved = db.get_source(source_id)
    assert saved["strategy"] == "html"


def test_failed_repair_keeps_old_strategy_and_sets_cooldown(tmp_path, monkeypatch, site):
    from app import db, settings

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "radar.db")
    monkeypatch.setattr(settings, "SECRET_PATH", tmp_path / "secret.key")
    db.init_db()

    bad = dict(CANDIDATE)
    bad["selectors"] = {**CANDIDATE["selectors"], "item": ".does-not-exist"}

    class FakeAI:
        configured = True
        model = "fake-model"

        def __init__(self, *_args, **_kwargs):
            pass

        def chat(self, *_args, **_kwargs):
            return json.dumps(bad, ensure_ascii=False)

    monkeypatch.setattr(repair_mod, "AIClient", FakeAI)
    monkeypatch.setattr(repair_mod, "ai_settings", lambda: {
        "enabled": True, "api_key": "sk-test", "auto_repair": True,
        "repair_max_attempts": 1, "repair_cooldown_minutes": 360,
    })
    old_selectors = {"item": ".old-row", "title": ".old-title"}
    with db.get_conn() as conn:
        source_id = conn.execute(
            "INSERT INTO sources(name,url,strategy,selectors,interval_minutes,enabled,use_proxy,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            ("本地测试站", site, "html", json.dumps(old_selectors), 60, 0, 0,
             "2026-10-21T00:00:00Z", "2026-10-21T00:00:00Z"),
        ).lastrowid

    result = repair_mod.repair_source(db.get_source(source_id), force=True)
    assert result["ok"] is False
    assert len(result["attempts"]) == 1
    saved = db.get_source(source_id)
    assert saved["strategy"] == "html"
    selectors = db.json_load(saved["selectors"], {})
    assert selectors["item"] == ".old-row"
    assert selectors["_repair"]["failed_at"]

    skipped = repair_mod.repair_source(db.get_source(source_id))
    assert skipped["skipped"] is True
    assert skipped["attempts"] == []


def test_scan_source_auto_repairs_when_empty(tmp_path, monkeypatch, site):
    from app import db, settings
    from app.scanner import engine

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "radar.db")
    monkeypatch.setattr(settings, "SECRET_PATH", tmp_path / "secret.key")
    db.init_db()

    class FakeAI:
        configured = True
        model = "fake-model"

        def __init__(self, *_args, **_kwargs):
            pass

        def chat(self, *_args, **_kwargs):
            return json.dumps(CANDIDATE, ensure_ascii=False)

    monkeypatch.setattr(repair_mod, "AIClient", FakeAI)
    monkeypatch.setattr(repair_mod, "ai_settings", lambda: {
        "enabled": True, "api_key": "sk-test", "auto_repair": True,
        "repair_max_attempts": 1, "repair_cooldown_minutes": 360,
    })
    with db.get_conn() as conn:
        source_id = conn.execute(
            "INSERT INTO sources(name,url,strategy,selectors,interval_minutes,enabled,use_proxy,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            ("自动修复测试", site, "auto", "{}", 60, 1, 0,
             "2026-10-21T00:00:00Z", "2026-10-21T00:00:00Z"),
        ).lastrowid

    result = engine.scan_source(source_id)
    assert result["ok"] is True
    saved = db.get_source(source_id)
    assert saved["strategy"] == "html"
    assert saved["baseline_done"] == 1
    assert json.loads(saved["selectors"])["_repair"]["items_found"] == 2
    with db.get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM items WHERE source_id=?", (source_id,)).fetchone()[0]
    assert count == 2
