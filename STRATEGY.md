# STRATEGY — Game Update Radar

> 本文件是业务规则与方向取舍的唯一事实来源。规则先改这里，再改实现。

## 1. 项目目标

- 目标：做一个可自托管的「游戏更新雷达」。用户录入游戏名/官网新闻页，服务按计划抓取，识别新的更新/补丁/维护公告，并通过邮件、短信、IM、Webhook 等渠道提醒。
- 交付形态：`docker compose up -d` 启动应用容器 + Browserless Chromium sidecar；Web 端口 **3155**；应用 `network_mode: bridge`，browser 共享应用网络命名空间；数据持久化到宿主机 `./data:/config`。
- 技术形态：Python 3.12 + FastAPI + SQLite + APScheduler + httpx + 原生 WebUI（无构建步骤）。
- 明确不做（首版）：不做游戏启动器/自动下载；不做登录态抓取；不绕过付费墙或验证码；不做多租户账号体系。

## 2. 可行方向

<!-- project-flow:begin plan -->
_由 project-flow 维护 · 更新于 2026-10-21 15:02 · 状态：已交付_

### 2.1 候选方向

| # | 方向 | 概要 | 优点 | 缺点 |
| --- | --- | --- | --- | --- |
| D1 | Python FastAPI + SQLite + 原生 WebUI | 单体 Python 服务，APScheduler 定时，httpx 抓取，SQLite 存储，FastAPI 直接托管无构建步骤的原生 SPA。 | 镜像小、启动快、依赖少；代理/AI/邮件库成熟；静态前端无需 Node 构建，容器内易排障。 | 复杂交互需手写 JS；JS 重度站点需后续加 Playwright。 |
| D2 | Node.js + React + Playwright | NestJS/Express 后端 + React 前端，Playwright 渲染动态站点。 | 前端生态好；能抓 JS 渲染站点。 | 镜像 1GB+、内存高；构建链复杂；对 KARDS 这类 RSC 页面并不需要浏览器。 |
| D3 | n8n 工作流 + 轻量门户 | 用 n8n 负责定时与通知，额外做一个配置门户。 | 通知节点丰富、可视化编排。 | 两套服务、两套配置，AI 判定与站点适配难版本化；不满足单容器 3155 端口的简洁交付。 |

### 2.2 选定方向与理由

**Python FastAPI + SQLite + 原生 WebUI**

单容器、端口 3155、./data:/config 的交付约束下，Python 单体最稳；抓取层可同时支持 HTML/RSC/JSON，KARDS 已确认是 Next.js RSC 页面，无需浏览器；原生 SPA 免构建，容器内可直接改样式和排障。Playwright 留作后续可选扩展，不进入首版依赖。

### 2.3 步骤计划

| 步骤 | 内容 | 任务 | 验收标准 | 负责人 | 状态 |
| --- | --- | --- | --- | --- | --- |
| S8 | 浏览器渲染与官方接口接入 | 1) 新增 Browserless sidecar 与应用内 /content 客户端; 2) 扫描 0 条时自动渲染并校验最终主机; 3) 补充鸣潮/明日方舟/蔚蓝档案官方 JSON 预设; 4) WebUI 浏览器设置、源卡片标记与测试; 5) 文档、compose 与测试 |  | main | 已完成 |
<!-- project-flow:end plan -->

## 3. 业务规则

### 3.1 站点与扫描

