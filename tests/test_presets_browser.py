"""Official-API presets and the Browserless client (no network in tests)."""
from __future__ import annotations

import json

import pytest

from app.scanner import browser as browser_mod
from app.scanner.extract import extract_items
from app.scanner.presets import PRESETS, get_preset


def _extract(payload, preset):
    result = extract_items(
        json.dumps(payload, ensure_ascii=False),
        preset["url"],
        strategy=preset["strategy"],
        selectors=preset["selectors"],
        content_type="application/json",
    )
    assert result.items
    return result.items


def test_wuthering_official_json_preset():
    preset = get_preset("wuthering")
    assert preset and preset["verified"] and preset["strategy"] == "json"
    items = _extract(
        [{"articleId": 5354, "articleTitle": "3.6 版本内容说明", "startTime": "2026-08-20 10:00:00"}],
        preset,
    )
    assert items[0].title == "3.6 版本内容说明"
    assert items[0].url == "https://mc.kurogames.com/main/news/detail/5354"
    assert items[0].published_at is not None


def test_arknights_official_json_keeps_leading_zero():
    preset = get_preset("arknights")
    assert preset and preset["verified"]
    items = _extract(
        {"code": 0, "data": {"list": [
            {"cid": "0799", "title": "制作组通讯#70期", "displayTime": 1792227600},
        ]}},
        preset,
    )
    assert items[0].url == "https://ak.hypergryph.com/news/0799"
    assert items[0].title == "制作组通讯#70期"


def test_gamekee_bluearchive_preset_uses_page_url_and_api_headers():
    preset = get_preset("gamekee_ba")
    assert preset and preset["verified"] and preset["strategy"] == "json"
    assert preset["url"] == "https://www.gamekee.com/ba/notice"
    assert preset["selectors"]["fetch_headers"]["game-alias"] == "ba"
    items = _extract(
        {"code": 0, "data": [
            {"id": 724782, "title": "【日服】更新公告（北京时间 10/21 10:00）", "created_at": 1792499031, "summary": "内容更新"},
        ]},
        preset,
    )
    assert items[0].url == "https://www.gamekee.com/ba/724782.html"
    assert items[0].title.startswith("【日服】更新公告")


def test_bluearchive_official_json_preset():
    preset = get_preset("bluearchive")
    assert preset and preset["verified"]
    items = _extract(
        {"code": 0, "data": {"rows": [
            {"id": 1983, "title": "限时活动预告", "publishTime": 1792033200000},
        ]}},
        preset,
    )
    assert items[0].url == "https://bluearchive-cn.com/news/1983"
    assert items[0].published_at is not None


def test_same_site_guard_rejects_cross_host_rendering():
    assert browser_mod.same_site("https://www.gamekee.com/ba/notice", "https://gamekee.com/ba/notice")
    assert not browser_mod.same_site("https://mc.kurogames.com/main/news", "https://www.kurogames.com/main/news")
    assert not browser_mod.same_site("https://www.gamekee.com/ba/notice", "http://127.0.0.1:8902/shell.html")
    assert not browser_mod.same_site("https://gamekee.com", "https://evilgamekee.com")


def test_all_verified_presets_are_well_formed():
    keys = {p["key"] for p in PRESETS}
    assert {"kards", "genshin", "starrail", "zzz", "wuthering", "arknights", "bluearchive"} <= keys
    for preset in PRESETS:
        assert preset["url"].startswith("http")
        assert preset["strategy"] in {"auto", "html", "rsc", "json", "api"}
        if preset["verified"]:
            assert preset.get("notes")


class _FakeResponse:
    status_code = 200
    headers = {"content-type": "text/html", "x-response-code": "200"}
    content = b"<html><title>Rendered</title><body>ok</body></html>"
    encoding = "utf-8"
    text = content.decode()

    def __init__(self, status=200, body=None):
        self.status_code = status
        self.content = body if body is not None else self.content
        self.text = self.content.decode()


class _FakeClient:
    last_payload = None

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, json=None):
        _FakeClient.last_payload = json
        return _FakeResponse()


def test_browser_render_posts_to_content(monkeypatch):
    monkeypatch.setattr(
        browser_mod, "browser_settings",
        lambda: {"enabled": True, "url": "http://127.0.0.1:3000", "wait_ms": 500, "timeout_seconds": 20, "token": ""},
    )
    monkeypatch.setattr(browser_mod.httpx, "Client", _FakeClient)
    result = browser_mod.render("https://example.com")
    assert result.status == 200
    assert "Rendered" in result.text
    assert _FakeClient.last_payload["url"] == "https://example.com"
    assert _FakeClient.last_payload["gotoOptions"]["waitUntil"] == "networkidle2"


