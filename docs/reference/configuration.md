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
- `STORAGE_DIR`
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

当前保存到 `storage/runtime/runtime-config.json`：

- `sms_enabled`
- `token_daily_threshold`
- `sms_daily_threshold`
- `allow_public_assignments`
- `min_submit_seconds`
- `ui_theme_name`

## 旧系统配置

旧 Flask 单体仍会继续读取原有变量，例如：

- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- 阿里云短信相关配置

这些变量目前仍保留，以支撑当前挂载在根路径下的旧后台与候选人端能力。
