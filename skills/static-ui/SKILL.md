# Static UI 维护/扩展 Skill（static/）

你是一个资深前端/全栈工程师，需要在本项目中维护/扩展“静态前端 UI”（位于项目根目录 `static/`）。要求可私有化部署（禁止外部 CDN），运行时不依赖 Node；但允许在开发/构建阶段使用 Node（安装依赖与编译 Tailwind）。

## 1）不变量（Hard rules）

### 目标
- UI 技术栈：TailwindCSS v4 + Alpine.js + Material Symbols（都必须从本地静态资源加载，不引用任何外部 CDN）
- 后端：静态资源由 Flask 从 `static/` 目录直接提供（本提示词默认不改后端代码）
- 访问路径口径（以当前项目实现为准）：
  - 入口：`/` -> `static/index.html`
  - 静态资源：`/assets/*`、`/pages/*`、`/node_modules/*` -> `static/` 下同名目录
  - SPA：`/dashboard`、`/tasks`、`/symbols/...` 等路由会 fallback 到 `index.html`
- 交互框架：提供统一的“应用壳（App Shell）”布局，包含顶部状态栏 + 左侧菜单 + 主体内容区
  - 顶部状态栏：展示当前页面标题、全局状态（例如：同步状态/连接状态）、右侧操作区（例如：用户/设置入口）
  - 左侧菜单：固定宽度，可滚动；至少包含 3 个一级菜单项；支持高亮当前项
  - 主体内容区：通过左侧菜单切换路由（无需刷新页面），并 `fetch('pages/<route>.html')` 动态加载页面片段；注入 DOM 后调用 `Alpine.initTree(...)` 激活新页面
- 工具链尽量轻：不使用 Vite/webpack 等打包器；只在 `static/` 下用 Node + PostCSS 编译 Tailwind 输入样式
- 依赖管理：以 `static/package.json`/`static/package-lock.json` 为唯一事实来源；新增依赖必须同时更新 lockfile（用 `npm install`），不要手写改 lockfile

### 依赖版本（以当前项目 `static/package.json` 为准）
- Tailwind 构建链（固定版本）
  - tailwindcss：4.1.18
  - @tailwindcss/postcss：4.1.18
  - postcss：8.5.6
  - autoprefixer：10.4.23
- 前端运行时依赖（本地加载）
  - alpinejs：3.15.3
  - codemirror：^6.0.2
  - lightweight-charts：^5.1.0
  - plotly.js：^3.3.1
- 图标与字体（本地资源，不走 NPM）
  - Material Symbols（Outlined/Rounded/Sharp）：`assets/css/material-symbols.css` + `assets/fonts/material-symbols-*.woff2`

### 输出形式
- 只修改/新增必要文件；不要引入新框架或打包器
- 输出时必须标明文件路径；并仅给出你修改/新增文件的完整内容

---

## 2）工作流（Workflow）

### 项目前端目录结构（真实结构 + 职责说明）
项目根目录下的 `static/` 即前端根目录：