def test_browser_render_rejects_target_http_error(monkeypatch):
    monkeypatch.setattr(
        browser_mod, "browser_settings",
        lambda: {"enabled": True, "url": "http://127.0.0.1:3000", "wait_ms": 0, "timeout_seconds": 5, "token": ""},
    )

    class BadClient(_FakeClient):
        def post(self, url, json=None):
            class BadResponse(_FakeResponse):
                headers = {"content-type": "text/html", "x-response-code": "403"}

            return BadResponse(body=b"<html>blocked</html>")

    monkeypatch.setattr(browser_mod.httpx, "Client", BadClient)
    with pytest.raises(browser_mod.BrowserError):
        browser_mod.render("https://example.com")


def test_engine_uses_browser_when_static_extract_finds_nothing(tmp_path, monkeypatch):
    from app import db, settings
    from app.scanner import engine
    from app.scanner.fetch import FetchResult

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "radar.db")
    monkeypatch.setattr(settings, "SECRET_PATH", tmp_path / "secret.key")
    db.init_db()
    with db.get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO sources(name,url,strategy,interval_minutes,enabled,use_proxy,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            ("JS 壳站", "https://example.com/news", "auto", 60, 0, 0, "new",
             "2026-10-21T00:00:00Z", "2026-10-21T00:00:00Z"),
        )
        source_id = cur.lastrowid

    shell = "<html><head><title>Shell</title></head><body><div id=app></div>"
    rendered = """<html><head><title>Rendered</title></head><body>
      <div class="card"><a href="/news/1">版本更新公告</a><time>2026-10-01</time></div>
      <div class="card"><a href="/news/2">周末活动公告</a><time>2026-10-02</time></div>
    </body></html>"""

    def fake_fetch(_source, _selectors, timeout=None):
        return FetchResult("https://example.com/news", "https://example.com/news", 200, shell, "text/html", 10)

    def fake_render(_url, wait_ms=0, timeout=0):
        return FetchResult("https://example.com/news", "https://example.com/news", 200, rendered, "text/html", 30)

    def fail_repair(*_args, **_kwargs):
        raise AssertionError("AI repair should not run when the browser succeeds")

    monkeypatch.setattr(engine, "fetch_source", fake_fetch)
    monkeypatch.setattr(engine, "render_page", fake_render)
    monkeypatch.setattr(engine, "repair_source", fail_repair)
    monkeypatch.setattr(engine, "browser_settings", lambda: {
        "enabled": True, "auto_render": True, "wait_ms": 10, "timeout_seconds": 5,
    })

    result = engine.scan_source(source_id)
    assert result["ok"] is True, result
    assert result["items_found"] == 2
    assert result["browser"]["ok"] is True
    saved = db.get_source(source_id)
    selectors = db.json_load(saved["selectors"], {})
    assert selectors["_render"]["ok_at"]


def test_engine_rejects_rendered_page_from_another_host(tmp_path, monkeypatch):
    from app import db, settings
    from app.scanner import engine
    from app.scanner.fetch import FetchResult

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "radar.db")
    monkeypatch.setattr(settings, "SECRET_PATH", tmp_path / "secret.key")
    db.init_db()
    with db.get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO sources(name,url,strategy,interval_minutes,enabled,use_proxy,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            ("跨站渲染", "https://example.com/news", "auto", 60, 0, 0, "new",
             "2026-10-21T00:00:00Z", "2026-10-21T00:00:00Z"),
        )
        source_id = cur.lastrowid

    shell = "<html><head><title>Shell</title></head><body><div id=app></div></body></html>"
    rendered = '<html><body><a href="/news/1">假公告</a></body></html>'

    monkeypatch.setattr(engine, "fetch_source", lambda *_a, **_k: FetchResult(
        "https://example.com/news", "https://example.com/news", 200, shell, "text/html", 5))
    monkeypatch.setattr(engine, "render_page", lambda *_a, **_k: FetchResult(
        "https://example.com/news", "https://evil.example/blocked", 200, rendered, "text/html", 20))
    monkeypatch.setattr(engine, "repair_source", lambda *_a, **_k: {
        "ok": False, "error": "no strategy", "attempts": [], "skipped": False,
    })
    monkeypatch.setattr(engine, "browser_settings", lambda: {
        "enabled": True, "auto_render": True, "wait_ms": 10, "timeout_seconds": 5,
    })

    result = engine.scan_source(source_id)
    assert result["ok"] is False
    assert "浏览器最终地址与监控源不一致" in " ".join(result.get("notes") or [])
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM items WHERE source_id=?", (source_id,)).fetchone()[0] == 0
