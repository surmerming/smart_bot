# 小答 · RAG 驱动的网页端客服 Agent

> 能自动的高效自动，该转人工的绝不硬扛——幽默是调味料，解决问题才是主菜。

一个基于 RAG（检索增强生成）的网页端客服机器人：从知识库自动回答常见问题，回复风格轻松活泼、偶尔玩梗；
知识库命中时自动应答，未命中 / 高风险 / 情绪激动时自动转人工，并把对话上下文一并打包给人工客服。

本仓库同时包含：
- **官网落地页**（`frontend/`，按 `design/` 设计稿 1:1 还原，Hero 内嵌真实可交互的聊天面板）
- **可嵌入任意网站的 Web Component 聊天 Widget**（右下角悬浮 + 内嵌两种形态）
- **完整后端管线**（FastAPI：混合检索 / 防幻觉 / 情绪熔断 / 幽默分级 / 转人工 / 安全防刷 / SSE 流式）

---

## 一、架构总览

```
[用户端 Web Widget / 官网]
       │  POST + SSE Stream / Visitor Token
       ▼
[FastAPI 异步后端] ──► [SQLite 会话存储（滑动窗口 + 状态机）]
       │
       ├────────────┬───────────────────────────┐
       ▼            ▼                           ▼
[RAG 检索管线]   [AI 认知安全层]            [转人工调度]
- TF-IDF 向量 +  - 三层防幻觉               - 软转人工（澄清挽留）
  BM25 双路召回  - 三级情绪熔断(绿/黄/红)      - 硬转人工（红灯/高风险）
- RRF 融合重排   - NLI 否定句校验             - 上下文自动交接 + 排队
- 两级相似度阈值 - 幽默分级动态控制           - 黄金摘要打包
       │
       ▼
[DeepSeek V3 API（deepseek-chat，SSE 流式，首字 < 2s）]
```

## 二、目录结构

```
smart_bot/
├── backend/                  # Python FastAPI 后端
│   ├── app/
│   │   ├── main.py           # 入口：IP 限流中间件 + 知识库加载 + 路由注册
│   │   ├── config.py         # 配置（.env）
│   │   ├── routers/          # chat(init/stream/handover)、session(bind)、feedback、ops(统计/排队/坐席)、ws(实时通道)
│   │   ├── agent/            # orchestrator / retriever 决策 / emotion / intent / humor / llm / prompts / memory(分层记忆) / copilot(坐席AI)
│   │   ├── storage/          # db(SQLite) / kb(TF-IDF+BM25) / rate_limit(限流+Token) / cache(高频缓存)
│   │   └── models/schemas.py # 前后端契约（Pydantic）
│   ├── tools/badcase_report.py  # Bad Case 归因 → 自动生成 FAQ 草案（V1.5）
│   ├── tests/                # golden_dataset.json / eval.py / test_api.py / load_test.py / test_badcase_report.py / test_v2_ws_copilot.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/                 # Vite + TS：官网 + Widget + 坐席工作台 + 运营看板
│   ├── index.html            # 官网（7 个 section，design/ 还原）
│   ├── agent.html            # 坐席工作台：AI Copilot（工单卡片 / 快捷回复 / 内部系统查询）+ 实时待办（V1.5/V2.0）
│   ├── dashboard.html        # 运营看板：自动化率/转人工率/点赞率/漏斗/Bad Case（V1.5）
│   ├── src/
│   │   ├── main.ts / site.ts # 官网
│   │   ├── widget.ts         # <xd-chat-widget>（inline / floating，含排队进度轮询）
│   │   ├── agent.ts / dashboard.ts  # 坐席 / 看板入口（V1.5）
│   │   ├── sse-client.ts     # POST + SSE 流式解析
│   │   └── api.ts            # 后端 API 封装
│   └── package.json
├── knowledge_base/
│   ├── faq.json              # 知识库唯一数据源（40 条 FAQ + 变体问法）
│   ├── build_kb.py           # 一键入库：索引构建 + 健康检查 + 抽样自检
│   └── suggestions/          # Bad Case 归因产出的 FAQ 草案（V1.5）
├── scripts/check.sh          # 本地一键质量检查：测试+评估+压测+build（V1.5）
├── .github/workflows/ci.yml  # CI 评测流水线：pytest+eval+load+build（V1.5）
├── design/                   # 官网设计稿（s_nav/hero/problem/features/faq/cta/footer）
├── docker-compose.yml        # 生产期 Qdrant + Redis（MVP 无容器依赖）
└── README.md
```

