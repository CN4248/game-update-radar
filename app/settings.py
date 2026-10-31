"""Settings storage with field-level encryption for secrets."""
from __future__ import annotations

import copy
import json
import os
import stat
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from .config import CLEAR, CONFIG_DIR, KEEP, MASK, SECRET_PATH
from .db import get_conn, log_event
from .timeutil import now_iso

DEFAULT_SETTINGS: dict[str, dict[str, Any]] = {
    "general": {
        "default_interval_minutes": 60,
        "max_age_days": 45,
        "timezone": "Asia/Shanghai",
        "scan_concurrency": 3,
        "notify_on_first_scan": False,
        "ai_summary": True,
        "log_retention": 5000,
        "item_retention_days": 730,
        "alert_retention_days": 365,
    },
    "ai": {
        "enabled": False,
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "model": "deepseek-chat",
        "temperature": 0.1,
        "max_tokens": 900,
        "timeout_seconds": 45,
        "auto_repair": True,
        "repair_max_attempts": 3,
        "repair_cooldown_minutes": 360,
    },
    "proxy": {
        "enabled": False,
        "http_proxy": "",
        "https_proxy": "",
        "no_proxy": "localhost,127.0.0.1",
        "test_url": "https://api.ipify.org?format=json",
    },
    "browser": {
        "enabled": True,
        "auto_render": True,
        "url": "http://127.0.0.1:3000",
        "token": "",
        "wait_ms": 1200,
        "timeout_seconds": 45,
    },
    "ui": {
        "theme": "midnight",
        "mode": "dark",
        "accent": "",
        "accent2": "",
        "background": "",
        "surface": "",
        "text": "",
        "radius": 14,
        "density": "comfortable",
        "sidebar_collapsed": False,
    },
}

SECRET_KEYS = {
    "api_key",
    "password",
    "bot_token",
    "sendkey",
    "token",
    "auth_token",
    "secret",
    "smtp_password",
    "twilio_auth_token",
}


def _fernet() -> Fernet:
    if SECRET_PATH.exists():
        raw = SECRET_PATH.read_bytes().strip()
    else:
        raw = Fernet.generate_key()
        SECRET_PATH.write_bytes(raw + b"\n")
        try:
            os.chmod(SECRET_PATH, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    return Fernet(raw)


def encrypt_value(value: str) -> str:
    if not value or value.startswith("enc:v1:"):
        return value
    return "enc:v1:" + _fernet().encrypt(value.encode()).decode()


def decrypt_value(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("enc:v1:"):
        return value
    try:
        return _fernet().decrypt(value[7:].encode()).decode()
    except (InvalidToken, ValueError):
        return ""


def _walk(value: Any, fn) -> Any:
    if isinstance(value, dict):
        return {k: (fn(v) if k in SECRET_KEYS and isinstance(v, str) else _walk(v, fn)) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v, fn) for v in value]
    return value


def mask_value(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return MASK
    return MASK + value[-4:]


def _mask(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (mask_value(v) if k in SECRET_KEYS and isinstance(v, str) else _mask(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v) for v in value]
    return value


def _public(value: Any) -> Any:
    """Mask secrets for API responses (AI settings)."""
    return _mask(copy.deepcopy(value))


def get_setting(key: str, *, mask: bool = False) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    defaults = copy.deepcopy(DEFAULT_SETTINGS.get(key, {}))
    raw = json.loads(row["value"]) if row else defaults
    if isinstance(raw, dict):
        raw = deep_merge(defaults, raw)
    plain = _walk(raw, decrypt_value)
    return _public(plain) if mask else plain


def get_all_settings(*, mask: bool = True) -> dict[str, Any]:
    out = {}
    for key in DEFAULT_SETTINGS:
        out[key] = get_setting(key, mask=mask)
    return out


def _preserve(existing: Any, incoming: Any) -> Any:
    """Replace KEEP/masked secret placeholders with existing values; CLEAR empties."""
    if isinstance(incoming, dict) and isinstance(existing, dict):
        merged = {}
        for k, v in incoming.items():
            if k in SECRET_KEYS and isinstance(v, str):
                if v in (KEEP, MASK) or v.startswith(MASK):
                    merged[k] = existing.get(k, "")
                elif v == CLEAR:
                    merged[k] = ""
                elif v == "" and existing.get(k):
                    merged[k] = existing.get(k)
                else:
                    merged[k] = v
            else:
                merged[k] = _preserve(existing.get(k), v)
        return merged
    return incoming


def deep_merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def update_setting(key: str, patch: dict[str, Any]) -> dict[str, Any]:
    if key not in DEFAULT_SETTINGS:
        raise KeyError(key)
    existing = get_setting(key, mask=False)
    merged = deep_merge(existing, _preserve(existing, patch))
    stored = _walk(merged, encrypt_value)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, json.dumps(stored, ensure_ascii=False), now_iso()),
        )
    log_event("info", "settings", f"设置已更新：{key}")
    return _public(copy.deepcopy(merged))


def ensure_defaults() -> None:
    for key, value in DEFAULT_SETTINGS.items():
        with get_conn() as conn:
            exists = conn.execute("SELECT 1 FROM settings WHERE key=?", (key,)).fetchone()
        if not exists:
            with get_conn() as conn:
                conn.execute(
                    "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?)",
                    (key, json.dumps(value, ensure_ascii=False), now_iso()),
                )


def ai_settings() -> dict[str, Any]:
    cfg = get_setting("ai", mask=False)
    cfg["api_key"] = decrypt_value(cfg.get("api_key", ""))
    return cfg


def proxy_settings() -> dict[str, Any]:
    return get_setting("proxy", mask=False)


def proxy_url_for(target_url: str, use_proxy: bool = True) -> str | None:
    cfg = proxy_settings()
    if not use_proxy or not cfg.get("enabled"):
        return None
    from urllib.parse import urlparse

    host = (urlparse(target_url).hostname or "").lower()
    for item in str(cfg.get("no_proxy", "")).split(","):
        item = item.strip().lower()
        if item and (host == item or host.endswith("." + item.lstrip("*."))):
            return None
    scheme = urlparse(target_url).scheme
    if scheme == "https":
        return cfg.get("https_proxy") or cfg.get("http_proxy") or None
    return cfg.get("http_proxy") or cfg.get("https_proxy") or None


def channels_public() -> list[dict[str, Any]]:
    from .db import rows_to_dicts

    with get_conn() as conn:
        rows = rows_to_dicts(conn.execute("SELECT * FROM channels ORDER BY id ASC").fetchall())
    for row in rows:
        raw = json.loads(row.get("config") or "{}")
        plain = _walk(raw, decrypt_value)
        row["config"] = _mask(plain)
        row["configured"] = row.get("type") == "console" or bool(plain)
    return rows


def channel_raw(row: dict[str, Any]) -> dict[str, Any]:
    raw = json.loads(row.get("config") or "{}")
    plain = _walk(raw, decrypt_value)
    if "config" in row and isinstance(row["config"], str):
        row = dict(row)
        row["config"] = plain
    return row


def encrypt_config(config: dict[str, Any]) -> dict[str, Any]:
    """Encrypt every secret-looking field in a channel config."""
    return _walk(config or {}, encrypt_value)


def merge_secret_config(existing: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Merge a UI patch into an existing config, preserving masked/blank secrets."""
    return _preserve(existing or {}, patch or {})
