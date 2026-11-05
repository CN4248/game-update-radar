from app.categories import (
    normalize_notify,
    notification_kind,
    should_notify,
)
from app.notify import Notification
from app.scanner.classify import classify_rule


def test_rule_categories():
    assert classify_rule("版本更新 1.2.0", "补丁说明").category == "version_update"
    assert classify_rule("服务器停机维护预告", "本周四停服维护").category == "maintenance"
    assert classify_rule("周末活动：双倍经验", "登录领取奖励").category == "event"
    assert classify_rule("赛事更新公告", "锦标赛更新").category == "esports"
    assert classify_rule("招聘公告", "加入我们").category == "recruit"


def test_activity_update_is_not_a_version_update():
    cls = classify_rule("活动更新公告", "限时活动开启")
    assert cls.category == "event"
    # Legacy is_update may be true because of the generic word "更新", but
    # update_only must still not treat this as a patch note.
    assert should_notify(cls.category, cls.is_update, {"mode": "update_only"}) is False


def test_should_notify_modes():
    assert should_notify("version_update", True, {}) is True
    assert should_notify("maintenance", True, {}) is True
    assert should_notify("event", True, {}) is False
    selected = {"mode": "selected", "categories": ["event", "version_update"]}
    assert should_notify("event", False, selected) is True
    assert should_notify("maintenance", True, selected) is False
    assert should_notify("news", False, {"mode": "all"}) is True


def test_normalize_notify_and_notification_kind():
    assert normalize_notify({"mode": "selected", "categories": ["bogus", "event"]}) == {
        "mode": "selected",
        "categories": ["event"],
    }
    assert normalize_notify({})["mode"] == "update_only"
    assert normalize_notify({"mode": "all", "categories": []})["categories"] == []
    note = Notification(
        game="KARDS", title="周末活动", summary="", url="https://example.com",
        kind=notification_kind("event", False),
    )
    assert "活动公告" in note.subject
    assert "活动公告" in note.as_text()
