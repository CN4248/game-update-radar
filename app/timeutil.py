"""Time helpers: store UTC ISO strings, parse many human/JS date formats."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from dateutil import parser as dateparser

CST = timezone(timedelta(hours=8))
_CN_DATE = re.compile(
    r"(?P<y>20\d{2})\s*[年/\-.]\s*(?P<m>\d{1,2})\s*[月/\-.]\s*(?P<d>\d{1,2})\s*日?"
)
_REL = re.compile(r"(?P<n>\d+)\s*(?P<unit>秒|分钟|小时|天|周|个月)前")
_DATE_HINT = re.compile(
    r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}|"
    r"\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+20\d{2}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+20\d{2})",
    re.I,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utcnow().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def to_iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_date(value, *, reference: datetime | None = None) -> datetime | None:
    """Best-effort parse. Returns timezone-aware UTC datetime or None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            ts = float(value)
            if ts > 1e12:  # milliseconds
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a", "-", "未知"}:
        return None
    text = text.replace("（", "(").replace("）", ")")
    ref = reference or utcnow()
    m = _REL.search(text)
    if m:
        n, unit = int(m.group("n")), m.group("unit")
        delta = {
            "秒": timedelta(seconds=n),
            "分钟": timedelta(minutes=n),
            "小时": timedelta(hours=n),
            "天": timedelta(days=n),
            "周": timedelta(weeks=n),
            "个月": timedelta(days=30 * n),
        }[unit]
        return (ref - delta).astimezone(timezone.utc)
    if "昨天" in text:
        return (ref - timedelta(days=1)).astimezone(timezone.utc)
    if "刚刚" in text:
        return ref.astimezone(timezone.utc)
    # ISO 8601 first: dateutil's fuzzy parser can otherwise drop the time and
    # mistake "2026-10-15T03:36:05Z" for a date-only Chinese date.
    try:
        iso = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
        return to_utc(iso)
    except (ValueError, TypeError):
        pass
    # JS Date.toString(): "Wed Oct 21 2026 11:09:00 GMT+0000 (...)"
    cleaned = re.sub(r"\s*\([^)]*\)\s*$", "", text).strip()
    # email.utils ignores the non-standard "GMT+0000" suffix used by JS Date.toString();
    # turn it into a numeric offset so the actual timezone is honoured.
    js_gmt = re.match(r"^(.*\d{2}:\d{2}(?::\d{2})?)\s+GMT([+-]\d{4})$", cleaned)
    if js_gmt:
        cleaned = f"{js_gmt.group(1)} {js_gmt.group(2)}"
    try:
        dt = parsedate_to_datetime(cleaned)
        if dt:
            return to_utc(dt)
    except (TypeError, ValueError, OverflowError):
        pass
    m = _CN_DATE.search(text)
    if m:
        try:
            hour = minute = 0
            tm = re.match(r"\s*(\d{1,2}):(\d{2})", text[m.end():m.end() + 8])
            if tm:
                hour, minute = int(tm.group(1)), int(tm.group(2))
            return datetime(
                int(m.group("y")), int(m.group("m")), int(m.group("d")), hour, minute, tzinfo=CST
            ).astimezone(timezone.utc)
        except ValueError:
            pass
    try:
        dt = dateparser.parse(text, fuzzy=True)
        if dt:
            return to_utc(dt)
    except (ValueError, OverflowError, TypeError):
        pass
    return None


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        # Official sites usually publish in China time; naive dates are treated as CST.
        dt = dt.replace(tzinfo=CST)
    return dt.astimezone(timezone.utc)


def extract_date(text: str) -> datetime | None:
    if not text:
        return None
    m = _DATE_HINT.search(text)
    if not m:
        return None
    value = m.group(0)
    tail = text[m.end():m.end() + 12]
    tm = re.match(r"\s+(\d{1,2}:\d{2}(?::\d{2})?)", tail)
    if tm:
        value += " " + tm.group(1)
    return parse_date(value)


def age_days(dt: datetime | None) -> float | None:
    if not dt:
        return None
    return (utcnow() - dt).total_seconds() / 86400.0
