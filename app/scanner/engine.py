"""Single-source scan pipeline: fetch, extract, classify, persist, alert."""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime

from .. import db, notify
from ..config import HTTP_TIMEOUT, MAX_NEW_ITEMS_TO_CLASSIFY
from ..settings import channel_raw, get_conn
from ..timeutil import age_days, now_iso
from .classify import Classification, classify_items
from .browser import BrowserError, browser_settings, render as render_page, same_site
from .extract import Item, clean_text, extract_items, page_diagnostics
from .fetch import FetchError
from .repair import fetch_source, public_attempts, repair_source

logger = logging.getLogger(__name__)

_SCAN_LOCK = threading.Lock()
_SCAN_SEMAPHORE = threading.BoundedSemaphore(3)
_INFLIGHT: set[int] = set()


def scan_source(source_id: int, *, force: bool = False, force_repair: bool = False) -> dict:
    """Run one scan. Never raises: returns {ok, ...} for the API/log."""
    with _SCAN_LOCK:
        if source_id in _INFLIGHT:
            return {"ok": False, "error": "该监控源正在扫描中"}
        _INFLIGHT.add(source_id)
    if not _SCAN_SEMAPHORE.acquire(timeout=120):
        with _SCAN_LOCK:
            _INFLIGHT.discard(source_id)
        return {"ok": False, "error": "扫描并发已满，请稍后重试"}

    started = time.monotonic()
    try:
        source = db.get_source(source_id)
        if not source:
            return {"ok": False, "error": "监控源不存在"}
        selectors = db.json_load(source.get("selectors"), {})
        try:
            fetched = fetch_source(source, selectors, timeout=HTTP_TIMEOUT)
        except (FetchError, ValueError) as exc:
            error = str(exc)
            _finish(source_id, None, False, error, 0, 0, 0, [])
            return {"ok": False, "error": error, "source_id": source_id}

        result = extract_items(
            fetched.text,
            fetched.final_url,
            strategy=source.get("strategy") or "auto",
            selectors=selectors,
            content_type=fetched.content_type,
        )
        diag = page_diagnostics(fetched.text)
        notes = list(result.notes) + [
            f"页面标题：{diag.get('page_title') or '（空）'}",
            f"HTTP {fetched.status}，耗时 {fetched.elapsed_ms}ms，策略 {result.strategy}",
        ]
        repair: dict | None = None
        browser_info: dict | None = None
        browser_error = ""
        if not result.items:
            # JavaScript shells often return a tiny HTML document. Try the
            # sidecar before spending AI tokens; the rendered DOM is also the
            # much better input for automatic strategy repair.
            bcfg = browser_settings()
            strategy = (source.get("strategy") or "auto").lower()
            if (
                bcfg.get("enabled")
                and bcfg.get("auto_render", True)
                and strategy not in {"json", "api"}
            ):
                try:
                    rendered = render_page(
                        source["url"],
                        wait_ms=int(bcfg.get("wait_ms") or 1200),
                        timeout=float(bcfg.get("timeout_seconds") or 45),
                    )
                    if not same_site(source["url"], rendered.final_url):
                        raise BrowserError(
                            f"浏览器最终地址与监控源不一致：{rendered.final_url}"
                        )
                    b_strategy = (source.get("strategy") or "auto").lower()
                    if b_strategy not in {"html", "rsc"}:
                        b_strategy = "auto"
                    b_result = extract_items(
                        rendered.text,
                        rendered.final_url,
                        strategy=b_strategy,
                        selectors=selectors,
                        content_type=rendered.content_type,
                    )
                    b_diag = page_diagnostics(rendered.text)
                    browser_info = {
                        "ok": bool(b_result.items),
                        "elapsed_ms": rendered.elapsed_ms,
                        "status": rendered.status,
                        "bytes": len(rendered.text),
                        "items_found": len(b_result.items),
                    }
                    fetched = rendered
                    diag = b_diag
                    result = b_result
                    if b_result.items:
                        notes.append(
                            f"浏览器渲染成功：{len(b_result.items)} 条，"
                            f"{rendered.elapsed_ms}ms，最终地址 {rendered.final_url}"
                        )
                        _save_render_meta(source_id, selectors, rendered)
                    else:
                        notes.append(
                            "浏览器渲染完成，但仍未识别到公告条目；继续让 AI 检查渲染后的页面"
                        )
                except BrowserError as exc:
                    browser_error = str(exc)
                    browser_info = {"ok": False, "error": browser_error}
                    notes.append(f"浏览器渲染失败：{browser_error}")
            if not result.items:
                repair = repair_source(
                    source, fetched=fetched, diagnostics=diag, force=force_repair,
                )
                if repair.get("ok"):
                    fresh = db.get_source(source_id)
                    if fresh:
                        source = fresh
                    selectors = db.json_load(source.get("selectors"), {})
                    result = repair["result"]
                    fetched = repair.get("fetched") or fetched
                    diag = page_diagnostics(fetched.text)
                    notes.append(
                        f"AI 自动修复成功：第 {len(repair.get('attempts') or [])} 次尝试，策略 {repair.get('strategy')}，识别 {len(result.items)} 条"
                    )
                else:
                    error = "页面可访问，但未识别到公告条目"
                    notes.append(json.dumps(diag, ensure_ascii=False))
                    if repair.get("skipped"):
                        notes.append(f"AI 修复跳过：{repair.get('error')}")
                        error = "未识别到公告条目；AI 修复冷却中，稍后自动重试"
                    elif repair.get("error"):
                        notes.append(f"AI 修复失败：{repair.get('error')}")
                        error = "AI 自动修复失败：" + str(repair.get("error"))[:160]
                    _finish(source_id, fetched, False, error, 0, 0, 0, notes)
                    return {
                        "ok": False, "error": error, "source_id": source_id, "diagnostics": diag,
                        "notes": notes,
                        "repair": _repair_public(repair),
                        **({"browser": browser_info} if browser_info else {}),
                    }

        baseline = not bool(source.get("baseline_done"))
        if baseline:
            inserted, alerts = _handle_baseline(source, result.items, notes)
        else:
            inserted, alerts = _handle_incremental(source, result.items, notes, force=force)

        _finish(source_id, fetched, True, "", len(result.items), inserted, alerts, notes)
        logger.info(
            "scan source=%s ok items=%s new=%s alerts=%s baseline=%s",
            source_id, len(result.items), inserted, alerts, baseline,
        )
        return {
            "ok": True,
            "source_id": source_id,
            "baseline": baseline,
            "items_found": len(result.items),
            "new": inserted,
            "alerts": alerts,
            "strategy": result.strategy,
            "page_title": diag.get("page_title") or "",
            "notes": notes,
            "elapsed_ms": fetched.elapsed_ms,
            **({"repair": _repair_public(repair)} if repair else {}),
            **({"browser": browser_info} if browser_info else {}),
        }
    except Exception as exc:  # noqa: BLE001 - scanning must never kill the worker
        logger.exception("scan source=%s crashed", source_id)
        error = f"{type(exc).__name__}: {exc}"
        _finish(source_id, None, False, error, 0, 0, 0, [])
        return {"ok": False, "error": error, "source_id": source_id}
    finally:
        _SCAN_SEMAPHORE.release()
        with _SCAN_LOCK:
            _INFLIGHT.discard(source_id)
        logger.info("scan source=%s finished in %.1fs", source_id, time.monotonic() - started)


