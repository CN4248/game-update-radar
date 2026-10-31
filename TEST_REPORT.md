# TEST_REPORT — 验证记录（Game Update Radar）

> 每次验证都必须追加一条记录，使用 `project_test`。记录 = 时间 + 步骤 + 方法/命令 + 结果 + 证据。
> 没有证据的"通过"视为无效记录。

## 验证规范

- 单元测试、集成测试、回测、数据校验分别记录，不要合并成一条含糊的结论。
- 证据写：命令、输出摘要、指标数字（收益、夏普、最大回撤、命中率等）。
- 失败也要记录，并写清失败现象与下一步；失败记录不得删除。
- 一个步骤完成前，其最近一条记录必须是"通过"。

<!-- project-flow:begin tests -->
_由 project-flow 维护 · 更新于 2026-10-21 15:19_

| 编号 | 时间 | 步骤 | 验证内容 | 结果 |
| --- | --- | --- | --- | --- |
| T1 | 2026-10-21 12:19 | S1 | 后端骨架、API 与数据层验证 | 通过 |
| T2 | 2026-10-21 12:20 | S2 | KARDS RSC 抓取、基线与增量提醒 | 通过 |
| T3 | 2026-10-21 12:20 | S3 | AI 接入、回退与站点可行性 | 通过 |
| T4 | 2026-10-21 12:20 | S4 | Webhook 实收、渠道失败隔离与调度器 | 通过 |
| T5 | 2026-10-21 12:23 | S5 | WebUI 页面、主题持久化与 390px 响应式 | 通过 |
| T6 | 2026-10-21 12:24 | S6 | Docker Compose、全链路与文档验收 | 通过 |
| T7 | 2026-10-21 13:22 | — | Docker 构建优化配置校验 | 部分通过 |
| T8 | 2026-10-21 13:41 | — | 通知渠道字段渲染与真实发送验收 | 通过 |
| T9 | 2026-10-21 14:14 | S7 | AI 自动修复/创建抓取策略 | 通过 |
| T10 | 2026-10-21 14:15 | S7 | AI 修复失败/冷却提示与回归测试 | 通过 |
| T11 | 2026-10-21 14:52 | S8 | 官方 JSON 接口真实抓取（鸣潮/明日方舟/蔚蓝档案） | 通过 |
| T12 | 2026-10-21 14:52 | S8 | Browserless 渲染降级与跨站防护 | 通过 |
| T13 | 2026-10-21 14:53 | S8 | 全量测试、JS 语法与 compose 配置 | 通过 |
| T14 | 2026-10-21 15:02 | S8 | GameKee 碧蓝档案公告页识别与增量提醒 | 通过 |
| T15 | 2026-10-21 15:19 | — | 默认不拉取 Chromium + 镜像地址可配置 | 通过 |
<!-- project-flow:end tests -->

## 明细

### T1 · 后端骨架、API 与数据层验证 — 通过（2026-10-21 12:19）

- 步骤：S1
- 方法/命令：`curl /api/health; .venv/bin/python -m pytest -q`
- 证据：/api/health 返回 {"status":"ok","version":"1.0.0","db":"ok"}；pytest 24 passed；/api/sources 返回 KARDS/原神/星穹铁道/绝区零 4 个源且 status=ok。
- 备注：—

### T2 · KARDS RSC 抓取、基线与增量提醒 — 通过（2026-10-21 12:20）

- 步骤：S2
- 方法/命令：`curl /api/sources/1/items?limit=3; curl /api/alerts; 查看 logs 基线/增量记录`
- 证据：KARDS 基线抓取 80 条，标题/日期/链接正确；日志 scan.baseline "KARDS 基线完成，80 条"；删除一条已见记录后 scan.incremental "新增 1 条，更新 1 条"，alerts 表生成 1 条 [游戏更新] KARDS · 服务器停机维护预告，status=sent；重复扫描不再重复提醒。
- 备注：—

### T3 · AI 接入、回退与站点可行性 — 通过（2026-10-21 12:20）

- 步骤：S3
- 方法/命令：`.venv/bin/python -m pytest -q; curl -X POST /api/feasibility; curl -X POST /api/sources/3/probe; curl -X POST /api/ai/test -d '{}'`
- 证据：24 passed（含 AI mock、分类与回退用例）；/api/feasibility 对原神官网返回 feasible=false, needs_browser=true（JS 壳，未伪造成功）；/api/sources/3/probe 对星穹铁道 API 返回 feasible=true, item_count=20, sample=https://www.miyoushe.com/sr/article/79023863；无 Key 时 /api/ai/test 返回 {"ok":false,"error":"AI 未启用或未配置 API Key"}，规则链路仍可工作。
- 备注：—

### T4 · Webhook 实收、渠道失败隔离与调度器 — 通过（2026-10-21 12:20）

