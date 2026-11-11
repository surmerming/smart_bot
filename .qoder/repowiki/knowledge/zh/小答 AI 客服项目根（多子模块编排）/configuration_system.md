## 1. 使用方式
- 基于 `python-dotenv`，在 `backend/app/config.py` 启动时加载 `backend/.env`（以 `backend/` 为基准目录），所有运行时参数从环境变量读取。
- 通过 `Settings` 类集中声明全部配置项，并以模块级 `settings = Settings()` 作为全局单例被 FastAPI 入口和各路由、存储模块引用。
- 部署编排由根目录 `docker-compose.yml` 提供 Qdrant（向量库）与 Redis（限流/缓存）服务；MVP 阶段默认注释掉容器依赖，仅启用本地 SQLite + 内存限流。

## 2. 关键文件
- `backend/app/config.py`：唯一配置加载器，定义 `_env_str` / `_env_float` / `_env_int` 三个类型安全的 env 读取器及 `Settings` 类。
- `backend/app/main.py`：FastAPI 入口，导入 `settings`，并在应用初始化阶段调用 `kb.load(str(settings.KB_PATH))` 完成知识库加载，同时暴露 `/health` 健康检查端点输出 `brand`、`llm_mode`、`faqs`。
- `docker-compose.yml`：Qdrant + Redis 的可选生产依赖声明。

## 3. 架构与设计约定
- **单一来源**：除测试外，所有运行期配置只从 `.env` 环境变量获取，不存在 YAML/TOML/JSON 配置文件格式。
- **类型化兜底**：每个配置项都有明确默认值，并提供类型转换辅助函数。布尔型字段统一采用字符串解析：`value.lower() in ("1", "true", "yes", "on")`，如 `QUERY_REWRITE_ENABLED`、`CACHE_ENABLED`、`OTP_MOCK_MODE`。
- **路径拼接策略**：`DB_PATH`、`KB_PATH` 等路径字段以 `BASE_DIR`（即 `backend/`）为基准拼接，便于 Docker 卷挂载或相对路径工作。
- **功能开关集中管理**：LLM 模式通过 `LLM_MODE`（`auto` / `real` / `mock`）控制，并通过 `use_real_llm` 属性派生是否走真实 DeepSeek API。
- **安全敏感字段**：`DEEPSEEK_API_KEY`、`VISITOR_TOKEN_SECRET`、`AGENT_WS_TOKEN` 均无默认值，强制通过环境变量注入；`VISITOR_TOKEN_SECRET` 的默认值为占位符 `change-me-in-production`。
- **业务阈值可配**：检索阈值（`SIM_THRESHOLD_LOW`/`SIM_THRESHOLD_HIGH`）、Top-K（`RETRIEVE_TOP_K`、`RRF_K`）、会话限制（`SESSION_MAX_TURNS`、`SESSION_TIMEOUT_MINUTES`、`CONFIRM_TIMEOUT_SECONDS`、`REPEAT_UNRESOLVED_LIMIT`）、速率限制（`RATE_LIMIT_PER_MIN`）、OTP TTL 等均暴露为环境变量。
- **品牌与 UI 文案可配**：`BRAND_NAME`、`QUICK_CHIPS`（JSON 字符串）允许运行时调整品牌名与首页快捷提问气泡。

## 4. 约定与约束
- **强制要求**：`.env` 必须位于 `backend/.env`，因为 `load_dotenv(BASE_DIR / ".env")` 硬编码了该路径（见 `config.py` 第 8-9 行）。
- **命名约定**：所有环境变量均为大写蛇形命名，与 `Settings` 类中同名属性一一对应。
- **布尔值写法**：布尔型环境变量接受 `1` / `true` / `yes` / `on`（不区分大小写）为真，其余为假。
- **缺失行为**：未设置的环境变量回退到类属性中的默认值，不会抛出异常——这意味着遗漏某些非敏感配置不会产生启动期错误。
- **路径校验**：当前实现不对 `DB_PATH` / `KB_PATH` 是否存在做前置检查，仅在首次读写时失败。
- **扩展规则**：新增配置项应遵循既有模式——在 `Settings` 中以类属性声明并赋予默认值，配套 `_env_*` 类型转换器；若涉及业务逻辑分支（如 LLM_MODE），同步更新相关属性或方法（参考 `use_real_llm`）。