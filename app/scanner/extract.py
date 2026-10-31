"""Extract announcement candidates from HTML, Next.js RSC payloads and JSON APIs."""
from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..config import MAX_ITEMS_PER_SCAN
from ..timeutil import extract_date, parse_date

STRONG_HINTS = (
    "更新", "补丁", "版本", "维护", "停机", "热修", "更新公告", "版本更新", "预下载",
    "patch notes", "patch", "update", "hotfix", "maintenance", "downtime",
)
WEAK_HINTS = (
    "平衡", "修复", "优化", "新内容", "赛季", "活动", "卡池", "上线", "调整", "公告",
    "bug", "fix", "release", "notes",
)
NEWS_PATH = re.compile(r"(news|article|update|announcement|patch|notice|blog|post|detail|event)", re.I)
SKIP_EXT = re.compile(r"\.(jpg|jpeg|png|gif|webp|svg|css|js|pdf|zip|mp4|mp3)(\?|$)", re.I)
TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid", "spm"}
NAV_WORDS = {
    "首页", "新闻", "公告", "资讯", "更多", "查看更多", "查看全部", "登录", "注册", "下载", "返回",
    "上一页", "下一页", "english", "中文", "en", "jp", "kr", "社区", "商城", "支持", "联系我们",
}
_TITLE_KEYS = ("title", "headline", "name", "post_title", "subject", "heading")
_URL_KEYS = ("url", "link", "href", "jump_url", "post_url", "permalink", "web_url")
_DATE_KEYS = (
    "date", "published_at", "publishedAt", "created_at", "createdAt", "publish_time",
    "start_time", "pubDate", "published", "time", "release_date", "datePublished",
)
_SUMMARY_KEYS = ("summary", "desc", "description", "excerpt", "content", "intro", "abstract")


@dataclass
class Item:
    title: str
    url: str
    summary: str = ""
    published_at: datetime | None = None
    external_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "summary": self.summary,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "external_id": self.external_id,
            "raw": self.raw,
        }


@dataclass
class ExtractResult:
    items: list[Item]
    strategy: str
    notes: list[str] = field(default_factory=list)
    page_title: str = ""


def clean_text(value: Any, limit: int = 400) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html_lib.unescape(value)
    value = re.sub(r"\\+$", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit]


def canonical_url(url: str, base: str = "") -> str:
    if not url:
        return ""
    joined = urljoin(base, url.strip())
    parts = urlsplit(joined)
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if len(path) > 1:
        path = path.rstrip("/")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in TRACKING]
    return urlunsplit((parts.scheme or "https", parts.netloc.lower(), path, urlencode(query, doseq=True), ""))


def make_external_id(title: str, url: str, published: datetime | None, explicit: Any = None) -> str:
    if explicit not in (None, ""):
        return f"id:{explicit}"
    if url:
        return "u:" + canonical_url(url)
    seed = f"{title}|{published.isoformat() if published else ''}".encode()
    return "h:" + hashlib.sha1(seed).hexdigest()[:20]


def dedupe(items: list[Item]) -> list[Item]:
    seen: dict[str, Item] = {}
    for item in items:
        if not item.external_id:
            item.external_id = make_external_id(item.title, item.url, item.published_at)
        old = seen.get(item.external_id)
        if old is None:
            seen[item.external_id] = item
            continue
        # Prefer the richer copy with a date and summary.
        if (item.published_at and not old.published_at) or (len(item.summary) > len(old.summary)):
            seen[item.external_id] = item
    out = list(seen.values())
    out.sort(key=lambda x: x.published_at.timestamp() if x.published_at else 0, reverse=True)
    return out[:MAX_ITEMS_PER_SCAN]


def _unescape_js(text: str) -> str:
    text = html_lib.unescape(text)
    text = text.replace('\\"', '"').replace("\\/", "/")
    text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)
    text = text.replace("\\n", " ").replace("\\t", " ")
    return text


def _normalise_href(href: str, base: str) -> str:
    href = html_lib.unescape(href).strip()
    if href.startswith("//"):
        href = "https:" + href
    return canonical_url(href, base)


