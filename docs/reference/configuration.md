# 配置项说明

## 配置分层

当前配置分为三层：

- 部署层：`docker-compose.yml`、`Dockerfile` 和 `.env`
- 进程环境变量：由 `config.py` 和各 service 直接读取
- 运行时配置：启动后保存在数据库 `runtime_kv.runtime_config`

默认 `docker compose` 会通过 `env_file: .env` 注入环境变量；`db` 服务直接读取 `POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_DB`，`app` 容器会把 `DATABASE_URL` 覆盖为 `postgresql://<user>:<password>@db:5432/<db>`，以便通过 Compose 服务名访问数据库。

## 部署层变量

### Compose / 数据库

- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`
- `DATABASE_URL`

### 镜像与构建参数

这些不是应用代码直接读取的业务配置，而是 `docker-compose.yml` / `Dockerfile` 会使用的部署参数：

- `MD_QUIZ_IMAGE`
- `NODE_IMAGE`
- `PYTHON_IMAGE`

## 应用环境变量

### API / 会话 / 基础运行

- `APP_ENV`
- `APP_HOST`
- `PORT`
- `APP_SECRET_KEY`
- `SECRET_KEY`
- `ASSIGNMENT_TOKEN_SECRET`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `DATABASE_URL`
- `LOG_LEVEL`

说明：

- `APP_SECRET_KEY` 用于 `SessionMiddleware`
- `SECRET_KEY` 仅作为兼容回退；当 `APP_SECRET_KEY` 未设置时才会被使用
- `ASSIGNMENT_TOKEN_SECRET` 用于生成答题 token；未设置时回退到 `APP_SECRET_KEY/SECRET_KEY`
- `DATABASE_URL` 支持 `postgresql+psycopg2://...`，启动时会被规范化为 `postgresql://...`

### Worker / Scheduler

- `WORKER_POLL_SECONDS`
- `SCHEDULER_POLL_SECONDS`
- `SCHEDULER_METRICS_INTERVAL_SECONDS`

### 运行时默认值

这些变量只定义“初始默认值”，实际运行时可再由 `/api/admin/config` 修改：

- `RUNTIME_TOKEN_DAILY_THRESHOLD`
- `RUNTIME_SMS_DAILY_THRESHOLD`
- `RUNTIME_ALLOW_PUBLIC_ASSIGNMENTS`
- `RUNTIME_MIN_SUBMIT_SECONDS`
- `RUNTIME_UI_THEME_NAME`

这些变量只影响首次启动或数据库里尚无配置时的默认值；管理员后续在后台修改后，以数据库值为准。

### MCP

- `MCP_ENABLED`
- `MCP_AUTH_TOKEN`
- `MCP_CORS_ALLOW_ORIGINS`

### LLM / OpenAI-compatible Responses API

- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_BASE_URL`
- `LLM_RESPONSE_FORMAT_JSON`
- `LLM_RETRY_MAX`
- `LLM_TIMEOUT_JSON`
- `LLM_TIMEOUT_TEXT`
- `LLM_TIMEOUT_STRUCTURED`
- `LLM_TIMEOUT_VISION`

说明：

- 当前 LLM 调用统一走 `backend/md_quiz/services/llm_client.py`
- 底层使用 OpenAI Python SDK 的 `client.responses.create(...)`
- 只兼容 `chat/completions` 的平台，不能只改 `OPENAI_BASE_URL` 直接接入

### 简历解析高级参数

- `RESUME_USE_LLM`
- `RESUME_PDF_MAX_PAGES`
- `RESUME_DETAILS_TEXT_MAX_CHARS`
- `RESUME_DETAILS_FOCUS_MAX_CHARS`
- `RESUME_EXPERIENCE_RAW_MAX_CHARS`
- `RESUME_DETAILS_PROMPT_MAX_CHARS`

这些参数由 `resume_service.py` 直接读取，用来控制简历抽取是否启用 LLM、PDF 扫描页数和详情 prompt 截断长度。

### 测验生成 / 题库同步

- `AI_EXAM_DIAGRAM_MODE`
- `EXAM_REPO_SYNC_PROXY`

说明：

- `AI_EXAM_DIAGRAM_MODE` 当前影响 AI 生成测验时的配图策略
- `EXAM_REPO_SYNC_PROXY` 只用于 Git 仓库同步，不污染整个进程的全局代理

### 阿里云短信认证

- `ALIYUN_ACCESS_KEY_ID`
- `ALIYUN_ACCESS_KEY_SECRET`
- `ALIYUN_PNVS_ENDPOINT`
- `ALIYUN_PNVS_REGION_ID`
- `ALIYUN_PNVS_SIGN_NAME`
- `ALIYUN_PNVS_TEMPLATE_CODE`
- `ALIYUN_PNVS_TEMPLATE_PARAM`
- `ALIYUN_PNVS_SCHEME_NAME`
- `ALIYUN_PNVS_COUNTRY_CODE`
- `ALIYUN_PNVS_OUT_ID`
- `ALIYUN_PNVS_VALID_TIME`
- `ALIYUN_PNVS_CASE_AUTH_POLICY`

## 运行时配置

运行时配置现在保存到数据库表 `runtime_kv` 的 `runtime_config` 键中。

环境变量只提供初始默认值；管理员在后台修改后，以数据库值为准。当前配置项包括：

- `token_daily_threshold`
- `sms_daily_threshold`
- `allow_public_assignments`
- `min_submit_seconds`
- `ui_theme_name`

## 实例级仓库绑定

测验仓库绑定信息也保存在数据库表 `runtime_kv` 中，但使用独立键 `exam_repo_binding`，不属于 `runtime_config`，也不是环境变量配置。

当前结构最小为：

- `repo_url`
- `bound_at`
- `updated_at`

说明：

- 一套 `md-quiz` 实例只绑定一个仓库
- 首次绑定后，管理端同步按钮只会针对这个已绑定仓库执行
- 更换仓库必须走显式“重新绑定”流程

## 补充说明

- 并不是所有变量都集中在 `config.py`；部分高级参数由 `llm_client.py`、`resume_service.py`、`exam_generation_service.py` 等模块直接读取
- `MCP_ENABLED=1` 时，应用会在 `/mcp` 挂载远程 MCP 服务
- `MCP_AUTH_TOKEN` 是 MCP Bearer Token，未设置时不允许启用 MCP
- `MCP_CORS_ALLOW_ORIGINS` 仅在浏览器型 MCP 客户端需要跨域访问时设置，使用逗号分隔