static/
  package.json（Node 依赖与脚本入口：CSS 构建、开发静态服务器、Jest）
  package-lock.json（锁定依赖解析结果；用于可复现安装）
  tailwind.config.js（Tailwind content 扫描范围与主题扩展）
  postcss.config.js（PostCSS 插件：@tailwindcss/postcss + autoprefixer）
  scripts/
    build-css.cjs（编译 Tailwind：assets/css/style.css -> assets/css/style.compiled.css；支持 --watch）
    dev-server.cjs（本地 SPA 静态服务器：支持 History fallback；用于纯前端预览）
  assets/
    css/
      style.css（Tailwind 输入文件：@import "tailwindcss" + 少量 base 层修正）
      style.compiled.css（构建产物：index.html 默认引用该文件）
      material-symbols.css（Material Symbols 本地字体 @font-face 配置；woff2 位于 assets/fonts/）
    js/
      init-alpine.js（统一注册 Alpine 组件/初始化）
      alpine.min.js（本地 Alpine 单文件副本；如改为从 /assets/js 引入可使用）
      utils/
        kanban.js（通用工具：querystring/路由等）
        __tests__/...（Jest 前端单测）
      components/
        frame.js（App Shell：菜单/路由/动态加载 pages 片段）
        dashboardPage.js / tasksPage.js / ...（各页面的 Alpine 组件逻辑）
      vendor/
        qlibExprEditor.js（CodeMirror 相关：表达式编辑器等）
    fonts/（本地图标字体与字体文件）
    img/（图片资源：logo 等）
    data/（前端演示/本地数据：如 sample-kline.json）
  pages/
    dashboard.html（页面片段：被 frame.js 动态插入主内容区）
    tasks.html / symbols.html / ...（其余页面片段，必须是“片段”而非完整 HTML 文档）
  index.html（入口页：App Shell 布局 + CSS/JS 引用 + importmap）
  readme.md（前端使用/开发说明）
  node_modules/（npm install 产物；不会提交 git，但会被后端作为静态文件提供给浏览器）
  .gitignore（忽略 node_modules）

### 构建产物
- `static/assets/css/style.compiled.css`：由 `npm run build:css` 或 `npm run watch:css` 生成/更新

### package.json 脚本（以 static/package.json 为准）
- `npm run build:css`：执行 `node scripts/build-css.cjs`（编译一次）
- `npm run watch:css`：执行 `node scripts/build-css.cjs --watch`（监听并增量编译）
- `npm run dev`：执行 `node scripts/dev-server.cjs`（History 模式预览用）
- `npm test`：执行 Jest（用于 `assets/js/**/__tests__`）

### Tailwind v4 注意事项
- 使用 `@tailwindcss/postcss` 作为 PostCSS 插件（见 `static/postcss.config.js`）
- Tailwind v4 有“自动 content 扫描/检测”的能力：当你通过 PostCSS 插件链路构建时，它会以输入 CSS 所在工程为基准做默认扫描；但本项目仍**显式维护** `static/tailwind.config.js` 的 `content`，并且我会额外确保它覆盖到那些“动态拼接 class”的 JS 文件，避免样式被 tree-shake 掉。
- `static/tailwind.config.js` 当前 content 覆盖：
  - `./*.html`（入口）
  - `./pages/**/*.html`（页面片段）
  若你在 JS 中拼接 Tailwind class（字符串模板），需要把对应 JS 路径加入 content 扫描，否则样式可能不会被生成。

### 页面开发约定
- `pages/*.html` 必须是片段：不要包含 `<!doctype> / <html> / <head> / <body> / <script>`
- 如页面需要交互：顶层容器使用 `x-data="xxxPage"` 并在 `assets/js/init-alpine.js` 注册对应组件
- 新增/改动路由与菜单：更新 `assets/js/components/frame.js` 的 `menuItems` 与路由映射逻辑
- 资源路径：`pages/*.html` 是被 `static/index.html` 动态加载并注入的片段，因此片段内的资源引用（图片/链接等）必须**以 `index.html` 的位置为基准**写相对路径（例如 `assets/img/...`、`node_modules/...`），不要写成相对于 `pages/` 目录的 `../assets/...`。

### 页面构建指引
- 用途：将 `static/index.html` 作为“Layout Cookbook/风格对齐页”，用于快速复制页面骨架与响应式写法；不承担复杂业务逻辑
- 总体原则（与现有界面一致）：
  - 无外边距：页面主体默认贴边（主内容区不要默认 `p-*` / `mx-auto` / `max-w-*`），用“全高面板”贴边承载
  - 固定头 + 滚动体：工具条/筛选区 `shrink-0`，内容区 `flex-1 min-h-0 overflow-auto`
  - 用边框/分割线组织层级：面板用 `border` + `divide-y`；列表用 `divide-y`；尽量少用大阴影/大圆角做分隔
  - 响应式优先：工具条 `flex-wrap`；按钮“图标常显、文案按断点隐藏（`hidden sm:inline`）”；输入控件 `max-w-full`
