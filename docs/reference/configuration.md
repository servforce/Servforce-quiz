# 配置项说明

## 环境变量

### API / 通用

- `APP_ENV`
- `APP_HOST`
- `PORT`
- `APP_SECRET_KEY`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `DATABASE_URL`
- `LOG_LEVEL`
- `MCP_ENABLED`
- `MCP_AUTH_TOKEN`
- `MCP_CORS_ALLOW_ORIGINS`

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

## 集成配置

以下变量仍由服务直接读取，用于外部集成：

- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `EXAM_REPO_SYNC_PROXY`
- 阿里云号码认证短信认证相关配置：
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

它们不属于运行时后台配置，重启前后都依赖环境变量。

补充说明：

- `EXAM_REPO_SYNC_PROXY` 只用于测验 Git 仓库同步。
- 同步服务不会再依赖全局 `HTTP_PROXY` / `HTTPS_PROXY` 环境变量污染整个进程，而是仅在执行 `git clone` 时显式传入 `git -c http.proxy=...`。
- `MCP_ENABLED=1` 时，应用会在 `/mcp` 挂载远程 MCP 服务。
- `MCP_AUTH_TOKEN` 是 MCP Bearer Token，未设置时不允许启用 MCP。
- `MCP_CORS_ALLOW_ORIGINS` 仅在浏览器型 MCP 客户端需要跨域访问时设置，使用逗号分隔。
