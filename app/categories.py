"""Announcement categories and notification-policy helpers.

Kept dependency-free so both the API layer and the scanner can import it
without creating circular imports.
"""
from __future__ import annotations

from typing import Any

CATEGORIES: tuple[dict[str, str], ...] = (
    {
        "key": "version_update",
        "label": "版本更新",
        "hint": "版本、补丁、热修、预下载",
        "tone": "accent",
    },
    {
        "key": "maintenance",
        "label": "停机维护",
        "hint": "维护、停机、故障修复",
        "tone": "warn",
    },
    {
        "key": "event",
        "label": "活动公告",
        "hint": "活动、赛季、卡池、联动、上线",
        "tone": "ok",
    },
    {
        "key": "esports",
        "label": "赛事电竞",
        "hint": "赛事、锦标赛、联赛、直播",
        "tone": "accent",
    },
    {
        "key": "merch",
        "label": "周边商城",
        "hint": "周边、商城、折扣、促销",
        "tone": "warn",
    },
    {
        "key": "community",
        "label": "社区互动",
        "hint": "社区、同人、问卷、征集",
        "tone": "muted",
    },
    {
        "key": "recruit",
        "label": "招聘",
        "hint": "招聘、招人、加入我们",
        "tone": "muted",
    },
    {
        "key": "news",
        "label": "普通资讯",
        "hint": "未命中其他类型的新闻公告",
        "tone": "muted",
    },
)

CATEGORY_KEYS = tuple(item["key"] for item in CATEGORIES)
CATEGORY_LABELS = {item["key"]: item["label"] for item in CATEGORIES}
CATEGORY_HINTS = {item["key"]: item["hint"] for item in CATEGORIES}
CATEGORY_TONES = {item["key"]: item["tone"] for item in CATEGORIES}

NOTIFY_MODES: tuple[dict[str, str], ...] = (
    {
        "key": "update_only",
        "label": "仅版本更新",
        "hint": "保持旧行为：只提醒被判定为更新或停服维护的公告",
    },
    {
        "key": "selected",
        "label": "按类型提醒",
        "hint": "勾选的公告类型都会提醒，包括活动、赛事、周边等",
    },
    {
        "key": "all",
        "label": "全部新公告",
        "hint": "任何新公告都会提醒；首次基线扫描除外",
    },
)
NOTIFY_MODE_KEYS = tuple(item["key"] for item in NOTIFY_MODES)

DEFAULT_SELECTED_CATEGORIES = ("version_update", "maintenance")
DEFAULT_NOTIFY = {
    "mode": "update_only",
    "categories": list(DEFAULT_SELECTED_CATEGORIES),
}


def normalize_notify(value: Any) -> dict[str, Any]:
    """Return a safe, canonical notify policy.

    An absent ``categories`` key falls back to the defaults; an explicitly
    empty list is respected (that is a deliberate "notify nothing" choice).
    """
    raw = value if isinstance(value, dict) else {}
    mode = str(raw.get("mode") or "update_only").strip()
    if mode not in NOTIFY_MODE_KEYS:
        mode = "update_only"

    raw_categories = raw.get("categories")
    if raw_categories is None:
        selected = list(DEFAULT_SELECTED_CATEGORIES)
    else:
        if isinstance(raw_categories, str):
            raw_categories = [x.strip() for x in raw_categories.replace("，", ",").split(",")]
        if not isinstance(raw_categories, (list, tuple, set)):
            raw_categories = []
        wanted = {str(x).strip() for x in raw_categories if str(x).strip()}
        selected = [key for key in CATEGORY_KEYS if key in wanted]

    return {"mode": mode, "categories": selected}


def should_notify(category: str, is_update: bool, policy: Any) -> bool:
    """Decide whether a newly stored item should trigger an alert."""
    cfg = normalize_notify(policy)
    if cfg["mode"] == "all":
        return True
    if cfg["mode"] == "selected":
        return str(category or "news") in cfg["categories"]
    if not is_update:
        return False
    # ``update_only`` keeps the old "version / maintenance" meaning. A pure
    # activity page whose text happens to contain the generic word "更新"
    # must not slip through as a version update.
    return str(category or "news") in ("version_update", "maintenance", "news")


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(str(category or ""), "普通资讯")


def category_tone(category: str) -> str:
    return CATEGORY_TONES.get(str(category or ""), "muted")


KIND_LABELS = {
    "version_update": "版本更新公告",
    "maintenance": "停机维护公告",
    "event": "活动公告",
    "esports": "赛事公告",
    "merch": "周边公告",
    "community": "社区公告",
    "recruit": "招聘公告",
    "news": "新公告",
}


def notification_kind(category: str, is_update: bool) -> str:
    """Human-readable announcement kind used in the notification headline."""
    key = str(category or "")
    if not key:
        return "版本更新公告" if is_update else "新公告"
    return KIND_LABELS.get(key, "版本更新公告" if is_update else "新公告")
