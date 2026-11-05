"""Feasibility probe for a candidate news URL."""
from __future__ import annotations

import time
from typing import Any

from ..config import HTTP_TIMEOUT
from ..timeutil import age_days
from .ai import ai_feasibility, heuristic_feasibility
from .browser import BrowserError, browser_settings, render as render_page
from .extract import extract_items, page_diagnostics
from .fetch import FetchError, fetch


def analyze(
    url: str,
    name: str = "",
    *,
    use_ai: bool = True,
    use_proxy: bool = True,
    selectors: dict | None = None,
    strategy: str = "auto",
) -> dict[str, Any]:
    started = time.monotonic()
    browser_used = False
    browser_error = ""
    fetched = None
    try:
        fetched = fetch(url, use_proxy=use_proxy, timeout=HTTP_TIMEOUT)
    except FetchError as exc:
        bcfg = browser_settings()
        if bcfg.get("enabled") and bcfg.get("auto_render", True) and (strategy or "auto") not in {"json", "api"}:
            try:
                fetched = render_page(
                    url,
                    wait_ms=int(bcfg.get("wait_ms") or 1200),
                    timeout=float(bcfg.get("timeout_seconds") or 45),
                )
                browser_used = True
            except BrowserError as berr:
                browser_error = str(berr)
        if fetched is None:
            return {
                "feasible": False,
                "confidence": 0.0,
                "strategy": "unknown",
                "item_count": 0,
                "dated_count": 0,
                "sample_items": [],
                "risks": ["网络请求失败"],
                "recommendation": f"无法访问该页面：{exc}。请检查 URL，或在「AI 与网络」中配置代理后重试。",
                "needs_browser": bool(bcfg.get("enabled")),
                "browser_used": False,
                "browser_error": browser_error,
                "error": str(exc),
                "url": url,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "ai_used": False,
            }
    result = extract_items(fetched.text, fetched.final_url, strategy=strategy or "auto", selectors=selectors)
    diag = page_diagnostics(fetched.text)
    if not result.items and not browser_used:
        bcfg = browser_settings()
        if bcfg.get("enabled") and bcfg.get("auto_render", True) and (strategy or "auto") not in {"json", "api"}:
            try:
                rendered = render_page(
                    url,
                    wait_ms=int(bcfg.get("wait_ms") or 1200),
                    timeout=float(bcfg.get("timeout_seconds") or 45),
                )
                rendered_result = extract_items(
                    rendered.text, rendered.final_url, strategy="auto", selectors=selectors,
                    content_type=rendered.content_type,
                )
                fetched = rendered
                result = rendered_result
                browser_used = True
                diag = page_diagnostics(rendered.text)
            except BrowserError as berr:
                browser_error = str(berr)
    diag["page_title"] = diag.get("page_title") or ""
    if browser_used:
        diag["browser_used"] = True
    if browser_error:
        diag["browser_error"] = browser_error
    meta = {
        "status": fetched.status,
        "final_url": fetched.final_url,
        "elapsed_ms": fetched.elapsed_ms,
        "content_type": fetched.content_type,
    }
    base = heuristic_feasibility(url, name, meta, result, diag)
    base.update(
        {
            "url": url,
            "final_url": fetched.final_url,
            "http_status": fetched.status,
            "browser_used": browser_used,
            "browser_error": browser_error,
            "notes": result.notes,
            "diagnostics": diag,
            "probe_elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    )
    if result.items:
        newest = min((age_days(i.published_at) for i in result.items if i.published_at), default=None)
        base["newest_item_age_days"] = round(newest, 1) if newest is not None else None
    if browser_used and result.items:
        base["needs_browser"] = False
        base["strategy"] = result.strategy
    if use_ai:
        base = ai_feasibility(name, url, base, result, diag, use_proxy=use_proxy)
    return base


def test_proxy(target_url: str) -> dict[str, Any]:
    from ..settings import proxy_settings, proxy_url_for

    started = time.monotonic()
    cfg = proxy_settings()
    proxy = proxy_url_for(target_url, True)
    try:
        fetched = fetch(target_url, use_proxy=True, retries=0, timeout=min(HTTP_TIMEOUT, 30))
        diag = page_diagnostics(fetched.text)
        return {
            "ok": True,
            "status": fetched.status,
            "final_url": fetched.final_url,
            "elapsed_ms": fetched.elapsed_ms,
            "page_title": diag.get("page_title") or "",
            "proxy_enabled": bool(cfg.get("enabled")),
            "proxy_used": bool(proxy),
            "total_ms": int((time.monotonic() - started) * 1000),
        }
    except FetchError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "proxy_enabled": bool(cfg.get("enabled")),
            "proxy_used": bool(proxy),
            "total_ms": int((time.monotonic() - started) * 1000),
        }