def _same_site(url: str, base: str) -> bool:
    try:
        a, b = urlsplit(url).netloc.lower(), urlsplit(base).netloc.lower()
    except ValueError:
        return False
    if not a or not b:
        return True
    a = a[4:] if a.startswith("www.") else a
    b = b[4:] if b.startswith("www.") else b
    return a == b or a.endswith("." + b) or b.endswith("." + a)


def _looks_like_news(href: str, selectors: dict | None = None) -> bool:
    if not href or SKIP_EXT.search(href):
        return False
    path = urlsplit(href).path
    if path in ("", "/"):
        return False
    if selectors and selectors.get("href_contains"):
        needles = selectors["href_contains"]
        if isinstance(needles, str):
            needles = [needles]
        return any(str(n).lower() in href.lower() for n in needles)
    return bool(NEWS_PATH.search(path))


# ---------------------------------------------------------------- JSON-LD

def extract_jsonld(text: str, base: str) -> list[Item]:
    soup = BeautifulSoup(text, "lxml")
    out: list[Item] = []
    for node in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = node.string or node.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        stack = [data]
        while stack:
            cur = stack.pop()
            if isinstance(cur, list):
                stack.extend(cur)
                continue
            if not isinstance(cur, dict):
                continue
            typ = str(cur.get("@type", ""))
            if typ in {"NewsArticle", "Article", "BlogPosting", "Report", "WebPage"} and (cur.get("headline") or cur.get("name")):
                title = clean_text(cur.get("headline") or cur.get("name"), 300)
                url = _normalise_href(str(cur.get("url") or cur.get("mainEntityOfPage") or ""), base)
                pub = parse_date(cur.get("datePublished") or cur.get("dateModified"))
                desc = clean_text(cur.get("description") or cur.get("abstract"), 400)
                if title:
                    out.append(Item(title, url, desc, pub, make_external_id(title, url, pub), {"source": "jsonld"}))
            stack.extend(v for v in cur.values() if isinstance(v, (dict, list)))
    return out


# ---------------------------------------------------------------- Next.js RSC

def extract_rsc(text: str, base: str, selectors: dict | None = None) -> list[Item]:
    page = _unescape_js(text)
    href_re = re.compile(r'"href":"((?:https?://|/)[^"\\]+)"')
    items: list[Item] = []
    seen: set[str] = set()
    for match in href_re.finditer(page):
        href = _normalise_href(match.group(1), base)
        if not _looks_like_news(href, selectors) or href in seen:
            continue
        before = page[max(0, match.start() - 2600):match.start()]
        after = page[match.end():match.end() + 300]
        titles = re.findall(r'"title":"((?:[^"\\]|\\.)*)"', before)
        dates = re.findall(r'"date":"([^"]+)"', before)
        summaries = re.findall(r'"summary":"((?:[^"\\]|\\.)*)"', before)
        title = clean_text(titles[-1], 300) if titles else ""
        if not title:
            continue
        if title in NAV_WORDS:
            continue
        published = parse_date(dates[-1]) if dates else None
        if not published:
            published = extract_date(after)
        summary = clean_text(summaries[-1], 400) if summaries else ""
        seen.add(href)
        items.append(Item(title, href, summary, published, make_external_id(title, href, published), {"source": "rsc"}))
    return dedupe(items)


# ---------------------------------------------------------------- HTML


def _sel(selectors: dict | None, *names: str) -> str:
    selectors = selectors or {}
    for name in names:
        value = selectors.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _select_one(node, selector: str):
    if not selector:
        return None
    try:
        return node.select_one(selector)
    except Exception:  # noqa: BLE001 - invalid user/AI selector
        return None


def _node_value(node, attr: str = "") -> str:
    if node is None:
        return ""
    if attr:
        value = node.get(attr)
        if value:
            return clean_text(value, 600)
    return clean_text(node.get_text(" ", strip=True), 600)


