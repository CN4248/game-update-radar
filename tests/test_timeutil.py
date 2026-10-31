from datetime import datetime, timedelta, timezone

from app.timeutil import age_days, extract_date, parse_date


def test_iso_and_js_dates():
    assert parse_date("2026-10-15T03:36:05Z") == datetime(2026, 10, 15, 3, 36, 5, tzinfo=timezone.utc)
    # JS Date.toString() emits "GMT+0000", which email.utils otherwise ignores.
    assert parse_date("Wed Oct 15 2026 03:36:05 GMT+0000 (Coordinated Universal Time)") == datetime(
        2026, 10, 15, 3, 36, 5, tzinfo=timezone.utc
    )
    assert parse_date("Wed Oct 15 2026 11:00:00 GMT+0800") == datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)


def test_chinese_dates_are_cst():
    dt = parse_date("2026年10月15日 11:00")
    assert dt == datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)


def test_relative_dates_use_reference():
    ref = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    assert parse_date("3 天前", reference=ref) == ref - timedelta(days=3)
    assert parse_date("2小时前", reference=ref) == ref - timedelta(hours=2)


def test_extract_and_age():
    assert extract_date("发布于 2026-10-15 11:00") == datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)
    assert parse_date("not a date") is None
    assert age_days(datetime.now(timezone.utc) - timedelta(days=2)) > 1.9