- 常用页面布局建议（基于项目实际代码风格）：
  1) 工具条 + 可滚动列表（如 `tasks` / `symbols` / `signals` / `alerts` 等列表页）
     - 面板：`border border-slate-800 bg-slate-900/40 overflow-hidden h-full flex flex-col min-h-0 divide-y divide-slate-800`
     - 工具条：`px-4 py-3 flex flex-wrap items-center justify-between gap-3`
     - 列表：`flex-1 min-h-0 overflow-auto divide-y divide-slate-800`；行：`p-4 hover:bg-slate-900/50`；行内：`flex-col sm:flex-row` 自适应
  2) 筛选条 + 自适应网格（网格页通用骨架）
     - 工具条放筛选控件（tag select / select / datetime / query），用 `flex flex-wrap gap-2`
     - 内容区：`p-4 grid grid-cols-1 min-[640px]:grid-cols-2 min-[1024px]:grid-cols-3 min-[1536px]:grid-cols-4 gap-4`
  3) 仪表盘统计块（如 `dashboard`）
     - 内容区：`p-4 space-y-4`；统计 tile：`rounded-md border border-slate-800 bg-slate-900/40 p-4`
     - 状态/服务：用 pill（`rounded-full border px-2 py-0.5 text-[11px]`）+ `text-xs text-slate-400 truncate` 错误提示
  4) 详情页（如 `symbol-detail` / `signal-detail`）
     - 顶部信息条固定高度（如 `h-20`），其余区域 `flex-1 min-h-0` 并独立滚动（避免 body 整页滚动）
     - 需要覆盖层（下拉/编辑/选择器）时：`absolute inset-0` + 半透明遮罩；覆盖层内容可用 `max-w-*` 居中并加内边距（覆盖层允许有边距）
  5) 小图表/趋势条（任务/概览类常见）
     - 图表容器固定高度（如 `h-32`），上方预留图例/筛选（避免图表挤占主列表空间）
     - chart 必须随容器 resize，并保持深色配色（背景/网格/文字弱化）
- Vendor 组件接入建议（必须本地加载，不可 CDN；与 `static/index.html` 的现有引用方式保持一致）：
  - CodeMirror 6：继续使用 `static/index.html` 的 `importmap`（将模块映射到 `/node_modules/...`）+ `<script type="module" src="assets/js/vendor/qlibExprEditor.js"></script>`；布局上让编辑器容器 `flex-1 min-h-0`，并确保 `.cm-editor` 可“吃满剩余高度”（优先配合 `h-full`/`min-h-0`）
  - lightweight-charts：从 `node_modules/lightweight-charts/dist/lightweight-charts.standalone.production.js` 加载（当前项目已在 `static/index.html` 引用）
  - Plotly：从 `node_modules/plotly.js/dist/plotly-basic.min.js` 加载（当前项目已在 `static/index.html` 引用）
