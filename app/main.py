"""FastAPI application: API, WebUI hosting, lifespan."""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import db, notify, settings
from .config import APP_NAME, APP_VERSION, KEEP, MASK, WEB_DIR
from .models import (
    BrowserTestRequest, ChannelCreate, ChannelUpdate, FeasibilityRequest, PresetInstall,
    ProxyTestRequest, SettingsPatch, SourceCreate, SourceUpdate, TestAIRequest,
)
from .scanner import browser as browser_scanner
from .scanner import presets, probe
from .scanner.ai import AIClient, AIError
from .scanner.engine import resend_alert
from .scanner.repair import public_attempts, repair_source
from .scheduler import scheduler
from .timeutil import now_iso

logger = logging.getLogger(__name__)

CHANNEL_TYPES: dict[str, dict[str, Any]] = {
    "email": {
        "label": "邮件 SMTP", "icon": "mail",
        "fields": [
            {"key": "host", "label": "SMTP 服务器", "required": True, "placeholder": "smtp.qq.com"},
            {"key": "port", "label": "端口", "type": "number", "placeholder": "587"},
            {"key": "username", "label": "用户名", "placeholder": "you@example.com"},
            {"key": "password", "label": "密码/授权码", "type": "secret"},
            {"key": "from_addr", "label": "发件地址", "required": True, "placeholder": "you@example.com"},
            {"key": "to_addr", "label": "收件地址", "required": True, "placeholder": "me@example.com，多个用逗号分隔"},
            {"key": "encryption", "label": "加密方式", "type": "select", "options": ["starttls", "ssl", "none"]},
            {"key": "subject_prefix", "label": "主题前缀", "placeholder": "[游戏更新]"},
        ],
    },
    "telegram": {
        "label": "Telegram Bot", "icon": "send",
        "fields": [
            {"key": "bot_token", "label": "Bot Token", "type": "secret", "required": True},
            {"key": "chat_id", "label": "Chat ID", "required": True},
            {"key": "api_base", "label": "API 地址", "placeholder": "https://api.telegram.org"},
        ],
    },
    "webhook": {
        "label": "通用 Webhook", "icon": "webhook",
        "fields": [
            {"key": "url", "label": "Webhook URL", "required": True},
            {"key": "method", "label": "方法", "type": "select", "options": ["POST", "PUT", "GET"]},
            {"key": "body_template", "label": "自定义 JSON 模板（可选）", "type": "textarea",
             "placeholder": "留空发送内置 JSON；支持 {{title}} {{game}} {{url}} 等变量"},
        ],
    },
    "bark": {
        "label": "Bark (iOS)", "icon": "bell",
        "fields": [
            {"key": "device_key", "label": "Device Key", "type": "secret", "required": True},
            {"key": "server", "label": "服务器", "placeholder": "https://api.day.app"},
            {"key": "group", "label": "分组", "placeholder": "游戏更新"},
        ],
    },
    "serverchan": {
        "label": "Server酱", "icon": "server",
        "fields": [{"key": "sendkey", "label": "SendKey", "type": "secret", "required": True}],
    },
    "pushplus": {
        "label": "PushPlus 微信", "icon": "wechat",
        "fields": [
            {"key": "token", "label": "Token", "type": "secret", "required": True},
            {"key": "topic", "label": "群组编码（可选）"},
        ],
    },
    "ntfy": {
        "label": "ntfy", "icon": "radio",
        "fields": [
            {"key": "topic", "label": "Topic", "required": True},
            {"key": "server", "label": "服务器", "placeholder": "https://ntfy.sh"},
            {"key": "token", "label": "访问令牌（可选）", "type": "secret"},
            {"key": "priority", "label": "优先级", "type": "select", "options": ["default", "high", "urgent", "low"]},
        ],
    },
    "twilio": {
        "label": "Twilio 短信", "icon": "message",
        "fields": [
            {"key": "account_sid", "label": "Account SID", "required": True},
            {"key": "auth_token", "label": "Auth Token", "type": "secret", "required": True},
            {"key": "from_number", "label": "发送号码", "required": True, "placeholder": "+12025550123"},
            {"key": "to_number", "label": "接收号码", "required": True, "placeholder": "+8613800000000"},
        ],
    },
    "console": {"label": "运行日志（本地验证）", "icon": "terminal", "fields": []},
}

