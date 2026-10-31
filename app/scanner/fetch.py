"""Outbound HTTP with global proxy, retries and size limits."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from ..config import HTTP_TIMEOUT, MAX_ITEMS_PER_SCAN
from ..settings import proxy_url_for

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 GameUpdateRadar/1.0"
)
DEFAULT_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}
MAX_BYTES = 8 * 1024 * 1024


class FetchError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    text: str
    content_type: str
    elapsed_ms: int
    headers: dict[str, str] = field(default_factory=dict)


def build_client(*, use_proxy: bool = True, timeout: float = HTTP_TIMEOUT) -> httpx.Client:
    proxy = None
    # target-independent default: prefer https proxy
    from ..settings import proxy_settings

    if use_proxy:
        cfg = proxy_settings()
        if cfg.get("enabled"):
            proxy = cfg.get("https_proxy") or cfg.get("http_proxy") or None
    kwargs = {
        "timeout": httpx.Timeout(timeout, connect=min(15.0, timeout)),
        "follow_redirects": True,
        "headers": DEFAULT_HEADERS,
        "verify": True,
    }
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.Client(**kwargs)


def fetch(
    url: str,
    *,
    use_proxy: bool = True,
    timeout: float = HTTP_TIMEOUT,
    retries: int = 2,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    json_body: dict | list | None = None,
) -> FetchResult:
    last_error: Exception | None = None
    method = (method or "GET").upper()
    for attempt in range(retries + 1):
        started = time.monotonic()
        proxy = proxy_url_for(url, use_proxy)
        try:
            client_kwargs = {
                "timeout": httpx.Timeout(timeout, connect=min(15.0, timeout)),
                "follow_redirects": True,
                "headers": {**DEFAULT_HEADERS, **(headers or {})},
                "verify": True,
            }
            if proxy:
                client_kwargs["proxy"] = proxy
            with httpx.Client(**client_kwargs) as client:
                stream_kwargs = {"json": json_body} if json_body is not None else {}
                with client.stream(method, url, **stream_kwargs) as resp:
                    status = resp.status_code
                    if status >= 400:
                        raise FetchError(f"HTTP {status}", status=status)
                    content_type = resp.headers.get("content-type", "")
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in resp.iter_bytes():
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise FetchError("响应超过 8MB 限制")
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                    encoding = resp.encoding or "utf-8"
                    try:
                        text = raw.decode(encoding, errors="replace")
                    except (LookupError, TypeError):
                        text = raw.decode("utf-8", errors="replace")
                    return FetchResult(
                        url=url,
                        final_url=str(resp.url),
                        status=status,
                        text=text,
                        content_type=content_type,
                        elapsed_ms=int((time.monotonic() - started) * 1000),
                        headers={k.lower(): v for k, v in resp.headers.items()},
                    )
        except FetchError as exc:
            last_error = exc
            if exc.status and 400 <= exc.status < 500 and exc.status not in (408, 429):
                break
        except (httpx.HTTPError, OSError, ValueError) as exc:
            last_error = exc
        if attempt < retries:
            time.sleep(1.0 if attempt == 0 else 3.0)
    detail = str(last_error) if last_error else "未知网络错误"
    raise FetchError(f"抓取失败：{detail}", status=getattr(last_error, "status", None))


def get_json(url: str, *, use_proxy: bool = True, timeout: float = HTTP_TIMEOUT) -> dict:
    import json

    result = fetch(url, use_proxy=use_proxy, timeout=timeout, headers={"Accept": "application/json"})
    try:
        return json.loads(result.text)
    except ValueError as exc:
        raise FetchError(f"返回内容不是合法 JSON：{exc}") from exc


def post_json(
    url: str,
    payload: dict,
    *,
    use_proxy: bool = True,
    timeout: float = HTTP_TIMEOUT,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    proxy = proxy_url_for(url, use_proxy)
    kwargs = {
        "timeout": httpx.Timeout(timeout, connect=min(15.0, timeout)),
        "follow_redirects": True,
        "headers": {**DEFAULT_HEADERS, "Content-Type": "application/json", **(headers or {})},
        "verify": True,
    }
    if proxy:
        kwargs["proxy"] = proxy
    with httpx.Client(**kwargs) as client:
        return client.post(url, json=payload)