def scan_source_async(source_id: int) -> bool:
    with _SCAN_LOCK:
        if source_id in _INFLIGHT:
            return False
        _INFLIGHT.add(source_id)
    # scan_source will re-check and see itself, so remove the reservation first.
    with _SCAN_LOCK:
        _INFLIGHT.discard(source_id)
    threading.Thread(target=scan_source, args=(source_id,), daemon=True).start()
    return True


def _save_render_meta(source_id: int, selectors: dict, rendered) -> None:
    """Remember that this source was successfully rendered by the sidecar."""
    try:
        meta = dict(selectors or {})
        meta["_render"] = {
            "ok_at": now_iso(),
            "final_url": rendered.final_url,
            "status": rendered.status,
            "elapsed_ms": rendered.elapsed_ms,
        }
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE sources SET selectors=?, updated_at=? WHERE id=?",
                (json.dumps(meta, ensure_ascii=False), now_iso(), source_id),
            )
    except Exception:  # noqa: BLE001 - metadata must never fail a scan
        logger.exception("failed to save browser metadata source=%s", source_id)


def _repair_public(repair: dict | None) -> dict:
    if not repair:
        return {"ok": False, "attempts": []}
    out = {k: v for k, v in repair.items() if k not in {"fetched", "result"}}
    out["attempts"] = public_attempts(repair.get("attempts"))
    return out