## 三、快速开始

### 0. 一键启动（前后端同时）

```bash
cp backend/.env.example backend/.env   # 填入 DEEPSEEK_API_KEY（首次）

cd smart_bot   # 项目根目录
npm start         # 同时启动后端(8000) + 前端(5173)
npm run stop      # 停止前后端
npm run status    # 查看健康状态
```

打开 http://localhost:5173 即可使用。日志在项目根 `backend.log` / `frontend.log`。有 Key 自动走 DeepSeek 真实模式，未配置则自动 Mock。
（底层驱动脚本为项目根 `dev.sh`，也支持直接 `./dev.sh [start|stop|status]`。）

### 1. 后端（手动方式）

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # 填入 DEEPSEEK_API_KEY（留空则自动进入 Mock 模式）
python ../knowledge_base/build_kb.py   # 知识库入库（可选，服务启动时也会自动构建）
uvicorn app.main:app --reload --port 8000
```

- 健康检查：`curl http://127.0.0.1:8000/health`
- API 文档：`http://127.0.0.1:8000/docs`
- 运营统计：`curl http://127.0.0.1:8000/api/v1/ops/stats`

> **Mock 模式**：未配置 `DEEPSEEK_API_KEY` 时后端自动使用 MockLLM（规则化输出），
> 知识库检索 / 决策 / 转人工 / 轮次熔断全链路可离线跑通；填 Key 即切真实 DeepSeek，无需改代码。

### 2. 前端（官网 + Widget）

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 （/api 自动代理到 8000）
npm run build      # 产物在 dist/，可交给任意静态托管或由后端同源托管
```

打开 `http://localhost:5173` 即可看到官网，右下角有悬浮聊天按钮，Hero 右侧是内嵌聊天面板——都是真实可对话的。

### 3. 知识库维护（运营唯一入口）

编辑 `knowledge_base/faq.json`（Source of Truth，禁止在向量库直接改）→ 运行 `python knowledge_base/build_kb.py` 一键全量重建（40 条毫秒级完成），脚本会输出分类分布、重复率检查和抽样命中自检。

## 四、核心 API

| 接口 | 方法 | 作用 |
|---|---|---|
| `/api/v1/chat/init` | POST | 初始化：下发 Visitor Token + 拉取历史（视觉失忆恢复） |
| `/api/v1/chat/stream` | POST(SSE) | 核心对话：流式返回回答 + 状态（meta → text → done → summary） |
| `/api/v1/session/bind` | POST | 登录瞬间绑定 anonymous_session_id ↔ user_id |
| `/api/v1/feedback` | POST | 👍/👎 埋点，点踩自动入库（Bad Case 归因） |
| `/api/v1/handover` | POST | 手动转人工 + 预留言 |
| `/api/v1/ops/stats` | GET | 自动化率 / 转人工率 / 点赞率（口径：转过人工即归人工） |
| `/api/v1/ops/handovers` | GET | 人工坐席待办列表（留言模式） |
| `/api/v1/ops/queue/status` | GET | V1.5 排队进度（position / ahead），用户侧轮询 |
| `/api/v1/ops/handovers/{id}/complete` | POST | V1.5 坐席标记待办完成 |
| `/api/v1/ops/badcases` | GET | V1.5 点踩记录（Bad Case 归因原料） |
| `/api/v1/ops/copilot/{queue_id}` | GET | V2.0 坐席工单卡片（核心诉求/订单号/Bot已答/未解决） |
| `/api/v1/ops/copilot/templates` | POST | V2.0 一键生成 3 个快捷回复模板 |
| `/api/v1/ops/copilot/query` | POST | V2.0 一键查询内部系统（开发期 Mock，标注演示） |
| `/ws/user?session_id=&visitor_token=` | WS | V2.0 用户端：排队进度 / 人工接入实时推送 |
| `/ws/agent` | WS | V2.0 坐席端：新待办 / 完成事件实时广播（首帧下发快照） |