AI_PROVIDERS = [
    {"key": "deepseek", "label": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    {"key": "openai", "label": "OpenAI 兼容", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    {"key": "anthropic", "label": "Anthropic Claude", "base_url": "https://api.anthropic.com/v1", "model": "claude-3-5-haiku-latest"},
    {"key": "ollama", "label": "Ollama 本地", "base_url": "http://127.0.0.1:11434", "model": "qwen2.5:7b"},
    {"key": "custom", "label": "自定义兼容接口", "base_url": "", "model": ""},
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    scheduler.start()
    logger.info("%s v%s started", APP_NAME, APP_VERSION)
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan, docs_url="/api/docs", redoc_url=None)


# --------------------------------------------------------------------------- helpers
def _source_out(row: dict) -> dict:
    out = dict(row)
    out["selectors"] = db.json_load(out.get("selectors"), {})
    out["feasibility"] = db.json_load(out.get("feasibility"), {})
    return out


def _source_with_next(row: dict | None) -> dict | None:
    if not row:
        return None
    out = _source_out(row)
    out["next_run_at"] = _next_runs().get(int(out["id"]))
    return out


def _next_runs() -> dict[int, str]:
    out: dict[int, str] = {}
    try:
        for job in scheduler.scheduler.get_jobs():
            if job.id.startswith("scan:") and job.next_run_time:
                out[int(job.id.split(":", 1)[1])] = job.next_run_time.astimezone(timezone.utc).isoformat()
    except Exception:  # noqa: BLE001
        pass
    return out


def _parse_json(value, fallback):
    return db.json_load(value, fallback)


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    errors = exc.errors()
    first = errors[0] if errors else {}
    loc = ".".join(str(x) for x in first.get("loc", []) if x not in ("body", "query", "path"))
    message = first.get("msg", "请求参数不合法")
    return JSONResponse(status_code=422, content={"detail": f"{loc}: {message}" if loc else message})


@app.exception_handler(Exception)
async def unhandled_handler(_: Request, exc: Exception):
    logger.exception("unhandled API error")
    db.log_event("error", "api", f"{type(exc).__name__}: {exc}")
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请查看运行日志"})


# --------------------------------------------------------------------------- health / summary
@app.get("/api/health")
def health():
    try:
        with db.get_conn() as conn:
            conn.execute("SELECT 1")
        db_state = "ok"
    except Exception as exc:  # noqa: BLE001
        logger.exception("db health check failed")
        db_state = f"error: {exc}"
    return {"status": "ok" if db_state == "ok" else "degraded", "version": APP_VERSION, "db": db_state}


@app.get("/api/summary")
def summary():
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with db.get_conn() as conn:
        sources_total = conn.execute("SELECT COUNT(*) c FROM sources").fetchone()["c"]
        sources_enabled = conn.execute("SELECT COUNT(*) c FROM sources WHERE enabled=1").fetchone()["c"]
        sources_error = conn.execute("SELECT COUNT(*) c FROM sources WHERE status IN ('error','degraded')").fetchone()["c"]
        items_total = conn.execute("SELECT COUNT(*) c FROM items").fetchone()["c"]
        updates_total = conn.execute("SELECT COUNT(*) c FROM items WHERE is_update=1").fetchone()["c"]
        updates_24h = conn.execute(
            "SELECT COUNT(*) c FROM items WHERE is_update=1 AND COALESCE(published_at, first_seen_at)>=?",
            (cutoff,),
        ).fetchone()["c"]
        alerts_total = conn.execute("SELECT COUNT(*) c FROM alerts").fetchone()["c"]
        alerts_24h = conn.execute("SELECT COUNT(*) c FROM alerts WHERE created_at>=?", (cutoff,)).fetchone()["c"]
        channels = conn.execute("SELECT COUNT(*) c FROM channels WHERE enabled=1").fetchone()["c"]
        recent_items = [dict(r) for r in conn.execute(
            """SELECT i.id,i.title,i.url,i.published_at,i.is_update,i.reason,i.first_seen_at,s.name source_name
               FROM items i JOIN sources s ON s.id=i.source_id
               ORDER BY COALESCE(i.published_at,i.first_seen_at) DESC LIMIT 6"""
        ).fetchall()]
        recent_alerts = [dict(r) for r in conn.execute(
            """SELECT a.id,a.title,a.status,a.created_at,s.name source_name
               FROM alerts a LEFT JOIN sources s ON s.id=a.source_id
               ORDER BY a.created_at DESC LIMIT 6"""
        ).fetchall()]
        source_states = [dict(r) for r in conn.execute(
            """SELECT id,name,status,last_scan_at,last_error,last_items_found,fail_count
               FROM sources ORDER BY id"""
        ).fetchall()]
    ai_cfg = settings.ai_settings()
    ai_ready = bool(ai_cfg.get("enabled")) and (
        bool(ai_cfg.get("api_key")) or "localhost" in str(ai_cfg.get("base_url")) or "127.0.0.1" in str(ai_cfg.get("base_url"))
    )
    next_runs = _next_runs()
    nearest = min(next_runs.values()) if next_runs else None
    return {
        "counts": {
            "sources": sources_total, "sources_enabled": sources_enabled, "sources_error": sources_error,
            "items": items_total, "updates": updates_total, "updates_24h": updates_24h,
            "alerts": alerts_total, "alerts_24h": alerts_24h, "channels": channels,
        },
        "recent_items": recent_items,
        "recent_alerts": recent_alerts,
        "source_states": source_states,
        "ai": {"enabled": bool(ai_cfg.get("enabled")), "ready": ai_ready,
               "provider": ai_cfg.get("provider"), "model": ai_cfg.get("model")},
        "proxy": {"enabled": bool(settings.proxy_settings().get("enabled"))},
        "scheduler": {"running": scheduler.scheduler.running, "next_run_at": nearest},
        "version": APP_VERSION,
    }


# --------------------------------------------------------------------------- sources
@app.get("/api/sources")
def list_sources():
    rows = [_source_out(r) for r in db.list_sources()]
    runs = _next_runs()
    for row in rows:
        row["next_run_at"] = runs.get(int(row["id"]))
    return {"sources": rows}


@app.get("/api/sources/{source_id}")
def get_source(source_id: int):
    row = db.get_source(source_id)
    if not row:
        raise HTTPException(404, "监控源不存在")
    out = _source_out(row)
    out["next_run_at"] = _next_runs().get(source_id)
    return out


@app.post("/api/sources", status_code=201)
def create_source(payload: SourceCreate):
    data = payload.model_dump()
    with db.get_conn() as conn:
        exists = conn.execute("SELECT id FROM sources WHERE url=?", (data["url"],)).fetchone()
        if exists:
            raise HTTPException(409, "该 URL 已存在监控源")
        ts = now_iso()
        cur = conn.execute(
            """INSERT INTO sources(name,url,strategy,interval_minutes,enabled,use_proxy,locale,
               keywords_include,keywords_exclude,selectors,feasibility,notes,status,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data["name"], data["url"], data["strategy"], data["interval_minutes"], int(data["enabled"]),
                int(data["use_proxy"]), data["locale"], data["keywords_include"], data["keywords_exclude"],
                json.dumps(data["selectors"], ensure_ascii=False), "{}", data["notes"], "idle", ts, ts,
            ),
        )
        source_id = int(cur.lastrowid)
    db.log_event("info", "source.create", f"新增监控源：{data['name']}", source_id=source_id)
    scheduler.reconcile()
    return _source_with_next(db.get_source(source_id))


@app.put("/api/sources/{source_id}")
def update_source(source_id: int, payload: SourceUpdate):
    existing = db.get_source(source_id)
    if not existing:
        raise HTTPException(404, "监控源不存在")
    patch = payload.model_dump(exclude_unset=True)
    if not patch:
        return _source_out(existing)
    if "selectors" in patch:
        patch["selectors"] = json.dumps(patch["selectors"], ensure_ascii=False)
    for bool_key in ("enabled", "use_proxy"):
        if bool_key in patch:
            patch[bool_key] = int(bool(patch[bool_key]))
    if "url" in patch and patch["url"] != existing["url"]:
        patch["baseline_done"] = 0
        patch["status"] = "idle"
        patch["last_error"] = ""
    patch["updated_at"] = now_iso()
    columns = ", ".join(f"{k}=?" for k in patch)
    with db.get_conn() as conn:
        conn.execute(f"UPDATE sources SET {columns} WHERE id=?", (*patch.values(), source_id))
    db.log_event("info", "source.update", f"更新监控源：{existing['name']}", source_id=source_id)
    scheduler.reconcile()
    return _source_with_next(db.get_source(source_id))


@app.delete("/api/sources/{source_id}")
def delete_source(source_id: int):
    existing = db.get_source(source_id)
    if not existing:
        raise HTTPException(404, "监控源不存在")
    with db.get_conn() as conn:
        conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
    db.log_event("warning", "source.delete", f"删除监控源：{existing['name']}")
    scheduler.reconcile()
    return {"ok": True}


@app.post("/api/sources/{source_id}/scan")
def scan_source_now(source_id: int):
    if not db.get_source(source_id):
        raise HTTPException(404, "监控源不存在")
    if not scheduler.scan_now(source_id):
        raise HTTPException(400, "无法启动扫描")
    return {"ok": True, "queued": True}


@app.post("/api/scan-all")
def scan_all_now():
    return {"ok": True, "queued": scheduler.scan_all_now()}


@app.post("/api/sources/{source_id}/probe")
def probe_source(source_id: int):
    row = db.get_source(source_id)
    if not row:
        raise HTTPException(404, "监控源不存在")
    result = probe.analyze(
        row["url"], row["name"], use_ai=True, use_proxy=bool(row["use_proxy"]),
        selectors=db.json_load(row.get("selectors"), {}),
        strategy=row.get("strategy") or "auto",
    )
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE sources SET feasibility=?, updated_at=? WHERE id=?",
            (json.dumps(result, ensure_ascii=False)[:20000], now_iso(), source_id),
        )
    return result


@app.post("/api/sources/{source_id}/repair")
def repair_source_now(source_id: int):
    """Ask AI to invent/prove a strategy, then queue a real scan."""
    row = db.get_source(source_id)
    if not row:
        raise HTTPException(404, "监控源不存在")
    result = repair_source(row, force=True)
    public = {k: v for k, v in result.items() if k not in ("fetched", "result")}
    public["attempts"] = public_attempts(result.get("attempts"))
    if result.get("ok"):
        public["queued"] = scheduler.scan_now(source_id)
        public["message"] = f"AI 策略已生效，识别到 {result.get('items_found', 0)} 条，正在重新扫描"
    else:
        public["message"] = result.get("error") or "AI 未能生成可用策略"
    return public


# --------------------------------------------------------------------------- items / alerts
@app.get("/api/items")
def list_items(
    source_id: int | None = None,
    only_update: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    where = ["1=1"]
    params: list[Any] = []
    if source_id is not None:
        where.append("i.source_id=?")
        params.append(source_id)
    if only_update:
        where.append("i.is_update=1")
    clause = " AND ".join(where)
    with db.get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) c FROM items i WHERE {clause}", params
        ).fetchone()["c"]
        rows = [dict(r) for r in conn.execute(
            f"""SELECT i.id,i.source_id,i.external_id,i.title,i.url,i.summary,i.published_at,
                       i.is_update,i.confidence,i.reason,i.ai_summary,i.first_seen_at,i.notified,
                       s.name source_name
                FROM items i JOIN sources s ON s.id=i.source_id
                WHERE {clause}
                ORDER BY COALESCE(i.published_at,i.first_seen_at) DESC
                LIMIT ? OFFSET ?""",
            (*params, limit, offset),
        ).fetchall()]
    return {"items": rows, "total": total}


@app.get("/api/sources/{source_id}/items")
def list_source_items(source_id: int, limit: int = Query(default=50, ge=1, le=200), offset: int = 0):
    if not db.get_source(source_id):
        raise HTTPException(404, "监控源不存在")
    with db.get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM items WHERE source_id=?", (source_id,)).fetchone()["c"]
        rows = [dict(r) for r in conn.execute(
            """SELECT id,source_id,external_id,title,url,summary,published_at,is_update,confidence,
                      reason,ai_summary,first_seen_at,notified
               FROM items WHERE source_id=? ORDER BY COALESCE(published_at,first_seen_at) DESC LIMIT ? OFFSET ?""",
            (source_id, limit, offset),
        ).fetchall()]
    return {"items": rows, "total": total}


@app.get("/api/alerts")
def list_alerts(limit: int = Query(default=50, ge=1, le=200), offset: int = 0, status: str | None = None):
    where = ["1=1"]
    params: list[Any] = []
    if status:
        where.append("a.status=?")
        params.append(status)
    clause = " AND ".join(where)
    with db.get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) c FROM alerts a WHERE {clause}", params).fetchone()["c"]
        rows = [dict(r) for r in conn.execute(
            f"""SELECT a.id,a.source_id,a.item_id,a.title,a.message,a.status,a.channel_results,
                       a.created_at,a.sent_at,s.name source_name,i.url item_url
                FROM alerts a LEFT JOIN sources s ON s.id=a.source_id LEFT JOIN items i ON i.id=a.item_id
                WHERE {clause} ORDER BY a.created_at DESC LIMIT ? OFFSET ?""",
            (*params, limit, offset),
        ).fetchall()]
    for row in rows:
        row["channel_results"] = _parse_json(row.get("channel_results"), [])
    return {"alerts": rows, "total": total}


@app.post("/api/alerts/{alert_id}/resend")
def resend(alert_id: int):
    result = resend_alert(alert_id)
    if not result.get("ok") and result.get("error"):
        raise HTTPException(400, result["error"])
    return result


# --------------------------------------------------------------------------- channels
@app.get("/api/channels")
def list_channels():
    return {"channels": settings.channels_public(), "types": CHANNEL_TYPES}


@app.post("/api/channels", status_code=201)
def create_channel(payload: ChannelCreate):
    try:
        notify.validate_channel(payload.type, payload.config)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    encrypted = json.dumps(settings.encrypt_config(payload.config), ensure_ascii=False)
    ts = now_iso()
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO channels(name,type,enabled,config,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (payload.name, payload.type, int(payload.enabled), encrypted, ts, ts),
        )
        channel_id = int(cur.lastrowid)
    db.log_event("info", "channel.create", f"新增通知渠道：{payload.name}")
    return {"id": channel_id}


@app.put("/api/channels/{channel_id}")
def update_channel(channel_id: int, payload: ChannelUpdate):
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM channels WHERE id=?", (channel_id,)).fetchone()
    if not row:
        raise HTTPException(404, "通知渠道不存在")
    row = dict(row)
    updates: dict[str, Any] = {}
    if payload.name is not None:
        updates["name"] = payload.name
    if payload.enabled is not None:
        updates["enabled"] = int(payload.enabled)
    if payload.config is not None:
        existing = settings.channel_raw(row)["config"]
        merged = settings.merge_secret_config(existing, payload.config)
        try:
            notify.validate_channel(row["type"], merged)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        updates["config"] = json.dumps(settings.encrypt_config(merged), ensure_ascii=False)
    if not updates:
        return {"ok": True}
    updates["updated_at"] = now_iso()
    columns = ", ".join(f"{k}=?" for k in updates)
    with db.get_conn() as conn:
        conn.execute(f"UPDATE channels SET {columns} WHERE id=?", (*updates.values(), channel_id))
    return {"ok": True}


@app.delete("/api/channels/{channel_id}")
def delete_channel(channel_id: int):
    with db.get_conn() as conn:
        cur = conn.execute("DELETE FROM channels WHERE id=?", (channel_id,))
    if not cur.rowcount:
        raise HTTPException(404, "通知渠道不存在")
    return {"ok": True}


@app.post("/api/channels/{channel_id}/test")
def test_channel(channel_id: int):
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM channels WHERE id=?", (channel_id,)).fetchone()
    if not row:
        raise HTTPException(404, "通知渠道不存在")
    channel = settings.channel_raw(dict(row))
    channel["enabled"] = True
    note = notify.Notification(
        game="测试游戏", title="通知渠道连通性测试",
        summary="如果你收到这条消息，说明 Game Update Radar 的通知渠道配置正确。",
        url="https://example.com/", published=now_iso(), reason="测试发送（非真实公告）",
    )
    result = notify.send_channel(channel, note)
    db.log_event("info" if result["ok"] else "error", "channel.test",
                 f"测试渠道 {row['name']}：{'成功' if result['ok'] else '失败'}")
    return {"ok": result["ok"], "result": result}


# --------------------------------------------------------------------------- settings / AI / proxy
@app.get("/api/settings")
def get_settings():
    return {
        "settings": settings.get_all_settings(mask=True),
        "providers": AI_PROVIDERS,
        "channel_types": CHANNEL_TYPES,
        "defaults": settings.DEFAULT_SETTINGS,
    }


@app.put("/api/settings/{group}")
def update_settings(group: str, payload: SettingsPatch):
    if group not in settings.DEFAULT_SETTINGS:
        raise HTTPException(404, "未知设置分组")
    try:
        result = settings.update_setting(group, payload.values)
    except Exception as exc:  # noqa: BLE001
        logger.exception("settings update failed")
        raise HTTPException(400, f"保存设置失败：{exc}") from exc
    if group == "general":
        scheduler.reconcile()
    return {"ok": True, "settings": result}


@app.post("/api/ai/test")
def test_ai(payload: TestAIRequest):
    cfg = settings.ai_settings()
    for key, value in payload.model_dump(exclude_none=True).items():
        if isinstance(value, str) and (not value or value == KEEP or value.startswith(MASK)):
            continue
        cfg[key] = value
    try:
        result = AIClient(cfg).test()
        return {"ok": True, **result}
    except (AIError, Exception) as exc:  # noqa: BLE001
        logger.warning("AI test failed: %s", exc)
        return {"ok": False, "error": str(exc)}


@app.post("/api/feasibility")
def feasibility(payload: FeasibilityRequest):
    result = probe.analyze(
        payload.url, payload.name or payload.url, use_ai=payload.use_ai, use_proxy=payload.use_proxy
    )
    return result


@app.post("/api/proxy/test")
def test_proxy(payload: ProxyTestRequest):
    target = (payload.url or settings.get_setting("proxy", mask=False).get("test_url") or "https://api.ipify.org?format=json").strip()
    return probe.test_proxy(target)


@app.post("/api/browser/test")
def test_browser(payload: BrowserTestRequest):
    target = (payload.url or "https://example.com").strip()
    if not target.startswith(("http://", "https://")):
        raise HTTPException(400, "测试 URL 必须以 http:// 或 https:// 开头")
    return browser_scanner.test_render(target)


@app.get("/api/presets")
def list_presets():
    with db.get_conn() as conn:
        urls = {r["url"] for r in conn.execute("SELECT url FROM sources").fetchall()}
    return {"presets": [{**p, "installed": p["url"] in urls} for p in presets.PRESETS]}


@app.post("/api/presets/{key}", status_code=201)
def install_preset(key: str, payload: PresetInstall):
    preset = presets.get_preset(key)
    if not preset:
        raise HTTPException(404, "预设不存在")
    with db.get_conn() as conn:
        exists = conn.execute("SELECT id FROM sources WHERE url=?", (preset["url"],)).fetchone()
        if exists:
            raise HTTPException(409, "该预设已添加")
        ts = now_iso()
        cur = conn.execute(
            """INSERT INTO sources(name,url,strategy,interval_minutes,enabled,use_proxy,locale,selectors,notes,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (preset["name"], preset["url"], preset["strategy"], 60, int(payload.enabled), 1,
             preset.get("locale") or "zh", json.dumps(preset.get("selectors") or {}, ensure_ascii=False),
             preset.get("notes") or "内置预设", "idle", ts, ts),
        )
        source_id = int(cur.lastrowid)
    db.log_event("info", "source.preset", f"安装预设：{preset['name']}", source_id=source_id)
    scheduler.reconcile()
    return _source_with_next(db.get_source(source_id))


# --------------------------------------------------------------------------- logs / export
@app.get("/api/logs")
def list_logs(level: str | None = None, limit: int = Query(default=120, ge=1, le=500)):
    where = "1=1"
    params: list[Any] = []
    if level:
        where = "level=?"
        params.append(level)
    with db.get_conn() as conn:
        rows = [dict(r) for r in conn.execute(
            f"SELECT * FROM logs WHERE {where} ORDER BY id DESC LIMIT ?", (*params, limit)
        ).fetchall()]
    return {"logs": rows}


@app.delete("/api/logs")
def clear_logs():
    with db.get_conn() as conn:
        conn.execute("DELETE FROM logs")
    return {"ok": True}


@app.get("/api/export")
def export_config():
    data = {
        "app": APP_NAME,
        "version": APP_VERSION,
        "exported_at": now_iso(),
        "sources": [_source_out(r) for r in db.list_sources()],
        "settings": settings.get_all_settings(mask=True),
        "channels": settings.channels_public(),
    }
    payload = json.dumps(_clean(data), ensure_ascii=False, indent=2)
    return Response(
        payload,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="game-update-radar-export.json"'},
    )


# --------------------------------------------------------------------------- WebUI
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index():
    path = WEB_DIR / "index.html"
    if not path.exists():
        return JSONResponse(status_code=503, content={"detail": "WebUI 尚未安装"})
    return FileResponse(path, media_type="text/html")


@app.get("/favicon.svg", include_in_schema=False)
def favicon():
    path = WEB_DIR / "favicon.svg"
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/svg+xml")
