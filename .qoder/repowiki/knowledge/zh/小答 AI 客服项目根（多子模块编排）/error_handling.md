## 总体方案

本仓库没有统一的异常类、全局异常处理器或中间件级错误转换层。后端采用 FastAPI 的 `HTTPException` 直接抛出业务错误，由 FastAPI 自动将其序列化为 JSON；应用侧仅注册了一个基于 IP 的限流中间件（返回 429），除此之外无全局异常处理逻辑。前端在 `api.ts` 中统一将非 `ok` 响应包装为 `Error` 对象向上抛出，各页面再各自 `catch` 并渲染到 DOM。

## 后端模式

- **业务参数校验**：路由中直接 `raise HTTPException(status_code=..., detail=...)`，例如 `chat.py` 中的 `401 invalid visitor token`、`404 session not found`、`503 service maintenance`；`ops.py` 中的 `400 invalid mode / gray_percent / rating`、`404 queue item not found`、`410 otp expired`；`otp.py` 中的 `400 no otp sent / phone mismatch`、`400 invalid code`。
- **异步/网络/外部调用容错**：使用 `try/except Exception as exc` 包裹 LLM 调用与记忆维护逻辑，捕获后 `logger.warning(...)` 并降级返回空结果或继续执行，而不是向上传播。典型位置：
  - `agent/orchestrator.py` 中对 `asyncio.CancelledError` 做特殊分支处理；
  - `agent/emotion.py`、`agent/copilot.py` 中捕获 `Exception` 记录日志后返回默认值；
  - `storage/rate_limit.py` 中捕获 `Exception` 回退到无限制路径；
  - `routers/chat.py` 中 `_update_memory` 对结构化事实提取和摘要压缩失败时仅 `logger.warning` 后 `return`。
- **JSON 解析防御**：`storage/db.py` 多处用 `try/except json.JSONDecodeError` 对历史消息/元数据字段做兼容读取，避免脏数据导致整条查询失败。
- **配置加载**：`config.py` 使用 `try/except (TypeError, ValueError)` 为布尔型环境变量提供默认值。
- **限流中间件**：`main.py` 通过 `@app.middleware("http")` 实现 `/api/` 前缀的 IP 级 10次/分钟 限流，超限返回 `JSONResponse(429, {"detail": "请求太频繁啦，请稍后再试", "remaining": ...})`。
- **无自定义异常类型**：未定义任何继承自 `Exception` 的业务异常类，也未注册 `@app.exception_handler` 做统一错误体封装。

## 前端模式

- **HTTP 错误集中化**：`frontend/src/api.ts` 定义 `post/get/put/del` 四个封装函数，统一判断 `resp.ok`，失败时 `throw new Error(`API ${path} 失败(${resp.status}): ${text.slice(0, 120)}\`)`，从而让上层调用方无需重复检查状态码。
- **SSE 客户端错误**：`frontend/src/sse-client.ts` 对 `fetch` 失败也构造带状态码的 `Error` 抛出。
- **UI 展示**：各模块 (`agent.ts`、`dashboard.ts`、`kb.ts`、`widget.ts`) 在各自的 `try/catch` 中将错误文本写入 `$("error")` 元素或 Widget 内部的 `.xd-error` 节点；`widget.ts` 提供 `pushError(text)` 私有方法统一插入红色提示块。
- **WebSocket 降级**：`widget.ts` 中 `ws.onerror` 触发轮询兜底；连接初始化失败时输出 `[xd-chat] init failed:` 日志和用户可读提示。

## 约定与约束（观察到的行为）

- 后端路由层的非法输入一律以 `HTTPException` 形式暴露给客户端，状态码集中在 400/401/404/410/503，没有业务错误码枚举。
- 所有可能抛异常的第三方调用（LLM、记忆压缩、情绪分析、copilot 工具等）都被 `try/except Exception` 包裹，并通过 `logger.warning/info` 记录后降级，不中断主流程。
- JSON 字段的读取普遍使用 `try/except json.JSONDecodeError` 做向后兼容，允许旧库数据中存在脏值。
- 前端 HTTP 调用全部经 `api.ts` 封装，禁止在业务代码里直接 `fetch` 后裸判断 `resp.ok`；错误统一转为 `Error` 对象上抛。
- 前端 UI 的错误展示遵循“写入 `$("error")` 或 widget 的 `.xd-error` 节点”这一模式，CSS 类名固定为 `error` 或 `xd-error`。
- 限流失败路径（`rate_limit.py`）被 `except Exception` 保护，保证限流组件故障不会阻断正常请求。
- 未发现 `panic/recover` 语义（Python 不适用），也未发现 `fastapi.HTTPException` 之外的自定义异常体系或全局异常处理器。