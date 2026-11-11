## 1. 使用的框架/工具

后端使用 Python 标准库 `logging`（无第三方日志框架），前端仅通过原生 `console.log` 输出调试信息，没有统一的客户端日志框架。

## 2. 关键文件

- `backend/app/main.py`：全局日志初始化与根 logger 创建
- `backend/app/routers/chat.py`、`backend/app/routers/ws.py`、`backend/app/routers/kb_admin.py`、`backend/app/routers/ops.py`、`backend/app/routers/otp.py`：各路由模块的 logger 实例
- `backend/app/storage/runtime_control.py`：运行控制开关的警告日志
- `backend/app/agent/orchestrator.py`、`backend/app/agent/llm.py`、`backend/app/agent/memory.py`、`backend/app/agent/copilot.py`、`backend/app/agent/intent.py`、`backend/app/agent/emotion.py`、`backend/app/agent/humor.py`：Agent 子模块日志
- `backend/app/storage/cache.py`：缓存层日志
- `frontend/src/widget.ts`：前端唯一使用 `console.log` 的地方

## 3. 架构与约定

### 初始化方式
所有模块统一在文件顶部调用：
```python
import logging
logger = logging.getLogger(__name__)
```
全局格式在 `main.py` 中一次性配置：
```python
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
```
因此所有后端日志遵循同一行格式：`时间戳 级别 模块名: 消息`，默认级别为 `INFO`。

### 日志级别用法
- `logger.info(...)`：业务关键路径（知识库加载完成、会话初始化等）
- `logger.warning(...)`：异常但非错误场景（分层记忆维护失败、运行模式切换 Kill Switch、限流触发）
- 未见 `logger.error` / `logger.debug` 的使用；HTTP 异常通过 FastAPI `HTTPException` 返回，未单独记录 error 级日志

### 结构化字段
日志以模板字符串 + `%s` 占位符拼接参数，例如：
- `logger.info("知识库加载完成：%d 条 FAQ，分类 %s", len(kb.faqs), kb.category_stats())`
- `logger.warning("运行模式切换: %s -> %s（Kill Switch）", self._mode, mode)`
没有使用 JSON 结构化日志或字段字典。

### 前端日志
前端仅在 `widget.ts` 中使用 `console.log` 打印 Widget 生命周期事件，无分级、无统一封装，生产环境不会保留。