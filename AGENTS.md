# AGENTS — 开发约束（Game Update Radar）

> 所有参与本项目的对话/子代理开工前必读。与任务描述冲突时以本文件为准，除非用户显式豁免。

## 1. 环境与技术栈

- Python 3.12（容器 `python:3.12-slim`），依赖用 `requirements.txt` 锁定版本；本地用 `uv venv .venv && uv pip install -r requirements.txt`。
- 后端：FastAPI + Uvicorn + httpx + APScheduler + BeautifulSoup4/lxml + python-dateutil + cryptography。
- 存储：SQLite（标准库 `sqlite3`，WAL 模式），文件 `/config/radar.db`。
- 前端：原生 HTML/CSS/JS，**无构建步骤、无 CDN、无框架**；图标用内联 SVG。
- 容器：应用服务 `radar` 端口 3155，`network_mode: bridge`，卷 `./data:/config`，`CONFIG_DIR=/config`；可选 `browser` 服务（Browserless Chromium）通过 `network_mode: "service:radar"` 共享网络，应用调用 `127.0.0.1:3000/content`。

## 2. 目录与文件约定

```
app/
  main.py           FastAPI 应用、路由、启动/关闭
  db.py             SQLite 连接、schema、迁移
  settings.py       设置读写、密钥脱敏/加密
  models.py         Pydantic 请求/响应模型
  scanner/
    fetch.py        httpx 客户端、代理、重试
    extract.py      HTML/RSC/JSON/API 提取、日期解析、去重
    classify.py     规则 + AI 更新判定
    ai.py           OpenAI 兼容 / Anthropic 客户端、可行性分析
    presets.py      内置站点预设
    engine.py       单源扫描编排、基线、提醒落库
    repair.py       AI 生成/验证声明式抓取策略（不执行模型代码）
    browser.py      Browserless /content 客户端、同主机校验
  notify.py         通知渠道发送器
  scheduler.py      APScheduler 调度
web/
  index.html style.css app.js favicon.svg
tests/              pytest
data/               本地运行数据（gitignore）
Dockerfile docker-compose.yml requirements.txt README.md .env.example
```

- 不在 `web/` 引入 npm/打包器。
- 不在业务代码硬编码 `/workspace` 等本机路径；一切经 `CONFIG_DIR`。
- 文档三件套固定在根目录。

## 3. 代码质量门禁

- 改动后必须通过：`.venv/bin/python -m pytest -q`；应用可启动：`CONFIG_DIR=./data .venv/bin/uvicorn app.main:app --port 3155`。
- 所有对目标站的出站请求必须走 `scanner.fetch.build_client()` 或同一代理配置，禁止裸 `httpx.get`（通知/AI 也复用代理）。调用本机 Browserless sidecar 的 `httpx` 请求不受此限，但必须集中在 `scanner/browser.py`。
- AI 生成的抓取策略只能包含受控的 CSS 选择器/URL/JSON 字段路径；必须经 `repair.py` 的真实抓取验证后才能落库，禁止 `eval`/`exec` 或执行模型返回的代码；AI 候选 URL 不得指向与源站不同的内网地址。
- 浏览器渲染只能通过 `scanner/browser.py` 调用 Browserless，禁止在应用进程内启动 Chromium；渲染结果的最终主机必须与源站一致（允许 `www.` 差异），否则丢弃。
- 时间入库用 UTC ISO8601；日志用标准 `logging`，禁止 `print` 调试残留。
- 关键路径必须有测试：日期解析、KARDS RSC 提取、去重、更新判定、API 增删改查。
- SQL 一律参数化；外部 HTML 不得直接插入 DOM（前端用 `textContent`/转义）。
- 不提交 `data/`、`.venv/`、`__pycache__`、密钥。

## 4. 禁止事项

- 禁止伪造验证结果或把未运行的测试写进 TEST_REPORT.md。
- 禁止把 API Key/邮箱密码/机器人 Token 明文写进仓库、日志、错误响应。
- 禁止为迁就实现修改 STRATEGY.md 的业务规则（需用户确认）。
- 禁止删改既有测试来变绿；失败必须记录并说明。
- 禁止引入 Playwright/Selenium 等 Python 重依赖；浏览器能力由独立 Browserless sidecar 提供。
- 禁止在前端使用 `innerHTML` 拼接用户/站点文本。

## 5. 验证要求

- 每完成一个可验证节点调用 `project_test`，evidence 必须含命令 + 输出摘要/数字。
- 通过标准：pytest 全绿；API smoke 返回 2xx；KARDS 实抓 ≥10 条；增量扫描能产生 1 条提醒；Webhook 实测收到 payload；浏览器渲染用 fake sidecar 或真实 Browserless 验证；官方 JSON 预设至少一项实抓通过；UI 截图无布局溢出。
- 外部站点测试若因网络/反爬失败，记录 `blocked` 与原始错误，不得写成 pass。

## 6. 文档维护

- STRATEGY.md：业务规则；实现与规则不一致时先改代码或先说明。
- AGENTS.md：本文件；技术栈/目录变化同步更新。
- TEST_REPORT.md：每次验证追加，含时间、step、命令、证据。
- README.md：面向用户的部署/配置/排障说明，随功能同步。

## 7. 交接协议

- 上下文 high/critical 或用户要求交接：`project_check(fix=true)` → `project_handoff` → 停止改代码。
- 新对话先用 `project_resume` 读文档，不推翻已记录决策。

## 文档维护义务

- 任何行为变更先更新 STRATEGY.md，再改实现；验收证据写入 TEST_REPORT.md。
- 每次改动后至少运行 `pytest -q` 与 `node --check web/app.js`；涉及抓取时补一次真实站点扫描。
- 新增抓取策略、通知渠道或设置项时，同步更新 README 与 WebUI 提示文案。
- 不把密钥、明文密码、Cookie 写入日志、截图或测试夹具。
