"""Rule-based update detection and announcement typing with optional AI override."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..categories import CATEGORY_KEYS
from ..settings import ai_settings
from .ai import AIClient, AIError, extract_json
from .extract import Item

STRONG = (
    "更新", "补丁", "版本", "维护", "停机", "热修", "更新公告", "版本更新", "预下载",
    "patch notes", "hotfix", "maintenance", "downtime", "update", "patch",
)
WEAK = (
    "平衡", "修复", "优化", "新内容", "赛季", "活动", "卡池", "上线", "调整", "bug", "fix",
)
EXCLUDE = (
    "招聘", "周边", "商城", "折扣", "同人", "社区", "赛事", "锦标赛", "直播", "问卷调查",
    "merch", "esports", "tournament", "sale", "recruit", "cosplay",
)

# Keywords that decide the announcement *type*. Generic "更新" is handled
# separately as a weak version signal, because "活动更新" is an activity, not
# a patch note.
CATEGORY_WORDS: dict[str, tuple[str, ...]] = {
    "version_update": (
        "版本", "补丁", "热修", "更新公告", "版本更新", "预下载", "patch notes",
        "hotfix", "patch", "version", "preload",
    ),
    "maintenance": ("维护", "停机", "停服", "downtime", "maintenance"),
    "event": (
        "活动", "赛季", "卡池", "限时", "联动", "庆典", "上线", "新内容",
        "event", "season", "banner",
    ),
    "esports": (
        "赛事", "电竞", "锦标赛", "联赛", "比赛", "直播", "tournament",
        "esports", "league",
    ),
    "merch": ("周边", "商城", "折扣", "促销", "售卖", "merch", "sale", "shop"),
    "community": (
        "同人", "社区", "问卷", "征集", "投票", "共创", "cosplay", "contest",
    ),
    "recruit": ("招聘", "招人", "加入我们", "recruit", "hiring"),
}
CATEGORY_PRIORITY = (
    "maintenance", "version_update", "event", "esports", "merch", "community",
    "recruit", "news",
)
BLOCKED_CATEGORIES = ("esports", "merch", "community", "recruit")


@dataclass
class Classification:
    is_update: bool
    confidence: float
    reason: str
    digest: str = ""
    source: str = "rule"
    category: str = "news"


def _hits(text: str, words: tuple[str, ...]) -> list[str]:
    low = text.lower()
    return [w for w in words if w.lower() in low]


def _pick_category(body: str, blocked: bool) -> str:
    scores: dict[str, float] = {}
    for key, words in CATEGORY_WORDS.items():
        hits = _hits(body, words)
        if hits:
            scores[key] = float(len(hits))
    if "更新" in body:
        scores["version_update"] = scores.get("version_update", 0.0) + 0.5

    blocked_keys = [key for key in BLOCKED_CATEGORIES if scores.get(key, 0) > 0]
    if blocked:
        if not blocked_keys:
            return "news"
        return max(blocked_keys, key=lambda key: (scores[key], -CATEGORY_PRIORITY.index(key)))
    # A maintenance notice that also says "更新" is still a maintenance
    # notice; do not let the generic version signal outrank it.
    if scores.get("maintenance"):
        return "maintenance"
    if scores:
        return max(scores, key=lambda key: (scores[key], -CATEGORY_PRIORITY.index(key)))
    return "news"


def classify_rule(
    title: str,
    summary: str = "",
    *,
    include: str = "",
    exclude: str = "",
) -> Classification:
    title_low = title.lower()
    body = f"{title} {summary}".lower()
    custom_inc = [w.strip() for w in re.split(r"[,，;；\n]", include or "") if w.strip()]
    custom_exc = [w.strip() for w in re.split(r"[,，;；\n]", exclude or "") if w.strip()]
    strong = _hits(body, STRONG) + [w for w in custom_inc if w.lower() in body]
    weak = _hits(body, WEAK)
    blocked = _hits(body, EXCLUDE) + [w for w in custom_exc if w.lower() in body]
    strong_title = [w for w in strong if w.lower() in title_low]
    category = _pick_category(body, bool(blocked))

    if blocked:
        return Classification(
            False, 0.2, "命中排除词：" + "、".join(dict.fromkeys(blocked)), "", "rule", category
        )
    if strong:
        conf = min(0.96, 0.68 + 0.07 * len(set(strong)) + (0.08 if strong_title else 0))
        if category == "news":
            category = "version_update"
        return Classification(
            True, round(conf, 2), "命中更新关键词：" + "、".join(dict.fromkeys(strong)), "",
            "rule", category,
        )
    if len(set(weak)) >= 2:
        if category == "news":
            category = "version_update"
        return Classification(
            True, 0.55, "命中多个弱相关词：" + "、".join(dict.fromkeys(weak)), "", "rule", category
        )
    if weak and ("公告" in title or "说明" in title):
        if category == "news":
            category = "version_update"
        return Classification(
            True, 0.48, "公告标题含弱相关词：" + "、".join(dict.fromkeys(weak)), "", "rule", category
        )
    return Classification(False, 0.1, "未命中更新特征", "", "rule", category)


def classify_items(
    items: list[Item],
    *,
    include: str = "",
    exclude: str = "",
    use_ai: bool = True,
    use_proxy: bool = True,
    max_ai_items: int = 25,
) -> tuple[list[Classification], dict]:
    results = [classify_rule(i.title, i.summary, include=include, exclude=exclude) for i in items]
    meta = {"ai_used": False, "ai_error": None, "model": None}
    cfg = ai_settings()
    if not use_ai or not cfg.get("enabled") or not cfg.get("api_key") or not items:
        return results, meta
    candidates = list(enumerate(items))[:max_ai_items]
    lines = []
    for idx, item in candidates:
        lines.append(
            json.dumps(
                {
                    "id": idx,
                    "title": item.title,
                    "summary": item.summary[:240],
                    "date": item.published_at.isoformat() if item.published_at else None,
                },
                ensure_ascii=False,
            )
        )
    prompt = f"""判断下列游戏官网公告的内容，并给出公告类型 category。