- 一个「监控源」= 游戏名 + 新闻列表 URL + 抓取策略 + 扫描间隔 + 是否启用。
- 抓取策略：`auto` / `html` / `rsc` / `json` / `api`。`auto` 依次尝试 JSON、RSC、HTML；前一种提取不到 ≥1 条时降级。
- 默认扫描间隔 60 分钟，允许 5–10080 分钟；调度器每 30 秒检查一次到期源。
- 抓取超时 30 秒，最多重试 2 次（指数退避 1s/3s）。任意一次失败必须写日志，源状态置为 `error`，不中断其它源。
- 代理：全局代理配置对所有应用出站请求生效（抓取、AI、通知、代理测试）；单源可通过 `use_proxy=false` 绕过。支持 http/https/socks5 代理与 no_proxy。Browserless 容器的出网代理需在 compose 的 `browser.environment` 单独设置，应用代理不会自动注入 Chromium。
- 单轮扫描并发上限 3 个源；同一源禁止并发扫描。
- 浏览器渲染：`auto`/`html`/`rsc` 源提取 0 条且 `browser.auto_render=true` 时，先调用 Browserless `/content` 渲染；渲染结果的最终主机必须与源 URL 同主机（允许 `www.` 差异），否则拒绝；渲染后仍 0 条才进入 AI 修复。`json`/`api` 源不跑浏览器。
- 官方 API 优先：内置预设只把已实测通过的 JSON 接口标记为 `verified`；未验证站点保留 `auto`，必须由可行性检测/浏览器/AI 修复实际验证，不得伪造成功。
- 首次扫描只建立基线（baseline），默认不推送历史公告；可选发送一条「开始监控」通知。基线完成后 `baseline_done=1`。
- 增量扫描：以 `external_id`（规范化 URL path；无 URL 时 `sha1(title|published_at)`）去重；新 ID 才进入判定。
- AI 自动修复：页面抓取成功但提取到 0 条时，若 AI 已启用且 `ai.auto_repair=true`，允许 AI 提出 HTML 选择器、JSON 接口或 RSC 链接片段等声明式策略；每个候选必须真实抓取并提取验证，至少 1 条有效标题+链接才保存；最多 `repair_max_attempts`（默认 3，范围 1–5）次。失败保留原策略并写 `scan.repair` 日志，冷却 `repair_cooldown_minutes`（默认 360）内不再自动重试。手动「AI 修复」可绕过冷却，但同样必须验证通过才保存。
- 自动修复不得执行 AI 生成的代码，不得访问与源站不同的本机/内网地址，不得处理登录、验证码或 Cookie；AI 判断 `cannot` 时如实记录不可行，不得伪造成功。
- 发布超过 `max_age_days`（默认 45 天）的条目视为旧闻，只入库不提醒；无日期条目保留但置信度降级。
- 站点连续失败 5 次后，源状态标记 `degraded`，仍继续重试；成功一次即恢复 `ok`。

### 3.2 更新判定

- 规则判定（无 AI 或 AI 失败时也必须可工作）：
  - 强关键词（命中即视为更新）：`更新`、`补丁`、`版本`、`维护`、`停机`、`热修`、`更新公告`、`版本更新`、`预下载`、`patch notes`、`patch`、`update`、`hotfix`、`maintenance`、`downtime`。
  - 弱关键词（需 ≥1 个强词或 2 个弱词）：`平衡`、`修复`、`优化`、`新内容`、`赛季`、`活动`、`卡池`、`上线`、`调整`、`bug`、`fix`。
  - 排除词（单独命中则判定为非更新）：`招聘`、`周边`、`商城`、`折扣`、`同人`、`社区`、`赛事`、`锦标赛`、`直播`、`问卷调查`、`merch`、`esports`、`tournament`、`sale`、`recruit`。
  - 判定：强词命中且未被排除词支配 → `is_update=true`；否则 `false`。标题权重高于摘要。
- AI 判定：启用 AI 后，将标题/摘要/日期/链接批量送入模型，要求返回严格 JSON；AI 结论优先于规则。AI 超时/报错/JSON 非法 → 自动回退规则判定并记录 warning，**不得丢提醒**。
- 每条判定保存 `reason`（规则命中词或 AI 理由）与 `confidence`（0–1），用于 UI 展示和排障。
- 提醒内容：游戏名、公告标题、发布时间、摘要（≤180 字）、链接、判定理由。可选 AI 生成一句话影响摘要。

### 3.3 通知

- 支持渠道：邮件 SMTP、Telegram Bot、通用 Webhook、Bark、Server酱、PushPlus、ntfy、Twilio SMS、Console（写日志，用于本地验证）。
- 渠道可独立启停；每条提醒按启用渠道逐一发送，单渠道失败不影响其它渠道。
- 每个渠道发送失败自动重试 2 次（间隔 2s/5s），仍失败则记录 `failed` 与错误文本，UI 可手动重发。
- 发送结果按「提醒 × 渠道」记录状态：`sent` / `failed` / `skipped`。
- 提供「测试渠道」按钮，不依赖真实公告，发送固定测试消息。
- 邮件正文同时提供纯文本与 HTML；主题包含 `[游戏更新]` 前缀。

### 3.4 AI 接入

