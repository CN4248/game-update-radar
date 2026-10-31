"""Rule-based update detection with optional AI override."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..settings import ai_settings
from ..timeutil import now_iso
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


@dataclass
class Classification:
    is_update: bool
    confidence: float
    reason: str
    digest: str = ""
    source: str = "rule"


def _hits(text: str, words: tuple[str, ...]) -> list[str]:
    low = text.lower()
    return [w for w in words if w.lower() in low]


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
    if blocked:
        return Classification(False, 0.2, "命中排除词：" + "、".join(dict.fromkeys(blocked)), "", "rule")
    if strong:
        conf = min(0.96, 0.68 + 0.07 * len(set(strong)) + (0.08 if strong_title else 0))
        return Classification(True, round(conf, 2), "命中更新关键词：" + "、".join(dict.fromkeys(strong)), "", "rule")
    if len(set(weak)) >= 2:
        return Classification(True, 0.55, "命中多个弱相关词：" + "、".join(dict.fromkeys(weak)), "", "rule")
    if weak and ("公告" in title or "说明" in title):
        return Classification(True, 0.48, "公告标题含弱相关词：" + "、".join(dict.fromkeys(weak)), "", "rule")
    return Classification(False, 0.1, "未命中更新特征", "", "rule")


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
    prompt = f"""判断下列游戏官网公告中，哪些是“游戏更新/补丁/版本/停机维护”公告。
筛选标准：
- true：版本更新、补丁说明、平衡性调整、热修、停机维护、预下载、新版本上线。
- false：赛事、电竞、直播、周边商品、促销、社区活动、同人、招聘、问卷、纯活动公告。
- 摘要为空时按标题判断；不确定时 false。
对每条输出：
{{"id": 整数, "is_update": true/false, "confidence": 0~1, "reason": "15字内中文理由", "digest": "若为更新，写一句不超过40字的影响摘要，否则空字符串"}}

公告列表（每行一个 JSON）：
{chr(10).join(lines)}

严格输出 JSON 对象：{{"items": [ ... ]}}"""
    try:
        client = AIClient(cfg, use_proxy=use_proxy)
        text = client.chat("你是游戏公告分类器，只输出严格 JSON，不臆测。", prompt, max_tokens=1200)
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
            by_id[rid] = Classification(
                bool(is_update),
                round(conf, 2),
                str(row.get("reason") or "AI 判定")[:120],
                str(row.get("digest") or "")[:120],
                "ai",
            )
        for idx, cls in by_id.items():
            results[idx] = cls
        meta.update({"ai_used": bool(by_id), "model": cfg.get("model")})
        if not by_id:
            raise AIError("AI 判定结果为空")
    except AIError as exc:
        meta["ai_error"] = str(exc)
    return results, meta