- 页面资源引用必须为本地资源（不可 CDN），并与目录结构一致（不要写成 `/static/...` 这种不存在的路径）：
  ```html
  <!-- 样式（由 npm 构建产物 + 本地字体） -->
  <link href="assets/css/material-symbols.css" rel="stylesheet" />
  <link href="assets/css/style.compiled.css" rel="stylesheet" />

  <!-- 运行时依赖（全部本地加载，不走外部 CDN） -->
  <script src="node_modules/plotly.js/dist/plotly-basic.min.js"></script>
  <script src="node_modules/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
  <script defer src="node_modules/alpinejs/dist/cdn.min.js"></script>

---

## 3）UI 规范（Design system / Style）

### UI 风格与规范（必须遵循）

* 定位：深色优先、现代克制、偏“管理后台 / SaaS 控制台”风格；信息密度中等，强调可读性与状态表达
* 配色方案：

  * `docs/ui/theme.md` 若存在，则它是当前项目的配色重载事实来源；与本节默认值冲突时，以 `docs/ui/theme.md` 为准
  * 本节只提供默认定义，保证该 skill 在脱离当前项目文档时仍可独立使用
  * 后续改色时，项目内优先修改 `docs/ui/theme.md`；不要把项目主题差异直接堆回本节默认值
  * 其它地方如出现颜色 class，应优先引用“Base / Primary / Danger / Warning / Info / Overlay”这些语义槽位，而不是分散定义

  * Base（中性基底 / Slate）：

    * 页面背景：bg-slate-950
    * 面板背景：bg-slate-900/40（列表/面板主体），bg-slate-950/20（更弱的底）
    * 顶栏背景：bg-slate-950/70（可 backdrop-blur）
    * 边框/分割线：border-slate-800、divide-slate-800
    * Hover：hover:bg-slate-900/50
    * 文字：主文 text-slate-200，次级 text-slate-300，弱化 text-slate-400 / text-slate-500，占位 placeholder-slate-500
  * Primary（Emerald，主交互）：

    * 实心按钮：bg-emerald-500 text-slate-950 hover:bg-emerald-400
    * 选中/强调（弱底）：bg-emerald-500/10 text-emerald-200 border-emerald-500/30
    * Focus ring：focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/30
    * 状态点：bg-emerald-400
  * Danger（Rose，危险/错误）：

    * 弱底按钮/块：bg-rose-500/20 text-rose-200 hover:bg-rose-500/25
    * 错误文案：text-rose-300
    * 状态点：bg-rose-400
  * Warning（Amber，警告）：

    * 弱底：bg-amber-500/15 text-amber-200 border-amber-500/25
    * 文案：text-amber-300
  * Info（Sky，信息）：

    * 弱底：bg-sky-500/15 text-sky-200 border-sky-500/25
    * 文案：text-sky-300
  * Overlay（遮罩，默认值）：

    * 弹窗遮罩：bg-black/60
* 主题：

  * 默认深色主题，不强制实现 light/dark 切换
  * 如需主题切换：Tailwind darkMode: 'class' + Alpine theme（localStorage 持久化）
* 字体与排版：

  * 正文使用系统字体栈；图标字体例外：Material Symbols（必须自托管）
  * 页面标题/区块标题层级清晰：标题 text-md/lg，正文 text-sm，辅助信息 text-xs/text-[11px]
  * 行高与间距统一：正文 leading-6；常用内边距以 px-4 py-3（工具条）与 p-4（内容区）为主
  * 元信息排版（必须区分样式）：ID/时间/日期/时长/数值等统一使用更“技术化”的排版

    * ID：font-mono text-[11px] text-slate-500（可 select-all/break-all；避免与正文混淆）
    * 时间/日期：font-mono tabular-nums text-[11px] text-slate-400 whitespace-nowrap（保证数字等宽对齐、列表整齐）
    * 数值统计：在容器上加 tabular-nums（如列表列/指标卡），避免数字跳动
* 布局与层级（无边距 / 面板化）：

  * App Shell：顶部栏固定高度（h-14），侧边栏固定宽度（展开 w-48，折叠 w-14）；顶部栏 sticky top-0，主内容区独立滚动
  * 主内容区默认“无外边距/无卡片外框”：不要默认使用外层 rounded-*/shadow/mx-auto/max-w-*；页面主体用一个“全高面板”贴边承载，通过 border/divide-y/半透明背景区分结构
  * 全高面板推荐结构（需贯穿各视图一致）：

    * 容器：border border-slate-800 bg-slate-900/40 overflow-hidden h-full flex flex-col min-h-0 divide-y divide-slate-800
    * 顶部工具条：shrink-0 px-4 py-3（可 flex flex-wrap）
    * 内容区：flex-1 min-h-0 overflow-auto raelyn-scrollbar（列表用 divide-y；网格用 p-4 + grid）
  * “小卡片/Tile”仅用于面板内部的局部信息块（如统计卡、视频卡、弹窗），圆角更小（优先 rounded-md，必要时 rounded-lg），不作为页面默认外框
* 组件风格（保持一致即可）：

  * 按钮：Primary（bg-emerald-500 text-slate-950）、Secondary（border border-slate-700 bg-slate-950/20）、Danger（bg-rose-500/20 text-rose-200）三类；hover/disabled/焦点 ring 一致（focus:ring-emerald-500/30）
  * 表单：input/select 默认使用 rounded-md border border-slate-700 bg-slate-950/30；focus 使用 focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/30；错误态用 rose 文案与边框
  * 多行文本输入：textarea、提示词编辑区、cookies 编辑区这类“大段文本编辑面板”不要直接沿用最深底色；优先使用更浅一层的 slate 背景，并把正文降到更柔和的 slate-300 左右，而不是高对比纯白，placeholder 保持 slate-400/500，caret 与 focus 反馈可以继续更亮，以减少长时间阅读/编辑的视觉疲劳
  * 贴边编辑器（Edge-to-edge editor）：适用于提示词、Markdown、JSON、cookies、长文本说明等“大段文本编辑”区域；外层面板负责边框、圆角、分割线，编辑器内容区默认与面板贴边，不再额外包一层 `p-*`
  * 贴边编辑器结构：头部/说明/错误提示作为独立分区放在编辑器上方，使用 `border-b` 分隔；编辑器本体优先 `block w-full rounded-none border-0`，仅保留文本阅读所需的 `px-4 py-3`
  * 贴边编辑器禁忌：不要给编辑器外再套一层 `p-4`；不要同时保留“外层面板边框 + textarea 自身边框 + rounded-lg”；视觉目标是“面板即编辑器表面”，不是“面板里再嵌一张卡片”
  * 贴边编辑器优先级：当“无边距面板化”与“通用表单控件样式”冲突时，普通 input/select 保持 `rounded-md border`，大段文本编辑器优先使用贴边编辑器模式，不套用通用 textarea 卡片样式
  * 贴边编辑器推荐配方：外层 `rounded-lg border border-slate-800 bg-slate-950/20 overflow-hidden`；头部 `px-4 py-3 border-b border-slate-800`；错误行 `px-4 py-3 text-xs text-rose-200 border-b border-rose-900/60`；textarea `block w-full h-64 rounded-none border-0 px-4 py-3 text-xs font-mono leading-5 resize-none focus:outline-none`
  * 多选：优先使用 tag select 控件（“已选标签 + 搜索输入 + 下拉选项”），而不是原生 multi-select；需支持 Enter 添加第一个匹配项、Backspace 删除最后一个 tag、Esc 关闭下拉；窄屏可换行（flex-wrap）且不溢出（max-w-full）
  * 列表/表格：优先用 divide-y divide-slate-800；行 p-4 hover:bg-slate-900/50；空状态/加载态需要占位（如 暂无数据、加载中…）
  * 徽标/状态：pill badge 统一 rounded-full border bg-slate-950/30 text-[11px]；状态点用小圆点 + 文本
  * 弹窗：遮罩 bg-black/60；内容容器 rounded-lg border border-slate-800 bg-slate-900 shadow-lg p-4
* 交互细节：

  * 过渡动画克制：只在菜单切换/弹层/提示条使用 transition/x-transition，时长 150–250ms
  * 响应式：小屏侧边栏可隐藏/展开（顶部栏 hamburger，md:hidden）；工具条/列表行用 flex-wrap 适配窄屏；按钮文案用 hidden sm:inline
* 可视化区域规范（与本提示词要求的 3 个组件一致）：

  * CodeMirror：放入面板内容区；使用等宽字体；优先自适应高度并“吃满剩余可视区域”（与全高面板的滚动策略一致），而不是固定高度；提供“复制/保存/格式化”示例操作区；深色主题
  * lightweight-charts：放入面板工具条下方或内容区顶部；容器固定高度（如 h-32/h-48）；随容器 resize；深色配色与网格弱化
  * Plotly：放入面板内容区；容器固定高度（如 320px）；精简/关闭 modebar（保持界面干净）
* 图标策略：

  * 统一使用 Material Symbols（同一套风格/笔画/尺寸），禁止运行时从 CDN 加载
  * 推荐用自托管字体 + ligature 方式（如 <span class="material-symbols-rounded">settings</span>），并用 Tailwind 控制大小与对齐（如 text-[20px] leading-none）

### Material Symbols 使用约定

* 样式引入（入口页 `static/index.html`）：

  ```html
  <!-- Material Symbols：本地字体图标（禁止外部 CDN） -->
  <link href="assets/css/material-symbols.css" rel="stylesheet" />
  ```
* 图标使用方式：

  ```html
  <!-- 空心 Outlined 风格 -->
  <span class="material-symbols-outlined">menu</span>
  <!-- 实心 Rounded 风格 -->
  <span class="material-symbols-rounded">settings</span>
  ```

---

## 4）验收清单（Acceptance / DoD）

### 资源与私有化

* 资源引用必须为本地资源（不可 CDN），并与目录结构一致（不要写成 `/static/...` 这种不存在的路径）
* Material Symbols 必须自托管（`assets/css/material-symbols.css` + `assets/fonts/*.woff2`）
* 若项目存在 `docs/ui/theme.md`，验收时配色应以该文档为准；本 skill 中的配色表仅作为默认值

### 路由与 App Shell

* App Shell 必须包含：顶部状态栏 + 左侧菜单 + 主体内容区
* 左侧菜单切换路由无需刷新页面
* 主体内容区必须通过 `fetch('pages/<route>.html')` 动态加载页面片段
* 页面片段注入 DOM 后必须调用 `Alpine.initTree(...)` 激活新页面
* `assets/js/components/frame.js` 的路由切换逻辑里：在 `innerHTML` 赋值后应**立即**对注入容器执行 `Alpine.initTree(container)`，确保新 DOM 被 Alpine 识别（不要延后到下一次交互才初始化）。
* 左侧菜单至少包含 3 个一级菜单项，并支持高亮当前项

### 页面片段规范

* `pages/*.html` 必须是片段：不要包含 `<!doctype> / <html> / <head> / <body> / <script>`
* 如页面需要交互：顶层容器使用 `x-data="xxxPage"` 并在 `assets/js/init-alpine.js` 注册对应组件
* 新增/改动路由与菜单：更新 `assets/js/components/frame.js` 的 `menuItems` 与路由映射逻辑
* 资源引用路径必须相对 `static/index.html`：片段里用 `assets/...`、`node_modules/...` 等路径；不要写 `../assets/...`（因为浏览器解析相对路径时基于当前 document，即 `index.html`）。

### Tailwind 构建与 content 扫描

* 使用 `@tailwindcss/postcss` 作为 PostCSS 插件（见 `static/postcss.config.js`）
* Tailwind v4 默认具备自动扫描能力，但本项目以 `static/tailwind.config.js` 的 `content` 为准；若存在动态 class（字符串模板/拼接），必须把对应 JS 文件路径补进 `content`，避免样式缺失。
* `static/tailwind.config.js` 当前 content 覆盖：

  * `./*.html`（入口）
  * `./pages/**/*.html`（页面片段）
    若在 JS 中拼接 Tailwind class（字符串模板），需要把对应 JS 路径加入 content 扫描，否则样式可能不会被生成。
* `static/assets/css/style.compiled.css` 由 `npm run build:css` 或 `npm run watch:css` 生成/更新，并确保入口页引用正确

### 工具链与依赖管理

* 不使用 Vite/webpack 等打包器；只在 `static/` 下用 Node + PostCSS 编译 Tailwind 输入样式
* 以 `static/package.json`/`static/package-lock.json` 为唯一事实来源；新增依赖必须同时更新 lockfile（用 `npm install`），不要手写改 lockfile

### 输出要求

* 只修改/新增必要文件；不要引入新框架或打包器
* 输出时必须标明文件路径；并仅给出你修改/新增文件的完整内容
