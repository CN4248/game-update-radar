"""Notification channels. Every sender returns a result dict instead of raising."""
from __future__ import annotations

import base64
import html as html_lib
import json
import logging
import smtplib
import ssl
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any

import httpx

from .db import log_event
from .settings import proxy_url_for

logger = logging.getLogger(__name__)


@dataclass
class Notification:
    game: str
    title: str
    summary: str
    url: str
    published: str = ""
    reason: str = ""
    digest: str = ""
    source_url: str = ""

    @property
    def subject(self) -> str:
        return f"[游戏更新] {self.game} · {self.title}"

    def as_text(self) -> str:
        lines = [
            f"【{self.game}】检测到新的更新公告",
            "",
            f"标题：{self.title}",
        ]
        if self.published:
            lines.append(f"发布：{self.published}")
        if self.digest:
            lines += ["", f"AI 摘要：{self.digest}"]
        if self.summary:
            lines += ["", self.summary]
        lines += ["", f"查看公告：{self.url}"]
        if self.reason:
            lines += ["", f"判定依据：{self.reason}"]
        lines += ["", "—— Game Update Radar 自动提醒"]
        return "\n".join(lines)

    def as_html(self) -> str:
        esc = html_lib.escape
        digest = f'<p style="margin:12px 0;padding:10px 14px;background:#0f172a;border-left:3px solid #5ee7ff;color:#cbd5e1;border-radius:6px"><b>AI 摘要：</b>{esc(self.digest)}</p>' if self.digest else ""
        summary = f'<p style="color:#94a3b8;line-height:1.7">{esc(self.summary)}</p>' if self.summary else ""
        return f"""<!doctype html><html><body style="margin:0;background:#070b14;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
<div style="max-width:620px;margin:0 auto;padding:28px">
  <div style="color:#5ee7ff;font-size:12px;letter-spacing:2px;text-transform:uppercase">Game Update Radar</div>
  <h2 style="color:#f1f5f9;font-size:22px;margin:8px 0 4px">{esc(self.game)} 有新更新</h2>
  <div style="height:1px;background:linear-gradient(90deg,#5ee7ff,transparent);margin:16px 0"></div>
  <h3 style="color:#e2e8f0;font-size:18px;line-height:1.5;margin:0 0 8px">{esc(self.title)}</h3>
  <div style="color:#64748b;font-size:13px">{esc(self.published or '发布时间未知')}</div>
  {digest}{summary}
  <p style="margin:24px 0"><a href="{esc(self.url)}" style="display:inline-block;background:#5ee7ff;color:#04121a;text-decoration:none;font-weight:700;padding:11px 22px;border-radius:8px">查看公告原文</a></p>
  <div style="color:#475569;font-size:12px;line-height:1.6">判定依据：{esc(self.reason or '规则命中')}<br>由 Game Update Radar 自动发送</div>
</div></body></html>"""

    def as_dict(self) -> dict[str, Any]:
        return {
            "event": "game_update",
            "game": self.game,
            "title": self.title,
            "summary": self.summary,
            "url": self.url,
            "published": self.published,
            "reason": self.reason,
            "digest": self.digest,
            "source_url": self.source_url,
        }


REQUIRED: dict[str, tuple[str, ...]] = {
    "email": ("host", "from_addr", "to_addr"),
    "telegram": ("bot_token", "chat_id"),
    "webhook": ("url",),
    "bark": ("device_key",),
    "serverchan": ("sendkey",),
    "pushplus": ("token",),
    "ntfy": ("topic",),
    "twilio": ("account_sid", "auth_token", "from_number", "to_number"),
    "console": (),
}


def validate_channel(channel_type: str, config: dict[str, Any]) -> None:
    missing = [k for k in REQUIRED.get(channel_type, ()) if not str(config.get(k) or "").strip()]
    if missing:
        raise ValueError("缺少配置项：" + "、".join(missing))


def _result(channel: dict, ok: bool, message: str, started: float, **extra) -> dict[str, Any]:
    out = {
        "channel_id": channel.get("id"),
        "name": channel.get("name"),
        "type": channel.get("type"),
        "ok": ok,
        "status": "sent" if ok else "failed",
        "message": message[:500],
        "latency_ms": int((time.monotonic() - started) * 1000),
    }
    out.update(extra)
    return out


