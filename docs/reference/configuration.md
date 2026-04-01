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

### Worker / Scheduler

- `WORKER_POLL_SECONDS`
- `SCHEDULER_POLL_SECONDS`
- `SCHEDULER_METRICS_INTERVAL_SECONDS`

### 运行时默认值

这些变量只定义“初始默认值”，实际运行时可再由 `/api/admin/config` 修改：

- `RUNTIME_SMS_ENABLED`
- `RUNTIME_TOKEN_DAILY_THRESHOLD`
- `RUNTIME_SMS_DAILY_THRESHOLD`
- `RUNTIME_ALLOW_PUBLIC_ASSIGNMENTS`
- `RUNTIME_MIN_SUBMIT_SECONDS`
- `RUNTIME_UI_THEME_NAME`

## 运行时配置

运行时配置现在保存到数据库表 `runtime_kv` 的 `runtime_config` 键中。

环境变量只提供初始默认值；管理员在后台修改后，以数据库值为准。当前配置项包括：

- `sms_enabled`
- `token_daily_threshold`
- `sms_daily_threshold`
- `allow_public_assignments`
- `min_submit_seconds`
- `ui_theme_name`

## 实例级仓库绑定

试卷仓库绑定信息也保存在数据库表 `runtime_kv` 中，但使用独立键 `exam_repo_binding`，不属于 `runtime_config`，也不是环境变量配置。

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
- 阿里云短信相关配置

它们不属于运行时后台配置，重启前后都依赖环境变量。