def _handle_baseline(source: dict, items: list[Item], notes: list[str]) -> tuple[int, int]:
    classes, meta = classify_items(
        items,
        include=source.get("keywords_include") or "",
        exclude=source.get("keywords_exclude") or "",
        use_ai=False,
        use_proxy=bool(source.get("use_proxy")),
        max_ai_items=0,
    )
    if meta.get("ai_error"):
        notes.append(f"AI 基线判定跳过：{meta['ai_error']}")
    max_age = int(_general().get("max_age_days") or 45)
    inserted = 0
    latest = ""
    with db.get_conn() as conn:
        for item, cls in zip(items, classes):
            if _exists(conn, source["id"], item):
                continue
            old = (age_days(item.published_at) or 0) > max_age
            is_update = bool(cls.is_update and not old)
            reason = "历史基线，仅入库不提醒" if is_update else ("旧闻，仅入库" if old else cls.reason)
            _insert_item(conn, source, item, cls, is_update=is_update, reason=reason, notified=0)
            inserted += 1
            latest = max(latest, item.published_at.isoformat() if item.published_at else now_iso())
        conn.execute(
            "UPDATE sources SET baseline_done=1, status='ok', fail_count=0, last_success_at=?, last_error='', last_item_at=? WHERE id=?",
            (now_iso(), latest or None, source["id"]),
        )
    notes.append(f"首次扫描：建立基线 {len(items)} 条（新入库 {inserted} 条），不发送历史提醒")
    db.log_event("info", "scan.baseline", f"{source['name']} 基线完成，{len(items)} 条", source_id=source["id"])
    return inserted, 0


def _handle_incremental(source: dict, items: list[Item], notes: list[str], *, force: bool) -> tuple[int, int]:
    with db.get_conn() as conn:
        new_items = [item for item in items if not _exists(conn, source["id"], item)]
    if not new_items:
        notes.append("没有发现新公告")
        return 0, 0
    notes.append(f"发现 {len(new_items)} 条新公告，开始判定")
    classes, meta = classify_items(
        new_items,
        include=source.get("keywords_include") or "",
        exclude=source.get("keywords_exclude") or "",
        use_ai=True,
        use_proxy=bool(source.get("use_proxy")),
        max_ai_items=MAX_NEW_ITEMS_TO_CLASSIFY,
    )
    if meta.get("ai_used"):
        notes.append(f"AI 判定已启用（{meta.get('model')}）")
    if meta.get("ai_error"):
        notes.append(f"AI 判定失败，已回退规则：{meta['ai_error']}")

    max_age = int(_general().get("max_age_days") or 45)
    inserted = 0
    alert_count = 0
    latest = ""
    with db.get_conn() as conn:
        for item, cls in zip(new_items, classes):
            age = age_days(item.published_at)
            old = age is not None and age > max_age
            is_update = bool(cls.is_update and not old)
            confidence = float(cls.confidence)
            reason = cls.reason
            if old:
                reason = f"旧闻（发布 {age:.0f} 天前，超过 {max_age} 天），仅入库"
            elif not item.published_at:
                confidence = round(confidence * 0.8, 2)
                reason = f"{reason}（无发布日期，置信度降级）"
            item_id = _insert_item(
                conn, source, item, cls, is_update=is_update, reason=reason,
                confidence=confidence, notified=0,
            )
            inserted += 1
            latest = max(latest, item.published_at.isoformat() if item.published_at else now_iso())
            if is_update:
                alert_id = _create_alert(conn, source, item, item_id, cls, reason)
                alert_count += 1
            else:
                alert_id = 0
            conn.commit()  # make item/alert visible to the sender and UI immediately
            if is_update and alert_id:
                sent = _dispatch_alert(alert_id, source, item, cls, reason)
                if sent:
                    conn.execute("UPDATE items SET notified=1 WHERE id=?", (item_id,))
        conn.execute(
            "UPDATE sources SET last_item_at=?, status='ok', fail_count=0, last_success_at=?, last_error='' WHERE id=?",
            (latest or None, now_iso(), source["id"]),
        )
    db.log_event(
        "info", "scan.incremental",
        f"{source['name']}：新增 {inserted} 条，更新 {alert_count} 条",
        source_id=source["id"],
    )
    return inserted, alert_count


