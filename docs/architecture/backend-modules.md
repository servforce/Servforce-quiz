# 后端模块分工

## 入口与配置

- `app.py`：兼容入口，适合本地直接运行。
- `web/app_factory.py`：唯一推荐的 Flask 装配入口。
- `core/settings.py`：读取 `.env`，标准化 `DATABASE_URL`，构建 `Settings`。
- `config.py`：把 settings 扁平暴露成常量，兼容旧模块导入方式。

## 数据层

- `db.py`：连接池、事务上下文、DDL 初始化、核心读写函数。
- 当前 schema 与迁移逻辑直接写在 `init_db()`，没有额外 migration 框架。
- 所有业务表、索引和 enum 的事实定义以 `db.py` 为准。

## 业务服务层

- `services/assignment_service.py`：分发 token、邀请记录、最短交卷时长计算、并发锁。
- `services/grading_service.py`：客观题判分、简答题 LLM 判分、总分归一化。
- `services/exam_generation_service.py`：AI 生成试卷草稿和图示内容。
- `services/resume_service.py`：简历文本提取、图片/OCR 路径、LLM 结构化解析。
- `services/llm_client.py`：统一 OpenAI-compatible Responses API 调用、重试、超时和 token 用量记录。
- `services/aliyun_sms.py` / `services/aliyun_dypns.py`：短信验证码与本机号码认证能力。
- `services/system_log.py` / `services/system_metrics.py`：日志落库、每日指标、阈值告警。

## Web 层

- `web/routes/shared.py`：站点根入口、Markdown 过滤器、试卷资源分发。
- `web/routes/admin_*.py`：后台分域路由，按壳层、试卷、候选人、分发拆分。
- `web/routes/public_*.py`：公开入口、身份验证、简历上传、答题接口。
- `web/routes/admin.py` / `web/routes/public.py`：聚合注册器。

## 支撑模块

- `web/support/`：为路由层提供共享校验、依赖、运行期作业和系统状态工具。
- `web/runtime_support.py`：从 `web.support` 做兼容聚合导出。
- `qml/parser.py`：把 QML Markdown 转成结构化试卷对象。

## 前端载体

- `templates/`：Jinja2 模板，覆盖管理端和候选人端页面。
- `static/`：公共样式、页面脚本、图片和 vendor 资源。

## 测试

- `tests/`：以 pytest 为主，覆盖 Flask 启动、解析、判分、简历处理、数据访问和运行契约。

## 仓库布局概览

```text
md-quiz/
  AGENTS.md
  README.md
  app.py
  config.py
  db.py
  core/
  qml/
  services/
  web/
  templates/
  static/
  tests/
  scripts/dev/
  docs/
  skills/
  examples/
```

- `docs/` 负责长期维护的项目文档。
- `skills/` 负责项目内专项执行方法。
- 运行期目录默认由 `STORAGE_DIR` 指向项目根下的 `storage/`，通常不纳入版本库。