**WebSocket 事件协议**（V2.0，JSON 消息，见 `backend/app/routers/ws.py`）：

```
用户端收：{"type":"queue","queue_id":155,"position":3,"ahead":2,"status":"waiting"}
          {"type":"agent_joined","queue_id":155}
坐席端收：{"type":"handovers","data":[...]}      # 首帧快照
          {"type":"handover_new","queue_id":155}
          {"type":"handover_done","queue_id":155}
```

降级策略：前端 WebSocket 连接失败自动回退 V1.5 的 5s/15s HTTP 轮询（Widget / 坐席页均已实现）。

**SSE 事件协议**（前后端契约，见 `frontend/src/sse-client.ts`）：

```
event: meta   {"status":"answering|confirming|handover|limit|blocked","emotion":"LEVEL_0..3",
               "intent":"IN_KNOWLEDGE|...","confidence":0.323,"faq_ids":["faq_001"],
               "faqs":[{"id":"faq_001","title":"售后","score":0.32}],"handover":false,
               "quick_replies":[...],"rewritten_query":"<重写后的检索 query，V1.5>"}
event: text   {"content":"<流式增量>"}
event: done   {"message_id":"msg_xxx","handover":true,"handover_reason":"...","handover_summary":"...",
               "cached":true}   # cached=true 表示高频缓存秒回（V1.5）
event: summary {"message":"已转人工排队…","queue_id":155,"session_status":"HANDOVER"}  # 转人工后（V1.5）
```

## 五、设计要点（对应 plan.md）

| 支柱 | 实现 |
|---|---|
| 检索与认知 | TF-IDF 简化向量（jieba 词 + 中文 bigram 混合特征，预留豆包 embedding + Qdrant 替换）+ BM25 双路召回 + RRF 融合；两级相似度阈值（当前 TF-IDF 量纲 <0.22 转人工 / 0.22-0.40 LLM 可回答性判断 / >0.40 直接答；切换真实 Embedding 后按 0.75/0.85 重调）；**V1.5 Query Rewrite：口语化 → 标准问法（与情绪分级并行，仅用于检索召回，安全判断仍用原 query）** |
| 防幻觉 | ① Prompt 强约束（只答知识库、查不到转人工话术）② 生成前可回答性校验 + NLI 否定句校验 ③ 生成后关键事实校验（数字/时间/金额指纹比对，不通过回退兜底话术） |
| 幽默控制 | 只对售前类 + 情绪绿灯开放幽默；严肃场景（交易/售后/账户/投诉）自动关闭；润色模块（`humor.py`）预留两段式生成 |
| 情绪熔断 | LLM 分级 LEVEL_0-3 + 关键词兜底；红灯（投诉/威胁/风险词）强制转人工并加急标记 |
| 转人工 | 软转人工（澄清挽留 + 快捷选项）；硬转人工（承接话术 + 上下文摘要打包 + SQLite 排队列表）；V1.5 排队进度轮询 + 坐席工作台；**V2.0 WebSocket 实时排队（用户侧位置实时变化 / 人工接入即通知，坐席侧新待办秒级广播）+ 坐席 AI Copilot** |
| 会话 | SQLite 持久化 + 滑动窗口（最近 5 轮）+ 状态机（AGENT_ACTIVE/CONFIRMING/HANDOVER，可打断）+ 匿名→登录绑定；**V1.5 分层记忆：L2 超窗增量摘要 + L3 结构化事实（订单号/型号/诉求）注入 Prompt** |
| 安全防刷 | Visitor Token（HMAC 签名校验）+ IP 限流（10 次/分，内存实现可换 Redis）+ 30 轮硬上限 + 超长输入拦截 |
| 流式 | DeepSeek V3（deepseek-chat 非推理）+ SSE 逐 token，首字 < 2s；**V1.5 高频缓存：Top20 首轮问题命中秒回（cached=true，不调 LLM）** |
| 运营闭环 | V1.5 运营看板（自动化率/转人工率/点赞率/漏斗 + Bad Case 列表）+ Bad Case 归因 CLI（缺失/检索弱/生成质量三类 → 自动生成 FAQ 草案）；**V2.0 坐席 AI Copilot：转人工自动生成结构化工单卡片（核心诉求/订单号/Bot已答/未解决）+ 一键快捷回复模板 + 一键查询内部系统（Mock）** |