def _insert_item(conn, source: dict, item: Item, cls: Classification, *, is_update: bool,
                 reason: str, confidence: float | None = None, notified: int = 0) -> int:
    cur = conn.execute(
        """INSERT OR IGNORE INTO items
        (source_id, external_id, title, url, summary, published_at, is_update, confidence,
         reason, ai_summary, raw, first_seen_at, notified)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            source["id"], item.external_id, item.title[:500], item.url[:1000],
            clean_text(item.summary, 1200),
            item.published_at.isoformat() if item.published_at else None,
            1 if is_update else 0,
            round(float(confidence if confidence is not None else cls.confidence), 2),
            reason[:500], cls.digest[:500],
            json.dumps(item.raw or {}, ensure_ascii=False)[:8000],
            now_iso(), notified,
        ),
    )
    if cur.rowcount:
        return int(cur.lastrowid)
    row = conn.execute(
        "SELECT id FROM items WHERE source_id=? AND external_id=?",
        (source["id"], item.external_id),
    ).fetchone()
    return int(row["id"]) if row else 0


def _exists(conn, source_id: int, item: Item) -> bool:
    row = conn.execute(
        "SELECT 1 FROM items WHERE source_id=? AND external_id=?",
        (source_id, item.external_id),
    ).fetchone()
    return bool(row)


def _create_alert(conn, source: dict, item: Item, item_id: int, cls: Classification, reason: str) -> int:
    note = _notification(source, item, cls, reason)
    cur = conn.execute(
        """INSERT INTO alerts(source_id, item_id, title, message, status, channel_results, created_at)
        VALUES (?,?,?,?,?,?,?)""",
        (source["id"], item_id, note.subject[:500], note.as_text(), "detected", "[]", now_iso()),
    )
    return int(cur.lastrowid)


def _dispatch_alert(alert_id: int, source: dict, item: Item, cls: Classification, reason: str) -> bool:
    note = _notification(source, item, cls, reason)
    with db.get_conn() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM channels WHERE enabled=1 ORDER BY id").fetchall()]
    if not rows:
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE alerts SET status='skipped', channel_results=?, sent_at=? WHERE id=?",
                (json.dumps([{"error": "未配置可用的通知渠道"}], ensure_ascii=False), now_iso(), alert_id),
            )
        db.log_event("warning", "notify", f"{source['name']} 有新更新，但未配置通知渠道", source_id=source["id"])
        return False
    results = []
    any_sent = False
    for row in rows:
        try:
            channel = channel_raw(row)
        except Exception as exc:  # noqa: BLE001
            results.append({"channel_id": row.get("id"), "name": row.get("name"), "ok": False,
                            "status": "failed", "message": f"配置解密失败：{exc}"})
            continue
        result = notify.send_with_retries(channel, note)
        results.append(result)
        any_sent = any_sent or bool(result.get("ok"))
    ok_count = sum(1 for r in results if r.get("ok"))
    status = "sent" if ok_count == len(results) else ("partial" if ok_count else "failed")
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE alerts SET status=?, channel_results=?, sent_at=? WHERE id=?",
            (status, json.dumps(results, ensure_ascii=False)[:20000], now_iso(), alert_id),
        )
    level = "info" if ok_count else "error"
    db.log_event(level, "notify",
                 f"{source['name']}：{ok_count}/{len(results)} 个渠道发送成功",
                 source_id=source["id"],
                 detail=json.dumps(results, ensure_ascii=False)[:4000])
    return any_sent


def _notification(source: dict, item: Item, cls: Classification, reason: str) -> notify.Notification:
    published = ""
    if item.published_at:
        published = item.published_at.astimezone().strftime("%Y-%m-%d %H:%M")
    return notify.Notification(
        game=source["name"],
        title=item.title,
        summary=clean_text(item.summary, 600),
        url=item.url,
        published=published,
        reason=reason,
        digest=cls.digest or (cls.reason if cls.source == "ai" else ""),
        source_url=source["url"],
    )


def _general() -> dict:
    from ..settings import get_setting

    try:
        return get_setting("general", mask=False)
    except Exception:  # noqa: BLE001
        return {}


def _finish(source_id: int, fetched, ok: bool, error: str, items_found: int,
            new_count: int, alert_count: int, notes: list[str]) -> None:
    now = now_iso()
    status = "ok" if ok else "error"
    try:
        with db.get_conn() as conn:
            row = conn.execute("SELECT fail_count, name FROM sources WHERE id=?", (source_id,)).fetchone()
            if not row:
                return
            fail_count = 0 if ok else int(row["fail_count"] or 0) + 1
            if not ok and fail_count >= 5:
                status = "degraded"
            conn.execute(
                """UPDATE sources SET status=?, fail_count=?, last_scan_at=?, last_error=?,
                   last_http_status=?, last_items_found=?, last_notes=?
                   WHERE id=?""",
                (
                    status, fail_count, now, (error or "")[:1000],
                    getattr(fetched, "status", 0) or 0, items_found,
                    json.dumps(notes, ensure_ascii=False)[:6000], source_id,
                ),
            )
        if not ok:
            db.log_event("error", "scan", f"{row['name']} 扫描失败：{error[:300]}", source_id=source_id,
                         detail="\n".join(notes))
    except Exception:  # noqa: BLE001
        logger.exception("failed to persist scan result source=%s", source_id)


def resend_alert(alert_id: int) -> dict:
    """Re-dispatch an existing alert to all currently enabled channels."""
    with db.get_conn() as conn:
        row = conn.execute(
            """SELECT a.*, s.name AS source_name, s.url AS source_url,
                      i.title AS item_title, i.url AS item_url, i.summary AS item_summary,
                      i.published_at AS item_published_at, i.reason AS item_reason,
                      i.ai_summary AS item_digest, i.confidence AS item_confidence,
                      i.external_id AS item_external_id, i.raw AS item_raw
               FROM alerts a
               LEFT JOIN sources s ON s.id=a.source_id
               LEFT JOIN items i ON i.id=a.item_id
               WHERE a.id=?""",
            (alert_id,),
        ).fetchone()
    if not row:
        return {"ok": False, "error": "提醒不存在"}
    row = dict(row)
    if not row.get("item_id") or not row.get("source_id"):
        return {"ok": False, "error": "提醒对应的公告或监控源已被删除"}
    from ..timeutil import parse_date

    item = Item(
        title=row["item_title"], url=row["item_url"] or "", summary=row["item_summary"] or "",
        published_at=parse_date(row["item_published_at"]), external_id=row["item_external_id"] or "",
        raw=db.json_load(row["item_raw"], {}),
    )
    source = {"id": row["source_id"], "name": row["source_name"] or "未知游戏", "url": row["source_url"] or ""}
    cls = Classification(
        is_update=True, confidence=float(row["item_confidence"] or 0),
        reason=row["item_reason"] or "手动重发", digest=row["item_digest"] or "", source="manual",
    )
    sent = _dispatch_alert(alert_id, source, item, cls, row["item_reason"] or "手动重发")
    with db.get_conn() as conn:
        fresh = conn.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
    return {"ok": sent, "alert": _alert_out(dict(fresh)) if fresh else None}


def _alert_out(row: dict) -> dict:
    row = dict(row)
    row["channel_results"] = db.json_load(row.get("channel_results"), [])
    return row