- 步骤：S4
- 方法/命令：`启动本地 HTTP 接收器；POST /api/channels 创建 webhook 渠道；POST /api/channels/2/test；检查 /tmp/webhook_received.json；pytest tests/test_notify.py`
- 证据：Webhook 实收 HTTP 200，18ms，JSON 含 event/game/title/summary/url/published/reason；KARDS 增量提醒经 Console 投递成功；pytest notify 用例覆盖 9 类渠道校验与失败不崩溃；/api/summary 显示 scheduler.running=true 且每个源有 next_run_at；故障源 http://127.0.0.1:9 返回 status=error、last_error="抓取失败：[Errno 111] Connection refused" 且未崩溃。
- 备注：—

### T5 · WebUI 页面、主题持久化与 390px 响应式 — 通过（2026-10-21 12:23）

- 步骤：S5
- 方法/命令：`node --check web/app.js; 浏览器打开 #/dashboard、#/sources、#/settings、#/logs、#/alerts、#/channels、#/ai；390px iframe 响应式检查；PUT /api/settings/ui 后重启读取`
- 证据：7 个页面截图均正常；390px 宽度下统计卡两列、侧栏隐藏、无横向溢出；主题 aurora（accent #7c5cff、radius 16、density compact）保存后重启仍生效；#/logs 正确显示 ts/module/event 与 JSON 明细；#/alerts 显示 KARDS 提醒与"重发"按钮；app.js node --check 通过。
- 备注：—

### T6 · Docker Compose、全链路与文档验收 — 通过（2026-10-21 12:24）

- 步骤：S6
- 方法/命令：`PyYAML 解析 docker-compose.yml；检查 network_mode/ports/volumes；本地 HTTP 接收器 + 创建 webhook 渠道 + POST /api/alerts/1/resend；pytest -q`
- 证据：compose 解析成功：network_mode=bridge，ports=['${RADAR_PORT:-3155}:3155']，volumes=['./data:/config']；真实 KARDS 提醒重发到本地 webhook，实收 event=game_update、game=KARDS、title=服务器停机维护预告、url=https://www.kardsplayer.com/zh/news/scheduled-server-maintenance-october-2026；故障源错误写入 status/last_error 和 logs；pytest 24 passed；node --check app.js 通过；README 已更新米哈游 API 预设与安全说明。
- 备注：本机没有 Docker 守护进程，未执行镜像构建；已按 S6 验收允许的 YAML+schema 路径校验，实际容器启动由用户执行 `docker compose up -d --build`。

### T7 · Docker 构建优化配置校验 — 部分通过（2026-10-21 13:22）

- 步骤：—
- 方法/命令：`docker compose config; .venv/bin/python -m pytest -q; node --check web/app.js`
- 证据：compose config 解析通过（PIP_INDEX_URL build arg 生效）；pytest 24 passed, 1 warning；node --check 通过。Dockerfile 已去除 apt 层，依赖层加 BuildKit cache mount，pip 支持 --index-url 镜像，安装加 --no-compile。当前环境 Docker daemon 不可用（/var/run/docker.sock 不存在），未实测构建耗时。
- 备注：需在有 Docker daemon 的宿主机执行 `PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple docker compose build --progress=plain` 验证实际耗时；若 BuildKit 关闭，`RUN --mount` 会失败，需启用 BuildKit 或删掉该行。

### T8 · 通知渠道字段渲染与真实发送验收 — 通过（2026-10-21 13:41）

- 步骤：—
- 方法/命令：`CDP Runtime.evaluate 遍历渠道类型；curl POST /api/alerts/1/resend；本地 Webhook 接收器 8898；本地 SMTP 捕获 2526；node --check web/app.js`
- 证据：修复 `web/app.js` 事件监听 id 从 `channel-type` 改为 `ch-type`，新增渠道默认类型改为 email，静态资源版本升至 v=1.0.2。CDP 实测 9 种类型字段数：email 8、telegram 3、webhook 3、bark 3、serverchan 1、pushplus 2、ntfy 4、twilio 4、console 0。UI「保存并测试」Webhook 返回成功，本地接收器收到 HTTP 200 与 `event=game_update` payload；SMTP 测试与真实 KARDS 提醒均被本地 SMTP 捕获（2 封，Subject 含 KARDS）。`POST /api/alerts/1/resend` 返回 4/4 渠道成功（console/webhook/email×2），latency 4–149ms。服务端无异常堆栈，error 日志仅有历史故障注入记录。测试渠道已删除，未留在用户数据库。
- 备注：—

### T9 · AI 自动修复/创建抓取策略 — 通过（2026-10-21 14:14）

