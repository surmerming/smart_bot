## 1. 使用的系统
仓库采用**多语言、多模块**的依赖管理策略，按子模块分别使用各自生态的标准工具：
- Python 后端 (`backend/`)：使用 `requirements.txt` 声明运行时与测试依赖。
- TypeScript/Vite 前端 (`frontend/`)：使用 `package.json` 配合 `package-lock.json`（npm）锁定依赖版本。
- 仓库根 (`package.json`)：仅作为脚本入口，不声明任何第三方依赖，通过 `dev.sh` 编排子进程。

未发现 Go (`go.mod`)、Rust (`Cargo.toml`)、Java (`pom.xml`/`build.gradle`)、Ruby (`Gemfile`) 等其它语言的依赖清单；也未见私有 registry 配置或 vendored 第三方源码。

## 2. 关键文件
- `backend/requirements.txt`：后端依赖清单。
- `frontend/package.json`：前端项目元数据与依赖。
- `frontend/package-lock.json`：npm 锁文件（由 `npm install` 生成，用于保证构建可重现）。
- `package.json`（根）：仅提供 `start`/`stop`/`status` 脚本，委托给 `dev.sh`。

## 3. 架构与约定
- **分层声明**：后端依赖集中在 `backend/requirements.txt`，前端依赖集中在 `frontend/package.json`，根目录不持有业务依赖，保持多子模块边界清晰。
- **Python 依赖风格**：`requirements.txt` 统一使用 `>=` 宽松下限（如 `fastapi>=0.115`、`pydantic>=2.12`），未使用 `pip freeze` 生成的精确版本或 `requirements.in` / `poetry.lock` / `Pipfile`。注释行 `# 客服机器人 Agent 后端依赖（MVP，支持 Python 3.14）` 明确标注了目标 Python 版本范围。
- **前端依赖风格**：`package.json` 中 `typescript` 与 `vite` 使用 `^` 前缀语义化版本，允许小版本升级；生产依赖为空（纯前端由 Vite 打包），所有依赖均为 `devDependencies`。
- **无 vendoring**：未发现 `vendor/`、`node_modules` 提交到仓库，亦未见 `.npmrc` / `pip.conf` 中的私有 registry 配置。
- **CI 约束**：`.github/workflows/ci.yml` 在 CI 中执行 `npm ci` 与 `pip install -r backend/requirements.txt`，确保安装过程严格匹配锁文件与清单。

## 4. 约定与约束
- **描述性观察**：后端依赖以 `>=` 下界形式声明，前端依赖以 `^` 语义版本形式声明；Python 与 Node.js 两个生态各自维护独立清单，互不交叉。
- **实际约束**：CI 流水线强制使用 `npm ci`（而非 `npm install`）和 `pip install -r backend/requirements.txt`，这意味着：
  - 前端构建必须存在且与 `package.json` 一致的 `frontend/package-lock.json`。
  - 后端安装必须严格遵循 `backend/requirements.txt` 的版本区间。
- **非约束但值得注意**：`requirements.txt` 未包含 `openai` 等外部 SDK 的精确版本上限，依赖包管理器解析最新兼容版本；该行为由 pip 默认策略决定，并非仓库显式规则。