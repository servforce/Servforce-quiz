# 架构总览

## 运行入口

- `app.py`：兼容启动入口，直接运行时调用 `create_app()` 并监听 `PORT`。
- `web/app_factory.py`：Flask 应用工厂，负责装配模板目录、静态目录、启动初始化和路由注册。
- `web/runtime_setup.py`：启动期 bootstrap，负责准备运行目录、初始化数据库、启动自动收卷线程。
- `scripts/dev/webctl.sh` / `scripts/dev/test.sh`：本地启动与测试入口。

## 核心分层

- `core/`：环境变量加载、日志初始化、基础 settings 构建。
- `config.py`：对外暴露兼容配置常量，供旧代码以模块常量方式读取。
- `db.py`：PostgreSQL 连接池、DDL 初始化和所有核心表的读写函数。
- `services/`：业务能力与外部依赖，包括分发 token、判卷、LLM、简历解析、短信、系统指标等。
- `web/routes/`：HTTP 装配层，按 `shared / admin / public` 三大入口拆分。
- `web/support/`：路由和服务共用的辅助逻辑与兼容导出。
- `templates/` + `static/`：服务端模板页面和前端静态资源。
- `qml/`：试卷 Markdown 解析与结构化转换。

## 请求面划分

### shared

- `/`：根据管理员 session 跳转到登录页或后台首页。
- `/exams/<exam_key>/assets/<path:relpath>`：提供试卷资源文件输出。

### admin

- `/admin/login`、`/admin/logout`：后台登录与退出。
- `/admin/exams*`：试卷上传、编辑、预览、公开邀约、AI 生成与检查。
- `/admin/candidates*`：候选人列表、详情、编辑、简历上传与重解析。
- `/admin/assignments*`：考试分发、二维码、结果页和作答快照。
- `/admin/status*`、`/admin/logs*`：系统状态、资源指标、操作日志与轮询接口。

### public

- `/p/<public_token>`、`/t/<token>`：公开邀约和专属邀约入口。
- `/resume/<token>`：简历上传入口。
- `/a/<token>`、`/exam/<token>`：答题页入口。
- `/api/public/*`：验证码发送、身份验证、答案暂存、交卷、简历上传。
- `/done/<token>`：交卷完成页。

## 运行模型

- Web 请求仍是单体 Flask 进程内处理。
- 自动收卷由 `web/runtime_setup.py` 中的后台线程驱动，可通过 `ENABLE_AUTO_COLLECT` 关闭。
- 判卷、归档和部分状态推进在进程内完成，当前没有独立 worker 或消息队列。

## 当前稳定边界

- 业务真相源在 PostgreSQL，不再依赖 JSON 文件存储状态。
- 试卷解析和试题判分规则由服务层 + parser 共同定义，模板只负责展示。
- `web/runtime_support.py` 和 `config.py` 提供兼容导出，避免一次性打断旧调用路径。