def extract_html_selected(text: str, base: str, selectors: dict | None = None) -> list[Item]:
    """Extract a list using AI/user supplied CSS selectors."""
    selectors = selectors or {}
    item_selector = _sel(selectors, "item", "item_selector", "container", "list_selector")
    if not item_selector:
        return []
    soup = BeautifulSoup(text, "lxml")
    try:
        nodes = soup.select(item_selector)[:MAX_ITEMS_PER_SCAN]
    except Exception:  # noqa: BLE001
        return []
    link_selector = _sel(selectors, "link", "link_selector", "url_selector", "a_selector")
    title_selector = _sel(selectors, "title", "title_selector", "headline_selector")
    date_selector = _sel(selectors, "date", "date_selector", "time_selector")
    summary_selector = _sel(selectors, "summary", "summary_selector", "desc_selector", "description_selector")
    id_selector = _sel(selectors, "id", "id_selector")
    title_attr = _sel(selectors, "title_attr")
    link_attr = _sel(selectors, "link_attr") or "href"
    date_attr = _sel(selectors, "date_attr") or "datetime"
    summary_attr = _sel(selectors, "summary_attr")
    id_attr = _sel(selectors, "id_attr") or "data-id"
    url_template = _sel(selectors, "url_template", "link_template")
    items: list[Item] = []
    for node in nodes:
        link_node = _select_one(node, link_selector) if link_selector else None
        if link_node is None:
            link_node = node.find("a", href=True)
        if link_node is None and getattr(node, "name", "") == "a":
            link_node = node
        href = ""
        if link_node is not None:
            raw_href = link_node.get(link_attr) or link_node.get("href")
            if not raw_href:
                # Many CMS cards put the real URL in data-* when there is no
                # wrapping <a>. Accept the common spellings instead of making
                # the AI/model guess the exact attribute name.
                for fallback_attr in ("data-href", "data-url", "data-link", "data-permalink"):
                    raw_href = link_node.get(fallback_attr)
                    if raw_href:
                        break
            href = _normalise_href(str(raw_href or ""), base)
        if not href and url_template:
            href = _normalise_href(url_template.replace("{href}", "").replace("{id}", str(node.get("data-id") or "")), base)
        if not href or not href.startswith(("http://", "https://")):
            continue
        title_node = _select_one(node, title_selector) if title_selector else link_node
        title = _node_value(title_node, title_attr)
        if not title and link_node is not None:
            title = _anchor_title(link_node)
        if not title:
            title = clean_text(node.get_text(" ", strip=True), 300)
        if len(title) < 2 or len(title) > 300 or title.strip().lower() in NAV_WORDS:
            continue
        date_node = _select_one(node, date_selector) if date_selector else None
        if date_node is None:
            date_node = node.find("time")
        published = None
        if date_node is not None:
            published = parse_date(_node_value(date_node, date_attr))
            if not published:
                published = extract_date(_node_value(date_node))
        if not published:
            published = extract_date(clean_text(node.get_text(" ", strip=True), 400))
        summary_node = _select_one(node, summary_selector) if summary_selector else None
        summary = _node_value(summary_node, summary_attr) if summary_node is not None else ""
        if not summary:
            summary = clean_text(node.get_text(" ", strip=True), 400)
            if title and title in summary:
                summary = summary.replace(title, "", 1).strip(" -|·\n\t")
        explicit = None
        if id_selector:
            id_node = _select_one(node, id_selector)
            if id_node is not None:
                explicit = id_node.get(id_attr) or _node_value(id_node)
        elif node.get("data-id"):
            explicit = node.get("data-id")
        if not explicit and link_node is not None:
            explicit = link_node.get("data-id")
        items.append(Item(
            title, href, summary[:400], published,
            make_external_id(title, href, published, explicit),
            {"source": "html-custom", "selector": item_selector},
        ))
    return dedupe(items)

def _anchor_title(a) -> str:
    text = clean_text(a.get_text(" ", strip=True), 300)
    if text:
        return text
    for attr in ("aria-label", "title"):
        val = clean_text(a.get(attr), 300)
        if val:
            return val
    img = a.find("img")
    if img:
        return clean_text(img.get("alt"), 300)
    heading = a.find(re.compile(r"^h[1-4]$"))
    if heading:
        return clean_text(heading.get_text(" ", strip=True), 300)
    return ""