## 六、测试与评估

```bash
# 1) 检索评估（黄金测试集 100+ 问法，Mock 离线）
cd backend && python tests/eval.py

# 2) 接口测试（Mock LLM，离线）
cd backend && python -m pytest tests/test_api.py tests/test_badcase_report.py tests/test_v2_ws_copilot.py -v

# 3) 并发压测（默认进程内 Mock，零成本；--base 连真实后端）
cd backend && python tests/load_test.py --concurrency 20 --total 120

# 4) 本地一键全量检查（测试 + 评估 + 压测冒烟 + 前端构建）
./scripts/check.sh
```

- `tests/eval.py` 输出 Hit@3 / MRR / 高风险红线命中 / 否定句检查，并列出检索失败案例（建议补变体问法）。
- **CI 流水线**（`.github/workflows/ci.yml`）：push/PR 自动跑 pytest + eval + 压测冒烟 + 前端 build，防负向优化。

**当前基准（2026-10-27 V2.0 验证）**：黄金集 100 条命中评估 Hit@3 = 100%、MRR = 0.993（否定句 5/5、高风险红线 10/10、低置信转人工 10/10）；接口测试 20/20 通过（含 Query Rewrite、分层记忆 L2/L3、高频缓存、排队进度、坐席完成、点赞率、Bad Case 归因、WS 快照/实时广播/Token 鉴权、Copilot 卡片/模板/查询）；进程内并发压测 320 请求成功率 100%、P95 137ms、吞吐 85.8 req/s；前端 `npm run build` 通过（官网 / 坐席 / 看板三页）。**DeepSeek 真实链路已验证**：V1.5 全项 + V2.0 WS 实时排队（转人工 → 坐席秒收新待办、用户 WS 收到位置推送、坐席完成 → 双方实时通知）+ Copilot 真实 LLM 生成（工单卡片正确提取订单号 JD202610270088、3 条可用回复模板、内部系统 Mock 查询）。

## 七、生产演进路线（V3.0 计划）

- **检索**：TF-IDF → 豆包 text-embedding / BGE-M3 + Qdrant（`docker-compose.yml` 已预留）
- **运营**：Langfuse LLM Trace、自动化巡检 CronJob、FAQ 审批流
- **安全**：Cloudflare + Turnstile 无感人机验证、Redis 限流、坐席 WS 接入真实鉴权（AGENT_WS_TOKEN 已留配置位）
- **Copilot 增强**：内部系统查询接真实 API（当前 Mock 标注开发期演示）、回复模板纳入运营审批、多坐席会话协作

## 八、免责与合规

- Bot 全程披露 AI 身份，绝不伪装真人
- 收集手机号等个人信息前需明确提示
- 服务协议建议明示："AI 客服提供的信息仅供参考，涉及最终交易、价格确认以人工客服最终确认结果为准"
- 对话日志仅用于知识库优化，需符合数据安全规范

---

Copyright 2026 小答智能客服 · 本仓库按 plan.md 实施，设计稿见 `design/`
