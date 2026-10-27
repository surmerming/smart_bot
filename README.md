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
│   │   ├── routers/          # chat(init/stream/handover)、session(bind)、feedback、ops(统计)
│   │   ├── agent/            # orchestrator / retriever 决策 / emotion / intent / humor / llm / prompts
│   │   ├── storage/          # db(SQLite) / kb(TF-IDF+BM25) / rate_limit(限流+Token)
│   │   └── models/schemas.py # 前后端契约（Pydantic）
│   ├── tests/                # golden_dataset.json / eval.py / test_api.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/                 # Vite + TS：官网 + Web Component Widget
│   ├── src/
│   │   ├── main.ts / site.ts # 官网（7 个 section，design/ 还原）
│   │   ├── widget.ts         # <xd-chat-widget>（inline / floating）
│   │   ├── sse-client.ts     # POST + SSE 流式解析
│   │   └── api.ts            # 后端 API 封装
│   └── package.json
├── knowledge_base/
│   ├── faq.json              # 知识库唯一数据源（40 条 FAQ + 变体问法）
│   └── build_kb.py           # 一键入库：索引构建 + 健康检查 + 抽样自检
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
| `/api/v1/chat/stream` | POST(SSE) | 核心对话：流式返回回答 + 状态（meta → text → done） |
| `/api/v1/session/bind` | POST | 登录瞬间绑定 anonymous_session_id ↔ user_id |
| `/api/v1/feedback` | POST | 👍/👎 埋点，点踩自动入库（Bad Case 归因） |
| `/api/v1/handover` | POST | 手动转人工 + 预留言 |
| `/api/v1/ops/stats` | GET | 自动化率 / 转人工率（口径：转过人工即归人工） |
| `/api/v1/ops/handovers` | GET | 人工坐席待办列表（留言模式） |

**SSE 事件协议**（前后端契约，见 `frontend/src/sse-client.ts`）：

```
event: meta   {"status":"answering|confirming|handover|limit|blocked","emotion":"LEVEL_0..3",
               "intent":"IN_KNOWLEDGE|...","confidence":0.323,"faq_ids":["faq_001"],
               "faqs":[{"id":"faq_001","title":"售后","score":0.32}],"handover":false,"quick_replies":[...]}
event: text   {"content":"<流式增量>"}
event: done   {"message_id":"msg_xxx","handover":true,"handover_reason":"...","handover_summary":"..."}
```

## 五、设计要点（对应 plan.md）

| 支柱 | 实现 |
|---|---|
| 检索与认知 | TF-IDF 简化向量（jieba 词 + 中文 bigram 混合特征，预留豆包 embedding + Qdrant 替换）+ BM25 双路召回 + RRF 融合；两级相似度阈值（当前 TF-IDF 量纲 <0.22 转人工 / 0.22-0.40 LLM 可回答性判断 / >0.40 直接答；切换真实 Embedding 后按 0.75/0.85 重调） |
| 防幻觉 | ① Prompt 强约束（只答知识库、查不到转人工话术）② 生成前可回答性校验 + NLI 否定句校验 ③ 生成后关键事实校验（数字/时间/金额指纹比对，不通过回退兜底话术） |
| 幽默控制 | 只对售前类 + 情绪绿灯开放幽默；严肃场景（交易/售后/账户/投诉）自动关闭；润色模块（`humor.py`）预留两段式生成 |
| 情绪熔断 | LLM 分级 LEVEL_0-3 + 关键词兜底；红灯（投诉/威胁/风险词）强制转人工并加急标记 |
| 转人工 | 软转人工（澄清挽留 + 快捷选项）；硬转人工（承接话术 + 上下文摘要打包 + SQLite 排队列表） |
| 会话 | SQLite 持久化 + 滑动窗口（最近 5 轮）+ 状态机（AGENT_ACTIVE/CONFIRMING/HANDOVER，可打断）+ 匿名→登录绑定 |
| 安全防刷 | Visitor Token（HMAC 签名校验）+ IP 限流（10 次/分，内存实现可换 Redis）+ 30 轮硬上限 + 超长输入拦截 |
| 流式 | DeepSeek V3（deepseek-chat 非推理）+ SSE 逐 token，首字 < 2s |

## 六、测试与评估

```bash
# 1) 检索评估（黄金测试集 100+ 问法，Mock 离线）
cd backend && python tests/eval.py

# 2) 接口测试（Mock LLM，离线）
cd backend && python -m pytest tests/test_api.py -v
```

`tests/eval.py` 输出 Hit@3 / MRR / 高风险红线命中 / 否定句检查，并列出检索失败案例（建议补变体问法）。

**当前基准（2026-10-27 验证）**：黄金集 100 条命中评估 Hit@3 = 100%、MRR = 0.993（否定句 5/5、高风险红线 10/10、低置信转人工 10/10）；接口测试 `pytest tests/test_api.py` 10/10 通过。前端 `npm run build` 通过，官网 + Widget 已在浏览器实测对话（命中徽章、流式打字机、红灯转人工、floating 弹窗、历史恢复）。**DeepSeek 真实链路已验证**：命中 FAQ 生成真实回答（事实打底 + 幽默润色）、投诉场景 LLM 情绪分级 + 风险词兜底正确转人工。

## 七、生产演进路线（plan V1.5 / V2.0）

- **检索**：TF-IDF → 豆包 text-embedding / BGE-M3 + Qdrant（`docker-compose.yml` 已预留）；Query Rewrite 查询重写
- **记忆**：L2 摘要压缩 + L3 结构化事实（订单号/型号/诉求）
- **转人工**：WebSocket 实时排队 + 坐席工作台（黄金摘要卡片 + 快捷回复模板）
- **运营**：Bad Case 归因周报、Langfuse Trace、自动化巡检
- **安全**：Cloudflare + Turnstile 无感人机验证、Redis 限流

## 八、免责与合规

- Bot 全程披露 AI 身份，绝不伪装真人
- 收集手机号等个人信息前需明确提示
- 服务协议建议明示："AI 客服提供的信息仅供参考，涉及最终交易、价格确认以人工客服最终确认结果为准"
- 对话日志仅用于知识库优化，需符合数据安全规范

---

Copyright 2026 小答智能客服 · 本仓库按 plan.md 实施，设计稿见 `design/`