def extract_html(text: str, base: str, selectors: dict | None = None) -> list[Item]:
    if selectors and _sel(selectors, "item", "item_selector", "container", "list_selector"):
        selected = extract_html_selected(text, base, selectors)
        result = ExtractResult(selected, "html")
        soup_title = BeautifulSoup(text, "lxml")
        result.page_title = clean_text(soup_title.title.get_text(" ", strip=True) if soup_title.title else "", 200)
        if not selected:
            result.notes.append("自定义选择器未匹配到条目")
        return result
    soup = BeautifulSoup(text, "lxml")
    page_title = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "", 200)
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
        tag.decompose()
    candidates: list[tuple[float, Item]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = _normalise_href(a["href"], base)
        if not href.startswith(("http://", "https://")):
            continue
        if not _same_site(href, base):
            continue
        if SKIP_EXT.search(href):
            continue
        title = _anchor_title(a)
        if len(title) < 3 or len(title) > 300 or title.strip().lower() in NAV_WORDS:
            continue
        if href in seen:
            continue
        parent = a.find_parent(["article", "li"]) or a.find_parent(
            class_=re.compile(r"(article|card|item|post|news|list|entry)", re.I)
        )
        scope = parent or a.parent
        scope_text = clean_text(scope.get_text(" ", strip=True), 600) if scope else title
        summary = scope_text.replace(title, "", 1).strip(" -|·\n\t")[:400]
        time_node = scope.find("time") if scope else None
        published = None
        if time_node:
            published = parse_date(time_node.get("datetime") or time_node.get_text(" ", strip=True))
        if not published:
            published = extract_date(scope_text[:300])
        if not published:
            m = re.search(r"(20\d{2})[-/](\d{1,2})(?:[-/](\d{1,2}))?", href)
            if m:
                published = parse_date(f"{m.group(1)}-{m.group(2)}-{m.group(3) or 1}")
        score = 0.0
        low = (title + " " + href).lower()
        score += 3.5 if any(k in low for k in STRONG_HINTS) else 0
        score += 1.5 if any(k in low for k in WEAK_HINTS) else 0
        score += 2.0 if NEWS_PATH.search(urlsplit(href).path) else 0
        score += 1.5 if published else 0
        score += 1.0 if parent else 0
        score += 0.5 if 8 <= len(title) <= 120 else 0
        if score < 2.0 and not NEWS_PATH.search(urlsplit(href).path):
            continue
        seen.add(href)
        candidates.append((score, Item(title, href, summary, published, make_external_id(title, href, published), {"source": "html", "score": score})))
    candidates.sort(key=lambda pair: (pair[1].published_at.timestamp() if pair[1].published_at else 0, pair[0]), reverse=True)
    items = dedupe([item for _, item in candidates])
    if not items:
        # Fallback: any content-looking anchor on the same site.
        for a in soup.find_all("a", href=True):
            href = _normalise_href(a["href"], base)
            title = _anchor_title(a)
            if href.startswith("http") and _same_site(href, base) and 6 <= len(title) <= 200 and href not in seen:
                seen.add(href)
                items.append(Item(title, href, "", None, make_external_id(title, href, None), {"source": "html-fallback"}))
            if len(items) >= MAX_ITEMS_PER_SCAN:
                break
    result = ExtractResult(items, "html")
    result.page_title = page_title
    return result


# ---------------------------------------------------------------- JSON / API

def _dig(data: Any, path: str) -> Any:
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)] if int(part) < len(cur) else None
        else:
            return None
    return cur


