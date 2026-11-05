from app.scanner.classify import classify_items, classify_rule
from app.scanner.extract import Item


def test_strong_keyword_is_update():
    result = classify_rule("KARDS 更新 - 2026 年 10 月", "本次更新包含平衡性调整")
    assert result.is_update is True
    assert "更新" in result.reason


def test_exclusion_dominates_strong_keyword():
    result = classify_rule("赛事更新公告", "锦标赛更新")
    assert result.is_update is False
    assert "排除" in result.reason


def test_two_weak_keywords_are_update():
    result = classify_rule("平衡与修复说明", "本次调整")
    assert result.is_update is True


def test_custom_exclude():
    result = classify_rule("版本更新", include="", exclude="版本")
    assert result.is_update is False


def test_classify_items_without_ai(monkeypatch):
    import app.scanner.classify as mod

    monkeypatch.setattr(mod, "ai_settings", lambda: {"enabled": False, "api_key": ""})
    items = [Item("版本更新 1.0", "https://example.com/1"), Item("招聘公告", "https://example.com/2")]
    results, meta = classify_items(items, use_ai=True)
    assert [r.is_update for r in results] == [True, False]
    assert meta["ai_used"] is False
