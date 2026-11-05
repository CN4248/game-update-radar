import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app import db, settings

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "radar.db")
    monkeypatch.setattr(settings, "SECRET_PATH", tmp_path / "secret.key")
    db.init_db()

    from app import main

    monkeypatch.setattr(main.scheduler, "reconcile", lambda: None)
    return TestClient(main.app)


def test_health_and_seed(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    sources = client.get("/api/sources").json()["sources"]
    assert any(s["name"] == "KARDS" for s in sources)
    assert client.get("/").status_code == 200


def test_source_crud(client):
    payload = {
        "name": "测试源",
        "url": "https://example.com/news",
        "strategy": "auto",
        "interval_minutes": 30,
        "enabled": False,
    }
    created = client.post("/api/sources", json=payload)
    assert created.status_code == 201, created.text
    source_id = created.json()["id"]
    assert created.json()["next_run_at"] is None

    updated = client.put(f"/api/sources/{source_id}", json={"name": "改名源", "interval_minutes": 45})
    assert updated.status_code == 200
    assert updated.json()["name"] == "改名源"

    assert client.delete(f"/api/sources/{source_id}").status_code == 200
    assert client.get(f"/api/sources/{source_id}").status_code == 404


def test_settings_secret_roundtrip_and_masking(client):
    response = client.put(
        "/api/settings/ai",
        json={"values": {"enabled": True, "api_key": "sk-test-123456", "model": "deepseek-chat"}},
    )
    assert response.status_code == 200
    data = client.get("/api/settings").json()["settings"]["ai"]
    assert data["api_key"] != "sk-test-123456"
    assert data["api_key"].endswith("3456")

    # A masked PUT keeps the existing secret rather than overwriting it.
    client.put("/api/settings/ai", json={"values": {"api_key": data["api_key"]}})
    stored = client.get("/api/settings").json()["settings"]["ai"]["api_key"]
    assert stored == data["api_key"]


def test_notify_settings_and_item_category_filter(client):
    data = client.get("/api/settings").json()
    assert len(data["alert_categories"]) == 8
    assert data["settings"]["notify"]["mode"] == "update_only"

    saved = client.put(
        "/api/settings/notify",
        json={"values": {"mode": "selected", "categories": ["event", "maintenance"]}},
    )
    assert saved.status_code == 200
    notify = client.get("/api/settings").json()["settings"]["notify"]
    assert notify == {"mode": "selected", "categories": ["event", "maintenance"]}

    from app import db

    with db.get_conn() as conn:
        source_id = conn.execute("SELECT id FROM sources LIMIT 1").fetchone()["id"]
        conn.execute(
            """INSERT INTO items(source_id,external_id,title,url,category,is_update,confidence,first_seen_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (source_id, "cat-1", "活动公告", "https://example.com/event", "event", 0, 0.5, "2026-01-01T00:00:00+00:00"),
        )
    events = client.get("/api/items?category=event").json()
    assert [row["title"] for row in events["items"]] == ["活动公告"]
    assert client.get("/api/items?category=version_update").json()["items"] == []


def test_incremental_respects_notify_category(client, monkeypatch):
    from datetime import datetime, timezone

    from app import db, settings
    from app.scanner import engine
    from app.scanner.classify import Classification
    from app.scanner.extract import Item

    source = db.get_source(1)
    settings.update_setting("notify", {"mode": "update_only"})
    monkeypatch.setattr(
        engine, "classify_items",
        lambda items, **kwargs: ([Classification(False, 0.8, "活动", "", "rule", "event")], {}),
    )
    monkeypatch.setattr(engine, "_dispatch_alert", lambda *args, **kwargs: True)

    def run(uid: str):
        item = Item("周末活动", "https://example.com/event", "双倍经验", datetime.now(timezone.utc), uid)
        return engine._handle_incremental(source, [item], [], force=True)

    assert run("event-1") == (1, 0)

    settings.update_setting("notify", {"mode": "selected", "categories": ["event"]})
    assert run("event-2") == (1, 1)
    with db.get_conn() as conn:
        alerts = conn.execute("SELECT COUNT(*) c FROM alerts").fetchone()["c"]
    assert alerts == 1


def test_channel_validation(client):
    bad = client.post("/api/channels", json={"name": "邮件", "type": "email", "config": {}})
    assert bad.status_code == 400
    good = client.post(
        "/api/channels",
        json={
            "name": "测试 Webhook",
            "type": "webhook",
            "config": {"url": "https://example.com/hook", "headers": {"X-Test": "1"}},
        },
    )
    assert good.status_code == 201, good.text
    assert client.delete(f"/api/channels/{good.json()['id']}").status_code == 200