def _pick(obj: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in obj and obj[key] not in (None, "", [], {}):
            return obj[key]
        if "." in key:
            val = _dig(obj, key)
            if val not in (None, "", [], {}):
                return val
    return None


def _find_list(data: Any, preferred: list[str] | None = None) -> list:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    if preferred:
        for path in preferred:
            val = _dig(data, path)
            if isinstance(val, list) and val:
                return val
    for key in ("list", "items", "data", "result", "posts", "news", "records", "rows", "content"):
        val = data.get(key)
        if isinstance(val, list) and val:
            return val
        if isinstance(val, dict):
            nested = _find_list(val, preferred)
            if nested:
                return nested
    # last resort: the longest list of dicts
    best: list = []
    for val in data.values():
        if isinstance(val, list) and len(val) > len(best) and any(isinstance(x, dict) for x in val):
            best = val
        elif isinstance(val, dict):
            nested = _find_list(val, preferred)
            if len(nested) > len(best):
                best = nested
    return best


def extract_json(data: Any, base: str, selectors: dict | None = None) -> list[Item]:
    selectors = selectors or {}
    preferred = selectors.get("items_path")
    if isinstance(preferred, str):
        preferred = [preferred]
    rows = _find_list(data, preferred)
    items: list[Item] = []
    def keys(name: str, defaults: tuple[str, ...]) -> tuple[str, ...]:
        value = selectors.get(name)
        if isinstance(value, str):
            value = [value]
        custom = tuple(v for v in (value or []) if isinstance(v, str) and v.strip())
        return custom + tuple(k for k in defaults if k not in custom)
    title_keys = keys("title_keys", _TITLE_KEYS)
    url_keys = keys("url_keys", _URL_KEYS)
    date_keys = keys("date_keys", _DATE_KEYS)
    summary_keys = keys("summary_keys", _SUMMARY_KEYS)
    id_keys = keys("id_keys", ("id", "guid", "post_id", "article_id", "news_id", "content_id"))
    for row in rows:
        if not isinstance(row, dict):
            continue
        if isinstance(row.get("post"), dict):
            row = {**row, **row["post"]}
        title = clean_text(_pick(row, title_keys), 300)
        if not title:
            continue
        raw_url = _pick(row, url_keys)
        if isinstance(raw_url, dict):
            raw_url = raw_url.get("href") or raw_url.get("url")
        template = selectors.get("url_template") if isinstance(selectors, dict) else None
        if template:
            rendered = re.sub(
                r"\{([\w.]+)\}",
                lambda m: str(_dig(row, m.group(1)) or ""),
                str(template),
            )
            url = _normalise_href(rendered, base) if rendered else base
        else:
            url = _normalise_href(str(raw_url), base) if raw_url else base
        pub = parse_date(_pick(row, date_keys))
        summary = clean_text(_pick(row, summary_keys), 400)
        explicit = _pick(row, id_keys)
        ext = make_external_id(title, url if raw_url else "", pub, explicit)
        items.append(Item(title, url, summary, pub, ext, {"source": "json"}))
    return dedupe(items)


# ---------------------------------------------------------------- entrypoint

def extract_items(
    text: str,
    base_url: str,
    strategy: str = "auto",
    selectors: dict | None = None,
    content_type: str = "",
) -> ExtractResult:
    selectors = selectors or {}
    stripped = text.lstrip()
    is_json = "json" in (content_type or "").lower() or stripped.startswith(("{", "["))
    notes: list[str] = []
    page_title = ""

    parsed_json = None
    if is_json:
        try:
            parsed_json = json.loads(text)
        except ValueError:
            notes.append("响应标记为 JSON 但解析失败")

    if strategy == "json" or strategy == "api":
        if parsed_json is None:
            return ExtractResult([], "json", notes + ["JSON 解析失败"], page_title)
        return ExtractResult(extract_json(parsed_json, base_url, selectors), "json", notes, page_title)

    if strategy == "rsc" or (strategy == "auto" and "__next_f" in text):
        items = extract_rsc(text, base_url, selectors)
        if items or strategy == "rsc":
            return ExtractResult(items, "rsc", notes, page_title)
        notes.append("RSC 未提取到条目，降级 HTML")

    if parsed_json is not None and strategy == "auto":
        items = extract_json(parsed_json, base_url, selectors)
        if items:
            return ExtractResult(items, "json", notes, page_title)
        notes.append("JSON 未提取到条目")

    jsonld = extract_jsonld(text, base_url)
    if jsonld:
        notes.append(f"JSON-LD 命中 {len(jsonld)} 条")

    html_result = extract_html(text, base_url, selectors)
    html_result.notes = notes + html_result.notes
    if jsonld:
        html_result.items = dedupe(html_result.items + jsonld)
    return html_result


def page_diagnostics(text: str) -> dict[str, Any]:
    soup = BeautifulSoup(text, "lxml")
    title = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "", 200)
    anchors = len(soup.find_all("a", href=True))
    scripts = len(soup.find_all("script"))
    body_text = clean_text(soup.get_text(" ", strip=True), 5000) if soup.body else ""
    shell_markers = [
        m for m in ("__NEXT_DATA__", "self.__next_f", "__NUXT__", 'id="app"', "id='app'", "v-app", "react-root")
        if m in text
    ]
    return {
        "page_title": title,
        "anchors": anchors,
        "scripts": scripts,
        "body_text_length": len(body_text),
        "shell_markers": shell_markers,
        "looks_js_shell": anchors < 8 and len(body_text) < 1200,
    }