分类标准：
- version_update：版本更新、补丁说明、平衡性调整、热修、预下载、新版本/新内容上线。
- maintenance：停机维护、服务器维护、故障修复公告。
- event：活动、赛季、卡池、限时、联动、庆典、祈愿/通行证上线等运营活动。
- esports：赛事、电竞、锦标赛、联赛、比赛、赛事直播。
- merch：周边商品、商城、折扣、促销、售卖。
- community：社区、同人、问卷、征集、投票、共创、cosplay。
- recruit：招聘、招人、加入我们。
- news：以上都不是的普通新闻/资讯。
同时判断 is_update：true 表示这条公告包含版本/补丁/停机维护等玩家需要立刻知道的影响；纯活动、赛事、周边、社区、招聘、普通新闻为 false。拿不准时 is_update=false，但 category 仍要按内容选择。
对每条输出：
{{"id": 整数, "is_update": true/false, "category": "上面八个英文键之一", "confidence": 0~1, "reason": "15字内中文理由", "digest": "一句不超过40字的摘要，所有类型都可以写"}}

公告列表（每行一个 JSON）：
{chr(10).join(lines)}

严格输出 JSON 对象：{{"items": [ ... ]}}"""
    try:
        client = AIClient(cfg, use_proxy=use_proxy)
        text = client.chat("你是游戏公告分类器，只输出严格 JSON，不臆测。", prompt, max_tokens=1500)
        data = extract_json(text)
        if isinstance(data, dict):
            rows = data.get("items") or data.get("results") or data.get("data") or []
        elif isinstance(data, list):
            rows = data
        else:
            rows = []
        if not isinstance(rows, list) or not rows:
            raise AIError("AI 未返回 items 数组")
        by_id = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                rid = int(row.get("id"))
            except (TypeError, ValueError):
                continue
            if rid < 0 or rid >= len(items):
                continue
            is_update = row.get("is_update")
            if isinstance(is_update, str):
                is_update = is_update.lower() in {"true", "yes", "1", "是"}
            conf = row.get("confidence", 0.7)
            try:
                conf = max(0.0, min(1.0, float(conf)))
            except (TypeError, ValueError):
                conf = 0.7
            category = str(row.get("category") or "").strip().lower()
            if category not in CATEGORY_KEYS:
                category = results[rid].category
            if category in ("version_update", "maintenance"):
                is_update = True
            elif bool(is_update) and category == "news":
                category = "version_update"
            by_id[rid] = Classification(
                bool(is_update),
                round(conf, 2),
                str(row.get("reason") or "AI 判定")[:120],
                str(row.get("digest") or "")[:120],
                "ai",
                category,
            )
        for idx, cls in by_id.items():
            results[idx] = cls
        meta.update({"ai_used": bool(by_id), "model": cfg.get("model")})
        if not by_id:
            raise AIError("AI 判定结果为空")
    except AIError as exc:
        meta["ai_error"] = str(exc)
    return results, meta
