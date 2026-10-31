"""Browser rendering through a self-hosted Browserless sidecar.

The app never launches Chromium itself.  It calls Browserless' `/content`
endpoint, which returns the DOM after JavaScript execution.  This keeps the
main image small and lets `docker-compose.yml` run the browser in the same
network namespace as the app (`network_mode: service:radar`) without exposing
another host port.
"""
from __future__ import annotations

import time
from urllib.parse import urlsplit

import httpx

from ..settings import get_setting
from .fetch import FetchResult

MAX_RENDER_BYTES = 8 * 1024 * 1024


class BrowserError(RuntimeError):
    pass


def browser_settings() -> dict:
    return get_setting("browser", mask=False)


def _endpoint(base: str) -> str:
    base = (base or "").strip().rstrip("/")
    if not base:
        raise BrowserError("未配置浏览器服务地址")
    if base.endswith("/content") or base.endswith("/chromium/content"):
        return base
    return base + "/content"


def render(
    url: str,
    *,
    wait_ms: int | None = None,
    timeout: float | None = None,
    headers: dict[str, str] | None = None,
) -> FetchResult:
    """Render *url* with Browserless and return it as a FetchResult.

    Raises BrowserError with an actionable message when the sidecar is down,
    rejects the request, or returns an empty page.
    """
    cfg = browser_settings()
    if not cfg.get("enabled"):
        raise BrowserError("浏览器渲染未启用")
    endpoint = _endpoint(str(cfg.get("url") or ""))
    wait = int(wait_ms if wait_ms is not None else cfg.get("wait_ms") or 1200)
    wait = max(0, min(wait, 15000))
    timeout_s = float(timeout if timeout is not None else cfg.get("timeout_seconds") or 45)
    timeout_s = max(5.0, min(timeout_s, 120.0))
    token = str(cfg.get("token") or "").strip()
    req_headers = {"Accept": "text/html,application/xhtml+xml", **(headers or {})}
    if token:
        req_headers["Authorization"] = f"Bearer {token}"
    payload = {
        "url": url,
        "gotoOptions": {"waitUntil": "networkidle2", "timeout": int(timeout_s * 1000)},
        "waitForTimeout": wait,
        "bestAttempt": True,
    }
    started = time.monotonic()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout_s + 15, connect=10),
            follow_redirects=True,
            headers=req_headers,
        ) as client:
            resp = client.post(endpoint, json=payload)
    except (httpx.HTTPError, OSError) as exc:
        raise BrowserError(
            f"浏览器服务不可达（{endpoint}）：{exc}；请确认 browser 容器已启动"
        ) from exc

    if resp.status_code >= 400:
        body = resp.text[:300].replace("\n", " ")
        raise BrowserError(f"浏览器服务返回 HTTP {resp.status_code}：{body}")
    raw = resp.content
    if len(raw) > MAX_RENDER_BYTES:
        raise BrowserError("浏览器渲染结果超过 8MB 限制")
    text = raw.decode(resp.encoding or "utf-8", errors="replace")
    if not text.strip():
        raise BrowserError("浏览器返回了空页面")
    target_status = 0
    try:
        target_status = int(resp.headers.get("x-response-code") or 0)
    except ValueError:
        target_status = 0
    final_url = resp.headers.get("x-response-url") or url
    if target_status and target_status >= 400:
        raise BrowserError(
            f"目标页面返回 HTTP {target_status}（浏览器已渲染，但站点拒绝访问）",
        )
    return FetchResult(
        url=url,
        final_url=str(final_url),
        status=target_status or resp.status_code,
        text=text,
        content_type=resp.headers.get("content-type", "text/html"),
        elapsed_ms=int((time.monotonic() - started) * 1000),
        headers={k.lower(): v for k, v in resp.headers.items()},
    )


def same_site(left: str, right: str) -> bool:
    """True when both URLs belong to the same site (www/subdomains allowed)."""
    if not left or not right:
        return True

    def host(value: str) -> str:
        try:
            return (urlsplit(value).hostname or "").lower().strip(".")
        except ValueError:
            return ""

    a, b = host(left), host(right)
    if not a or not b:
        return True
    # Keep this strict: only the exact host (or its www. variant) is accepted.
    # A rendered login/blocked page on another host must never be trusted.
    return a.removeprefix("www.") == b.removeprefix("www.")


def test_render(url: str = "https://example.com") -> dict:
    try:
        result = render(url, wait_ms=500, timeout=25)
        return {
            "ok": True,
            "url": url,
            "final_url": result.final_url,
            "status": result.status,
            "elapsed_ms": result.elapsed_ms,
            "bytes": len(result.text),
            "title": _page_title(result.text),
        }
    except BrowserError as exc:
        return {"ok": False, "url": url, "error": str(exc)}


def _page_title(html: str) -> str:
    from .extract import clean_text

    start = html.lower().find("<title")
    if start < 0:
        return ""
    end = html.lower().find("</title>", start)
    if end < 0:
        return ""
    raw = html[start:end]
    if ">" in raw:
        raw = raw.split(">", 1)[1]
    return clean_text(raw, 200)