- 步骤：S7
- 方法/命令：`.venv/bin/python -m pytest -q; node --check web/app.js; curl -X POST /api/sources/8/repair; curl -X POST /api/sources/7/repair`
- 证据：pytest 29 passed（新增 test_repair.py 5 项：自定义选择器、data-* 链接、失败保留原策略+冷却、扫描 0 条自动修复、修复结果验证）。真实 DeepSeek（deepseek-flash）本地测试页成功：AI 输出 item=section.news-list article.news-card, title=.news-title, link=.news-title, link_attr=data-href, date=.news-date, summary=.news-summary，1 次尝试提取 2 条，保存后排队扫描写入 2 条（1 条判定更新），source 8 返回 ok:true/repaired:true。失败保护：蔚蓝档案（纯前端 SPA）连续 3 次 AI 尝试均提取 0 条，返回 ok:false，原 strategy=auto 未被覆盖，selectors._repair.failed_at=2026-10-21T14:10:20Z，冷却期内自动扫描跳过。node --check 通过；UI 截图 screenshots/repair-success.png、screenshots/repair-ai-settings.png。
- 备注：真实 AI 修复成功一次；蔚蓝档案为纯前端 SPA，无公开 API/RSS，AI 如实判定不可行，未伪造成功。测试用本地源 8 与临时 HTTP 服务已删除。

### T10 · AI 修复失败/冷却提示与回归测试 — 通过（2026-10-21 14:15）

- 步骤：S7
- 方法/命令：`.venv/bin/python -m pytest -q`
- 证据：29 passed, 1 warning（Starlette TestClient httpx 弃用提示）。在 engine 增加 AI 修复失败/冷却的可读 last_error 后重跑，全部通过；/api/sources/7 返回 last_error=未识别到公告条目；AI 修复冷却中，稍后自动重试，last_notes 含 AI 修复跳过原因。
- 备注：仅错误提示文案调整，无行为回退。

### T11 · 官方 JSON 接口真实抓取（鸣潮/明日方舟/蔚蓝档案） — 通过（2026-10-21 14:52）

- 步骤：S8
- 方法/命令：`curl 实抓 + extract_items(strategy=json)`
- 证据：鸣潮 ArticleMenu.json：80 条，最新 2026-10-20T03:00Z，链接 https://mc.kurogames.com/main/news/detail/5655；明日方舟 api/news：6 条，https://ak.hypergryph.com/news/0799；蔚蓝档案 api/news/list：10 条，https://bluearchive-cn.com/news/1983。DB 已建立 7 个源、236 条公告，0 异常。
- 备注：—

### T12 · Browserless 渲染降级与跨站防护 — 通过（2026-10-21 14:52）

- 步骤：S8
- 方法/命令：`fake Browserless + curl /api/browser/test + /api/sources/9/scan`
- 证据：本地 fake sidecar：POST /content 返回 200，header X-Response-URL 指向源站；/api/browser/test 返回 ok=true,status=200,title=Rendered News；源 9（JS 壳）扫描后 last_items_found=2、selectors._render.ok_at 存在、UI 显示「浏览器」标记。同主机校验测试：跨站 evil.example 渲染被拒绝，items 不落库；pytest 38 passed。
- 备注：—

### T13 · 全量测试、JS 语法与 compose 配置 — 通过（2026-10-21 14:53）

- 步骤：S8
- 方法/命令：`.venv/bin/python -m pytest -q && node --check web/app.js && docker compose config`
- 证据：38 passed, 1 warning；node --check 通过；docker compose config 有效，services=radar,browser，radar network_mode=bridge，browser network_mode=service:radar。Docker daemon 不可达，未实际构建/启动 browser 镜像。
- 备注：真实 Browserless 镜像因无 Docker daemon 未运行，使用 fake sidecar 验证协议；生产 compose 已配置 sidecar。

### T14 · GameKee 碧蓝档案公告页识别与增量提醒 — 通过（2026-10-21 15:02）

- 步骤：S8
- 方法/命令：`curl /api/presets/gamekee_ba + /api/sources/13/scan + 模拟删除最新项后重扫`
- 证据：页面 URL 作为监控源：https://www.gamekee.com/ba/notice；实际请求 /v1/content/pageList（带 game-alias: ba 等头），首次扫描 last_items_found=20，链接如 https://www.gamekee.com/ba/724782.html。删除最新项模拟新公告后，产生 alert id=2，标题「【日服】更新公告（北京时间 10/21 10:00）」，status=sent，console 与 Server酱均成功；全量 pytest 39 passed。
- 备注：—

### T15 · 默认不拉取 Chromium + 镜像地址可配置 — 通过（2026-10-21 15:19）

- 步骤：—
- 方法/命令：`docker compose config --quiet; docker compose --profile browser config --quiet; docker compose config --services; .venv/bin/python -m pytest -q`
- 证据：`docker compose config` 与 `--profile browser config` 均通过；`config --services` 默认仅 `radar`，带 profile 为 `radar`+`browser`；pytest 39 passed, 1 warning。Docker daemon 不存在，未做真实拉取耗时对比。
- 备注：默认不再拉取 ghcr.io/browserless/chromium；Browserless 改为 profile 按需启动。PYTHON_IMAGE/BROWSER_IMAGE 可指向镜像加速器。真实构建/拉取耗时需在用户 Docker 主机验证。
