## 1. 构建系统概览

本项目采用**脚本驱动的多子模块编排式构建**，没有统一的 Makefile 或 Bazel 等构建工具。四个子模块（`backend/`、`frontend/`、`knowledge_base/`、根级 `scripts/`）通过根目录的 shell 脚本和 Docker Compose 组合启动；CI 使用 GitHub Actions 分别对后端与前端执行独立的构建与测试。

- 本地开发：`dev.sh` 同时拉起 FastAPI 后端（uvicorn, 端口 8000）与 Vite 前端（端口 5173），并通过轮询 `/health` 等待后端就绪。
- 依赖服务：可选地用 `docker-compose.yml` 拉起 Qdrant（向量库）与 Redis（限流/缓存）。
- CI：`.github/workflows/ci.yml` 在 push main 与 PR 上运行后端 pytest + eval + load smoke 以及前端的 TypeScript 类型检查与 vite build。

## 2. 关键文件

| 文件 | 作用 |
|---|---|
| `dev.sh` | 本地一键启动/停止/状态检查脚本，固定后端 8000、前端 5173 端口 |
| `docker-compose.yml` | 可选生产期依赖服务（Qdrant + Redis） |
| `.github/workflows/ci.yml` | GitHub Actions CI，分 backend / frontend 两个 job |
| `frontend/package.json` | Vite + TypeScript 构建入口，`build` 脚本为 `tsc && vite build` |
| `package.json`（根） | 暴露 `npm start/stop/status` 作为 `dev.sh` 的别名 |
| `backend/requirements.txt` | Python 依赖清单（由 CI 安装） |
| `scripts/check.sh` | 本地质量检查脚本（被 CI 之外的开发者调用） |

## 3. 架构与约定

### 3.1 本地开发流程
- `./dev.sh start`（默认动作）会先清理占用 8000/5173 端口的进程，再分别以 `nohup ... & disown` 后台启动后端与前端的 dev server，PID 写入根目录 `.backend.pid` / `.frontend.pid`，日志输出到根目录 `backend.log` / `frontend.log`。
- 后端启动后通过循环最多 40 次、间隔 0.5s 轮询 `http://127.0.0.1:8000/health` 确认就绪，超时即继续。
- 前端通过 `cd frontend && npm run dev` 启动 Vite dev server。
- `./dev.sh stop` 用 `lsof -ti :PORT | xargs kill -9` 强制杀进程并删除 PID 文件。
- `./dev.sh status` 通过 curl 探测 `/health` 与前端根路径判断存活。
- 根 `package.json` 将 `npm start/stop/status` 代理到 `bash dev.sh`，便于通过 npm 脚本统一入口。

### 3.2 容器化
- `docker-compose.yml` 仅定义 `qdrant`（镜像 `qdrant/qdrant:latest`, 卷 `qdrant_data:/qdrant/storage`）与 `redis:7-alpine` 两个服务，**不包含应用本身的服务定义**。注释说明“MVP 阶段无容器依赖（简化向量 + 内存限流），生产期取消下面注释即可一键拉起”，意味着部署时把 compose 中依赖服务启用即可，应用自身仍通过 `dev.sh` 或外部方式运行。
- 仓库内未发现 `Dockerfile`，容器化策略是“依赖容器化 + 应用进程托管”。

### 3.3 前端构建
- 基于 Vite 5.x + TypeScript 5.6，`frontend/package.json` 的 `build` 脚本顺序执行 `tsc` 然后 `vite build`，产物由 Vite 生成。
- CI 中使用 `npm ci` 而非 `npm install`，并以 `cache-dependency-path: frontend/package-lock.json` 缓存 npm 依赖。

### 3.4 后端构建与测试
- 依赖通过 `pip install -r requirements.txt` 安装（Python 3.11）。
- CI 的 backend job 依次执行：
  1. API 单元测试：`pytest tests/test_api.py tests/test_badcase_report.py tests/test_v2_ws_copilot.py tests/test_kb_admin.py tests/test_v2_ops.py tests/test_v2_gaps.py -q`
  2. 检索评估：`python tests/eval.py`（基于 `golden_dataset.json`）
  3. 负载冒烟测试：`python tests/load_test.py --concurrency 4 --total 5`
- 所有测试均在无真实 LLM 调用的 Mock 模式下运行。

### 3.5 触发条件
- CI 仅在 `push` 到 `main` 分支以及任意 `pull_request` 时触发。

## 4. 约定与约束

- **端口固定约定**：后端必须监听 `127.0.0.1:8000`，前端必须监听 `localhost:5173`（由 `dev.sh` 硬编码）。变更任一端口需要同步修改 `dev.sh` 中的 `PORT_BACKEND` / `PORT_FRONTEND` 及健康检查 URL。
- **本地启动命令约定**：统一入口为 `./dev.sh [start|stop|status]`，或通过 `npm start/stop/status` 间接调用。其他启动方式（如直接 uvicorn/vite）不会自动注册 PID 与日志文件，也不受 `stop` 管理。
- **依赖服务按需启用**：`docker-compose.yml` 中 Qdrant 与 Redis 默认不启用，仅在生产期取消注释后使用；MVP 阶段后端使用“简化向量 + 内存限流”实现，无需外部依赖。
- **CI 环境隔离**：后端使用 Ubuntu + Python 3.11，前端使用 Node.js 20；前端依赖缓存 key 基于 `frontend/package-lock.json`，确保缓存失效与锁文件同步。
- **前端构建契约**：`npm run build` 必须先完成 TypeScript 编译（`tsc`）再执行 `vite build`，任何 TS 类型错误都会阻断构建。
- **后端测试契约**：CI 固定运行六套测试文件和两套独立脚本（`eval.py`、`load_test.py`），新增测试应遵循现有命名规范（`tests/test_*.py`）以便 pytest 自动发现。
- **版本管理**：根 `package.json` 与 `frontend/package.json` 均声明 `version: "1.0.0"`，但仓库未观察到自动化发布流程或版本号注入机制；版本号目前为手动维护。
- **无 Makefile/Bazel/GitHub Release 流水线**：项目不使用 Makefile、Dockerfile 或自动化发布到制品库的流水线，构建产物（前端静态资源、后端源码）不经过中央制品仓库归档。