def _client_for(url: str, timeout: float = 20.0, headers: dict | None = None) -> httpx.Client:
    proxy = proxy_url_for(url, True)
    kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(timeout, connect=10.0),
        "follow_redirects": True,
        "headers": {"User-Agent": "GameUpdateRadar/1.0", **(headers or {})},
    }
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.Client(**kwargs)


def _send_email(cfg: dict, note: Notification) -> str:
    msg = EmailMessage()
    msg["Subject"] = f"{cfg.get('subject_prefix') or '[游戏更新]'} {note.game} · {note.title}"
    msg["From"] = formataddr((cfg.get("from_name") or "Game Update Radar", cfg["from_addr"]))
    to_addrs = [x.strip() for x in str(cfg["to_addr"]).replace(";", ",").split(",") if x.strip()]
    msg["To"] = ", ".join(to_addrs)
    msg.set_content(note.as_text())
    msg.add_alternative(note.as_html(), subtype="html")
    host = str(cfg["host"]).strip()
    port = int(cfg.get("port") or (465 if cfg.get("encryption") == "ssl" else 587))
    encryption = str(cfg.get("encryption") or "starttls").lower()
    timeout = 20
    if encryption == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(host, port, timeout=timeout)
    with server:
        server.ehlo()
        if encryption == "starttls":
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        if cfg.get("username"):
            server.login(str(cfg["username"]), str(cfg.get("password") or ""))
        server.send_message(msg, from_addr=cfg["from_addr"], to_addrs=to_addrs)
    return f"邮件已发送至 {len(to_addrs)} 个收件人"


def _send_telegram(cfg: dict, note: Notification) -> str:
    token = str(cfg["bot_token"]).strip()
    base = str(cfg.get("api_base") or "https://api.telegram.org").rstrip("/")
    url = f"{base}/bot{token}/sendMessage"
    payload = {
        "chat_id": cfg["chat_id"],
        "text": note.as_text(),
        "disable_web_page_preview": False,
    }
    with _client_for(url) as client:
        resp = client.post(url, json=payload)
    if resp.status_code >= 400:
        raise RuntimeError(f"Telegram HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram 返回失败：{data.get('description')}")
    return "Telegram 消息已发送"


def _send_webhook(cfg: dict, note: Notification) -> str:
    url = str(cfg["url"]).strip()
    method = str(cfg.get("method") or "POST").upper()
    headers = cfg.get("headers") or {}
    if not isinstance(headers, dict):
        headers = {}
    headers = {str(k): str(v) for k, v in headers.items()}
    payload = note.as_dict()
    template = cfg.get("body_template")
    if template:
        text = str(template)
        for key, val in payload.items():
            text = text.replace("{{" + key + "}}", str(val))
        try:
            payload = json.loads(text)
        except ValueError:
            payload = text
            headers.setdefault("Content-Type", "text/plain; charset=utf-8")
    with _client_for(url, headers=headers) as client:
        if method == "GET":
            resp = client.get(url, params=payload if isinstance(payload, dict) else None)
        else:
            if isinstance(payload, dict):
                resp = client.request(method, url, json=payload)
            else:
                resp = client.request(method, url, content=str(payload))
    if resp.status_code >= 400:
        raise RuntimeError(f"Webhook HTTP {resp.status_code}: {resp.text[:200]}")
    return f"Webhook 已触发（HTTP {resp.status_code}）"


def _send_bark(cfg: dict, note: Notification) -> str:
    server = str(cfg.get("server") or "https://api.day.app").rstrip("/")
    url = f"{server}/{str(cfg['device_key']).strip()}"
    payload = {
        "title": note.subject,
        "body": note.summary or note.title,
        "url": note.url,
        "group": cfg.get("group") or "游戏更新",
        "sound": cfg.get("sound") or "bell",
    }
    with _client_for(url) as client:
        resp = client.post(url, json=payload)
    if resp.status_code >= 400:
        raise RuntimeError(f"Bark HTTP {resp.status_code}: {resp.text[:200]}")
    return "Bark 推送已发送"


def _send_serverchan(cfg: dict, note: Notification) -> str:
    sendkey = str(cfg["sendkey"]).strip()
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    data = {"title": note.subject, "desp": note.as_text()}
    with _client_for(url) as client:
        resp = client.post(url, data=data)
    if resp.status_code >= 400:
        raise RuntimeError(f"Server酱 HTTP {resp.status_code}: {resp.text[:200]}")
    body = resp.json()
    if body.get("code") not in (0, None):
        raise RuntimeError(f"Server酱返回失败：{body.get('message')}")
    return "Server酱推送已发送"


