"""OpenAI-compatible and Anthropic chat clients plus feasibility analysis."""
from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from ..settings import ai_settings, proxy_url_for
from .extract import ExtractResult, Item, clean_text, page_diagnostics


class AIError(RuntimeError):
    pass


def extract_json(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        raise AIError("AI 返回为空")
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except ValueError:
        pass
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        raise AIError("AI 返回中没有 JSON")
    start = min(starts)
    end_char = "}" if text[start] == "{" else "]"
    end = text.rfind(end_char)
    if end <= start:
        raise AIError("AI 返回的 JSON 不完整")
    try:
        return json.loads(text[start:end + 1])
    except ValueError as exc:
        raise AIError(f"AI 返回的 JSON 无法解析：{exc}") from exc


class AIClient:
    def __init__(self, cfg: dict[str, Any] | None = None, *, use_proxy: bool = True):
        self.cfg = cfg or ai_settings()
        self.use_proxy = use_proxy
        self.provider = str(self.cfg.get("provider") or "openai").lower()
        self.base_url = str(self.cfg.get("base_url") or "https://api.deepseek.com/v1").rstrip("/")
        self.api_key = str(self.cfg.get("api_key") or "")
        self.model = str(self.cfg.get("model") or "deepseek-chat")
        self.timeout = float(self.cfg.get("timeout_seconds") or 45)

    @property
    def configured(self) -> bool:
        if self.provider == "anthropic":
            return bool(self.api_key)
        return bool(self.api_key) or "localhost" in self.base_url or "127.0.0.1" in self.base_url

    def _endpoint(self) -> tuple[str, dict[str, str], str]:
        if self.provider == "anthropic":
            url = self.base_url if self.base_url.endswith("/messages") else self.base_url + "/messages"
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            return url, headers, "anthropic"
        if self.base_url.endswith("/chat/completions"):
            url = self.base_url
        elif self.base_url.endswith("/v1"):
            url = self.base_url + "/chat/completions"
        else:
            url = self.base_url + "/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        return url, headers, "openai"

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url, headers, kind = self._endpoint()
        proxy = proxy_url_for(url, self.use_proxy)
        kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(self.timeout, connect=min(15.0, self.timeout)),
            "headers": headers,
        }
        if proxy:
            kwargs["proxy"] = proxy
        try:
            with httpx.Client(**kwargs) as client:
                resp = client.post(url, json=payload)
        except (httpx.HTTPError, OSError, ValueError) as exc:
            raise AIError(f"AI 接口连接失败：{type(exc).__name__}: {exc}") from exc
        if resp.status_code >= 400:
            detail = clean_text(resp.text, 300)
            raise AIError(f"AI 接口返回 HTTP {resp.status_code}：{detail}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise AIError("AI 接口返回的不是 JSON") from exc
        if kind == "anthropic":
            blocks = data.get("content") or []
            text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict))
        else:
            choices = data.get("choices") or []
            if not choices:
                raise AIError("AI 接口未返回 choices")
            message = choices[0].get("message") or {}
            text = message.get("content") or ""
            if isinstance(text, list):
                text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
        if not text:
            raise AIError("AI 返回内容为空")
        return {"text": text, "raw": data}

    def chat(self, system: str, user: str, *, json_mode: bool = True, max_tokens: int | None = None) -> str:
        if not self.cfg.get("enabled") and not self.configured:
            raise AIError("AI 未启用或未配置 API Key")
        if not self.api_key and "localhost" not in self.base_url and "127.0.0.1" not in self.base_url:
            raise AIError("未配置 AI API Key")
        tokens = int(max_tokens or self.cfg.get("max_tokens") or 900)
        temperature = float(self.cfg.get("temperature") or 0.1)
        if self.provider == "anthropic":
            payload = {
                "model": self.model,
                "max_tokens": tokens,
                "temperature": temperature,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
            return self._post(payload)["text"]
        payload = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            return self._post(payload)["text"]
        except AIError as exc:
            # Some OpenAI-compatible gateways reject response_format.
            if "response_format" in str(exc) or "HTTP 400" in str(exc):
                payload.pop("response_format", None)
                return self._post(payload)["text"]
            raise

    def test(self) -> dict[str, Any]:
        started = time.monotonic()
        text = self.chat(
            "你是接口连通性检查器。严格只输出 JSON，不要 markdown。",
            '返回 {"ok": true, "message": "pong"}',
            max_tokens=60,
        )
        data = extract_json(text)
        if not isinstance(data, dict) or not data.get("ok"):
            raise AIError("AI 返回格式不符合预期")
        return {
            "ok": True,
            "message": str(data.get("message") or "pong"),
            "model": self.model,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }


def heuristic_feasibility(
    url: str,
    name: str,
    fetch_meta: dict[str, Any],
    result: ExtractResult,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    items = result.items
    dated = sum(1 for i in items if i.published_at)
    count = len(items)
    needs_browser = count == 0 and diagnostics.get("looks_js_shell")
    if count >= 3 and dated >= max(1, count // 3):
        feasible, confidence = True, 0.86
        recommendation = f"可直接监控：已识别 {count} 条公告，推荐策略 {result.strategy}。"
    elif count >= 1:
        feasible, confidence = True, 0.62
        recommendation = f"基本可监控：识别到 {count} 条，但日期/结构不完整，建议保存后观察一轮再调选择器。"
    else:
        feasible, confidence = False, 0.15
        if needs_browser:
            recommendation = "页面疑似纯前端渲染（无服务端列表），首版抓取器无法直接读取。可寻找该站公开 JSON API/RSS，或改用支持浏览器的版本。"
        else:
            recommendation = "未识别到公告列表：可能被反爬拦截、需要登录，或页面结构特殊。可尝试填写具体新闻列表页 URL。"
    risks = []
    if needs_browser:
        risks.append("JS 渲染页面，需要 API/RSS 或浏览器渲染")
    if count and dated < count:
        risks.append(f"{count - dated} 条缺少可解析日期")
    if diagnostics.get("anchors", 0) and count == 0:
        risks.append("有链接但未形成公告列表，可能需要自定义选择器")
    return {
        "feasible": feasible,
        "confidence": confidence,
        "strategy": result.strategy if count else ("browser" if needs_browser else "unknown"),
        "item_count": count,
        "dated_count": dated,
        "sample_items": [
            {
                "title": i.title,
                "url": i.url,
                "published_at": i.published_at.isoformat() if i.published_at else None,
            }
            for i in items[:6]
        ],
        "risks": risks,
        "recommendation": recommendation,
        "needs_browser": needs_browser,
        "page_title": diagnostics.get("page_title") or result.page_title,
        "http_status": fetch_meta.get("status"),
        "final_url": fetch_meta.get("final_url"),
        "elapsed_ms": fetch_meta.get("elapsed_ms"),
        "ai_used": False,
        "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def ai_feasibility(
    name: str,
    url: str,
    base: dict[str, Any],
    result: ExtractResult,
    diagnostics: dict[str, Any],
    *,
    use_proxy: bool = True,
) -> dict[str, Any]:
    cfg = ai_settings()
    if not cfg.get("enabled") or not cfg.get("api_key"):
        return base
    client = AIClient(cfg, use_proxy=use_proxy)
    sample = "\n".join(f"- {i.title} | {i.url}" for i in result.items[:10]) or "（无）"
    prompt = f"""分析这个游戏官网新闻页能否被通用抓取器稳定监控。
游戏：{name or '未知'}
URL：{url}
页面标题：{diagnostics.get('page_title')}
页面诊断：{json.dumps(diagnostics, ensure_ascii=False)}
识别策略：{result.strategy}
已识别条目数：{len(result.items)}
样本：
{sample}

严格输出 JSON 对象：
{{"feasible": true/false, "confidence": 0-1, "strategy": "rsc|html|json|api|browser|unknown",
  "risks": ["..."], "recommendation": "一句中文建议", "needs_browser": true/false,
  "selectors": {{"items_path": "若有 JSON API 可填", "href_contains": ["路径关键词"]}}}}
判断标准：有 >=3 条稳定公告且日期可解析即可行；纯 JS 壳且无 API 则 needs_browser=true。"""
    try:
        text = client.chat("你是资深爬虫工程师，只输出严格 JSON。", prompt, max_tokens=500)
        data = extract_json(text)
    except AIError as exc:
        base["ai_error"] = str(exc)
        return base
    if not isinstance(data, dict):
        return base
    out = dict(base)
    for key in ("feasible", "confidence", "strategy", "risks", "recommendation", "needs_browser", "selectors"):
        if key in data:
            out[key] = data[key]
    # Data wins over speculation: if we already parsed >=3 items, it is feasible.
    if len(result.items) >= 3:
        out["feasible"] = True
        out["confidence"] = max(float(out.get("confidence") or 0), 0.7)
    out["ai_used"] = True
    return out
