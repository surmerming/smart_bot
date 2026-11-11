## 1. 采用的样式系统

- **无组件库、无 CSS-in-JS**：`frontend/package.json` 仅声明 `vite` 与 `typescript`，没有 Tailwind、Bootstrap、Ant Design 等第三方 UI 依赖。
- **单一全局样式文件**：所有视觉样式集中在 `frontend/src/styles.css`（约 170 行），由 Vite 直接引入构建。`src/components/` 目录为空，页面结构通过 HTML 模板与 TS 脚本动态注入，样式不随组件拆分。
- **CSS 变量（`:root`）作为设计令牌**：颜色、圆角等视觉常量统一在 `:root` 中声明，作为全仓共享的设计令牌。

## 2. 关键文件

- `frontend/src/styles.css` — 唯一的全局样式入口，包含设计令牌、全局 reset、按钮、导航、Hero、Features、FAQ、Footer 等全部站点样式。
- `frontend/index.html` / `frontend/agent.html` / `frontend/dashboard.html` / `frontend/kb.html` — 页面骨架，引用 `<script type="module" src="src/main.ts">` 或对应模块；样式通过 `<link rel="stylesheet" href="src/styles.css">` 加载。
- `frontend/vite.config.ts` — Vite 构建配置（未展示内容，但结合 package.json 可知使用 Vite 5 进行 TS→JS 转译与资源打包）。

## 3. 架构与约定

### 设计令牌（Design Tokens）

在 `styles.css` 的 `:root` 中集中定义：

| 令牌 | 值 | 用途 |
|---|---|---|
| `--blue` | `#0066cc` | 主色 |
| `--blue-dark` | `#0055aa` | 主色 hover |
| `--dark` | `#17181a` | 深色区块背景 |
| `--card-dark` | `#222428` | 卡片深色背景 |
| `--light` | `#f5f5f7` | 浅色区块背景 |
| `--text` | `#111214` | 正文文字 |
| `--muted` | `#6b7280` | 次要文字 |
| `--green` | `#22c55e` | 成功/状态色 |
| `--border` | `#ececef` | 边框色 |
| `--radius` | `14px` | 统一圆角 |

注释明确标注配色来源：“设计稿配色：主蓝 #0066CC / 深色 #17181A / 浅灰 #F5F5F7”。

### 布局策略

- **容器宽度**：`.container { max-width: 1120px; margin: 0 auto; padding: 0 24px; }` 是全站统一的页面最大宽度与内边距规范。
- **栅格布局**：大量使用 CSS Grid（如 `.hero-inner { grid-template-columns: 1.15fr 1fr; }`、`.pains { grid-template-columns: repeat(3, 1fr); }`、`.steps { grid-template-columns: repeat(4, 1fr); }`、`.footer-grid { grid-template-columns: 2fr 1fr 1fr 1fr; }`），而非 Flexbox 主导的大块布局。
- **响应式断点**：仅有一个 `@media (max-width: 960px)` 断点，将 Hero 改为单列、Feature 改为单列、Pains 改为单列、Steps 改为两列、Footer 改为两列、隐藏 `.nav-links`。

### 组件级样式约定

- **按钮族**：以 `.btn` 为基类，派生 `.btn-primary`、`.btn-sm`、`.btn-ghost`、`.btn-outline-light`，通过组合类名复用基础样式。
- **深色/浅色区块**：`.problem`、`.cta` 使用 `--dark` 背景；`.features`、`.faq`、`.footer` 使用 `--white` / `--light` 背景，形成固定的“暗-亮-暗”段落节奏。
- **卡片风格**：`.pain-card`、`.step`、`.demo-card`、`.prompt-card` 统一使用 `border-radius: var(--radius)` 与边框/阴影，保持一致的卡片语言。
- **交互反馈**：按钮 hover 使用 `transform: translateY(-1px)` + 背景色变化；FAQ summary 展开时箭头旋转 45°（`::after { transform: rotate(45deg) }`）。

### 字体与排版

```css
font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
```

优先使用系统字体栈，并显式回退到苹方、黑体、微软雅黑以覆盖中文环境。

## 4. 约定与约束

- **样式只有一份**：全仓不存在 Sass/Less、CSS Modules、Styled Components 或其他样式预处理工具，所有样式均写在 `styles.css` 中，按区域用注释分隔（`/* ---------- 导航 ---------- */` 等）。
- **禁止硬编码颜色**：除极个别场景（如 demo 消息气泡的临时色）外，颜色应通过 `var(--*)` 引用设计令牌，而非直接使用十六进制。
- **响应式仅靠一个断点**：目前仓库只维护 `960px` 一个断点，新增响应式行为应沿用此模式，而非引入新的媒体查询层级。
- **命名采用 BEM 风格的扁平类名**：如 `.feature-row`、`.feature-copy`、`.footer-col-title`，不使用深层嵌套选择器，也不使用 CSS Modules 生成的哈希类名。
- **Vite 构建流程要求 TypeScript 先行编译**：`package.json` 的 build 脚本为 `tsc && vite build`，意味着 TS 文件需先经 tsc 转译为 JS，再由 Vite 处理静态资源；样式文件则不经 TS 编译器，直接由 Vite 原样输出。

该样式体系轻量、可预期，适合当前单页官网 + 管理后台的规模；若未来拆分为多页面应用或引入组件化框架，设计令牌（`:root` 变量）可作为迁移时的最小保留资产。