def _send_pushplus(cfg: dict, note: Notification) -> str:
    url = "https://www.pushplus.plus/send"
    payload = {
        "token": cfg["token"],
        "title": note.subject,
        "content": note.as_html(),
        "template": "html",
    }
    if cfg.get("topic"):
        payload["topic"] = cfg["topic"]
    with _client_for(url) as client:
        resp = client.post(url, json=payload)
    if resp.status_code >= 400:
        raise RuntimeError(f"PushPlus HTTP {resp.status_code}: {resp.text[:200]}")
    body = resp.json()
    if body.get("code") not in (200, 0, None):
        raise RuntimeError(f"PushPlus 返回失败：{body.get('msg')}")
    return "PushPlus 推送已发送"


def _send_ntfy(cfg: dict, note: Notification) -> str:
    server = str(cfg.get("server") or "https://ntfy.sh").rstrip("/")
    topic = str(cfg["topic"]).strip()
    url = f"{server}/{topic}"
    headers = {
        "Title": note.subject.encode("utf-8").decode("latin-1", "ignore"),
        "Priority": str(cfg.get("priority") or "default"),
        "Tags": "video_game",
        "Content-Type": "text/plain; charset=utf-8",
    }
    if cfg.get("token"):
        headers["Authorization"] = f"Bearer {cfg['token']}"
    with _client_for(url, headers=headers) as client:
        resp = client.post(url, content=note.as_text().encode("utf-8"))
    if resp.status_code >= 400:
        raise RuntimeError(f"ntfy HTTP {resp.status_code}: {resp.text[:200]}")
    return "ntfy 推送已发送"


def _send_twilio(cfg: dict, note: Notification) -> str:
    sid = str(cfg["account_sid"]).strip()
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    body = note.as_text()
    if len(body) > 1500:
        body = body[:1490] + "…"
    auth = base64.b64encode(f"{sid}:{cfg['auth_token']}".encode()).decode()
    with _client_for(url, headers={"Authorization": f"Basic {auth}"}) as client:
        resp = client.post(
            url,
            data={"From": cfg["from_number"], "To": cfg["to_number"], "Body": body},
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Twilio HTTP {resp.status_code}: {resp.text[:200]}")
    return "短信已提交至 Twilio"


def _send_console(cfg: dict, note: Notification) -> str:
    logger.info("CONSOLE NOTIFICATION\n%s", note.as_text())
    log_event("info", "notify.console", f"Console 提醒：{note.game} · {note.title}")
    return "已写入运行日志（Console 渠道）"


SENDERS = {
    "email": _send_email,
    "telegram": _send_telegram,
    "webhook": _send_webhook,
    "bark": _send_bark,
    "serverchan": _send_serverchan,
    "pushplus": _send_pushplus,
    "ntfy": _send_ntfy,
    "twilio": _send_twilio,
    "console": _send_console,
}


def send_channel(channel: dict[str, Any], note: Notification) -> dict[str, Any]:
    started = time.monotonic()
    ctype = str(channel.get("type") or "")
    cfg = channel.get("config") or {}
    sender = SENDERS.get(ctype)
    if not sender:
        return _result(channel, False, f"未知渠道类型：{ctype}", started)
    try:
        if not channel.get("enabled", True):
            return _result(channel, False, "渠道已禁用", started, status="skipped")
        validate_channel(ctype, cfg)
        message = sender(cfg, note)
        return _result(channel, True, message, started)
    except Exception as exc:  # noqa: BLE001 - a channel must never break scanning
        logger.warning("channel %s (%s) failed: %s", channel.get("name"), ctype, exc)
        return _result(channel, False, f"{type(exc).__name__}: {exc}", started)


def send_with_retries(channel: dict[str, Any], note: Notification, retries: int = 2) -> dict[str, Any]:
    result = send_channel(channel, note)
    attempt = 0
    while not result["ok"] and result.get("status") != "skipped" and attempt < retries:
        attempt += 1
        time.sleep(2 if attempt == 1 else 5)
        result = send_channel(channel, note)
        result["attempts"] = attempt + 1
    result.setdefault("attempts", 1)
    return result