- 支持 OpenAI 兼容接口（DeepSeek、OpenAI、Moonshot、通义、Ollama 等，自定义 base_url）与 Anthropic Messages API。
- 默认预设：DeepSeek `https://api.deepseek.com/v1`，模型 `deepseek-chat`。
- API Key 仅存于 `/config` 数据库，接口返回时脱敏；日志不得打印 Key。
- AI 超时 45 秒；温度默认 0.1；要求 JSON 输出，解析失败先尝试提取 ```json 代码块/首尾花括号，再失败则回退。
- 「AI 可行性检测」：对用户输入的新官网 URL 抓取样本，返回是否可监控、推荐策略/选择器、样本条目、风险说明；无 Key 时用启发式规则给出可行性。
- 「AI 自动修复」：扫描提取到 0 条时，先按规则尝试 Browserless 渲染；仍为 0 条才把页面结构摘要与候选接口交给模型生成声明式策略，逐条真实抓取验证；成功保存 `selectors` 与 `_repair` 元数据，失败记录原因和冷却时间。禁止模型生成并执行代码。

### 3.5 WebUI

- 页面：总览、监控源、提醒记录、通知渠道、AI 与网络、运行日志、关于。
- 主题：内置 7 套（深空蓝、极光紫、森林绿、日落橙、玫瑰红、深海青、浅色日间），支持自定义主色/背景色；设置持久化到服务端，刷新后保留。
- 所有耗时操作有 loading/禁用态；API 错误以 toast 展示并写入日志。
- 移动端可用（≤768px 侧栏折叠）。
- 不使用外部 CDN，容器离线可用；中文字体使用系统字体栈。

### 3.6 数据与运维

- 数据目录由 `CONFIG_DIR` 指定，Docker 中固定 `/config`；SQLite 文件 `radar.db`，加密密钥 `secret.key`。
- 时间统一以 UTC ISO8601 入库，界面按浏览器本地时区显示；调度时区默认 `Asia/Shanghai`，可配置。
- 日志保留最近 5000 条；提醒记录保留 365 天；公告条目保留 730 天。
- 健康检查：`GET /api/health` 返回 `{status:"ok", version, db:"ok"}`。
- 备份：UI/接口支持导出配置与源为 JSON（不含明文密钥，可选含密钥需二次确认）。

## 4. 风险与约束

- 部分官网为纯客户端渲染或强反爬（Cloudflare/验证码）。系统内置 Browserless 渲染 sidecar 处理普通 SPA；遇到登录/验证码/Cloudflare 挑战仍会失败，可行性检测标记 `needs_browser`，应改用公开 JSON API/RSS。
- Browserless 是独立容器，首次拉取约 1GB、常驻内存数百 MB；小内存机器需限制并发或内存。它不是 Python 依赖，不影响应用镜像大小。
- KARDS 官网为 Next.js RSC 流式页面，列表不在 DOM 中，必须解析 `self.__next_f.push` 载荷。
- 原神/崩坏：星穹铁道/绝区零官网新闻页为 JS 壳；已改用米哈游公开内容 API（api-takumi.mihoyo.com，gids=2/6/8），预设内置 items_path 与 url_template，实测各 20 条且链接正确。
- 用户未提供 AI Key 时，系统必须完整可用（规则判定），UI 明示「AI 未配置」。
- 无内置鉴权：默认监听 0.0.0.0:3155，README 明确建议置于反向代理/内网，或后续版本加密码。

## 5. 未决问题

- [ ] 是否需要内置登录鉴权（首版不做，文档标注）。
- [x] 浏览器渲染已用 Browserless sidecar 实现；后续评估是否内置更多官方 API 预设。

## 监控与提醒规则

- 首次扫描只建立基线，不为历史公告发送提醒；之后只处理 `external_id` 未见过的条目。
- 更新判定：强关键词（版本更新、更新公告、补丁、停服维护等）优先；弱关键词需日期/摘要辅助；排除词（招聘、赛事、周边等）直接降权；AI 仅在启用且配置 Key 时复核，AI 失败必须回退规则，不得丢失提醒。
- 无发布日期的公告置信度 ×0.8；超过 `general.max_age_days`（默认 45 天）的旧公告只入库、不提醒。
- 同一公告以规范化 URL/hash 去重；同一源扫描期间禁止重入；通知失败重试 2 次并记录每个渠道的结果。
- 通知渠道按启用状态全部投递；任一渠道成功即视为提醒已送达，全部失败标记为 failed 并保留重发入口。
- 代理对所有抓取、AI 请求和 Webhook/IM 通知生效；SMTP 由 Python 直连邮件服务器，不走 HTTP 代理，README 已注明。

## 交易规则

本项目不涉及金融交易，无下单/持仓/风控规则。与“交易规则”对应的业务规则是上文章节《监控与提醒规则》：首次扫描只建基线；只对未见过的公告判定更新；规则优先、AI 复核失败回退；旧公告不入提醒；通知失败可重发。
