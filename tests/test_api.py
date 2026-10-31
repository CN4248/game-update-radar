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
