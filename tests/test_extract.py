import json

from app.scanner.extract import (
    canonical_url,
    dedupe,
    extract_html,
    extract_items,
    extract_rsc,
    page_diagnostics,
)


def test_rsc_kards_shape():
    payload = (
        '<html><body><script>self.__next_f.push([1,"{'
        '\\"title\\":\\"KARDS 更新 - 2026 年 10 月\\",'
        '\\"summary\\":\\"本次更新包含平衡性调整。\\",'
        '\\"date\\":\\"Wed Oct 15 2026 03:36:05 GMT+0000 (Coordinated Universal Time)\\",'
        '\\"href\\":\\"/zh/news/kards-update-october-2026\\"}"])</script></body></html>'
    )
    result = extract_items(payload, "https://www.kardsplayer.com/zh/news", "rsc")
    assert result.strategy == "rsc"
    assert len(result.items) == 1
    item = result.items[0]
    assert item.title == "KARDS 更新 - 2026 年 10 月"
    assert item.url == "https://www.kardsplayer.com/zh/news/kards-update-october-2026"
    assert item.published_at.isoformat() == "2026-10-15T03:36:05+00:00"
    assert item.summary.startswith("本次更新")


def test_rsc_repeated_titles_on_different_urls_survive():
    payload = """<script>self.__next_f.push([1,"[
      {\\"title\\":\\"更新公告\\",\\"date\\":\\"2026-10-01\\",\\"href\\":\\"/news/a\\"},
      {\\"title\\":\\"更新公告\\",\\"date\\":\\"2026-10-02\\",\\"href\\":\\"/news/b\\"}
    ]"])</script>"""
    items = extract_rsc(payload, "https://example.com/news")
    assert {i.url for i in items} == {"https://example.com/news/a", "https://example.com/news/b"}


def test_html_list_extraction():
    html = """
    <html><head><title>游戏公告</title></head><body>
      <article><a href="/news/update-1">版本更新 1.2</a>
        <time datetime="2026-10-01">2026-10-01</time><p>更新内容与修复</p></article>
      <article><a href="/news/event-2">周末活动</a>
        <time datetime="2026-10-02">2026-10-02</time><p>活动公告</p></article>
    </body></html>
    """
    result = extract_html(html, "https://example.com/news")
    assert len(result.items) == 2
    assert result.items[0].url.startswith("https://example.com/news/")
    assert result.page_title == "游戏公告"


def test_json_api_extraction():
    payload = json.dumps([
        {"title": "版本更新 2.0", "url": "https://example.com/news/2", "date": "2026-10-03", "summary": "新版本"},
        {"title": "社区活动", "url": "https://example.com/news/3", "date": "2026-10-02", "summary": "活动"},
    ])
    result = extract_items(payload, "https://example.com/news", "json")
    assert result.strategy == "json"
    assert len(result.items) == 2


def test_canonical_and_dedupe():
    assert canonical_url("https://example.com/a?utm_source=x&id=1#frag") == "https://example.com/a?id=1"
    items = extract_rsc(
        """<script>self.__next_f.push([1,"[
          {\\"title\\":\\"更新\\",\\"href\\":\\"/news/a?utm_source=x\\"},
          {\\"title\\":\\"更新\\",\\"href\\":\\"/news/a\\"}
        ]"])</script>""",
        "https://example.com/news",
    )
    assert len(items) == 1


def test_shell_diagnostics():
    diag = page_diagnostics("<html><body><script>self.__next_f.push([])</script></body></html>")
    assert diag["looks_js_shell"] is True
    assert diag["anchors"] == 0
    assert "self.__next_f" in diag["shell_markers"]


def test_json_url_template():
    payload = json.dumps({
        "data": {"list": [{"post": {"post_id": "79023863", "subject": "4.6版本活动跃迁", "created_at": 1792476011}}]}
    })
    result = extract_items(
        payload,
        "https://api-takumi.mihoyo.com/post/wapi/getNewsList?gids=6&page_size=5&type=1",
        "json",
        selectors={
            "items_path": "data.list",
            "url_template": "https://www.miyoushe.com/sr/article/{post_id}",
        },
    )
    assert len(result.items) == 1
    assert result.items[0].url == "https://www.miyoushe.com/sr/article/79023863"
