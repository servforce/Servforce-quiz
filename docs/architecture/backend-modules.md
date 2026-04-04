# 后端模块分工

## 入口与装配

### `backend/md_quiz/config.py`

- 环境变量读取与默认值装配
- `EnvironmentSettings` / `RuntimeConfigDefaults` 定义
- 路径常量、日志初始化与数据库连接串规范化

### `backend/md_quiz/app.py`

- 构建 `AppContainer`
- 创建 FastAPI 应用并挂载 `SessionMiddleware`
- 注册 `/api/system/*`、`/api/admin/*`、`/api/public/*`
- 挂载 MCP、静态资源、测验资源下载与双 SPA 入口
- 处理 `/legacy/*` 兼容跳转

### 进程入口

- `main.py`：API 进程入口
- `worker.py`：Worker 轮询 `runtime_job` 并执行任务
- `scheduler.py`：Scheduler 定时投递周期任务
- `multi_process.py`：容器内的进程托管器，统一拉起 `api / worker / scheduler`

## `backend/md_quiz/api/`

### 通用

- `deps.py`：从 FastAPI `request/app.state` 取容器对象
- `system.py`：健康检查、进程心跳、系统 bootstrap 与 MCP 摘要

### 后台

- `admin.py`：后台共用 payload、serializer、helper，以及子路由聚合入口
- `admin_core_routes.py`：后台会话、bootstrap、运行时配置、任务列表与手动投递
- `admin_quiz_routes.py`：题库列表/详情、仓库绑定/重绑、同步任务、公开邀约开关
- `admin_candidate_routes.py`：候选人 CRUD、简历上传/重解析、简历下载、管理员评价
- `admin_assignment_routes.py`：邀约创建、答题记录列表、详情/结果页、删除与二维码
- `admin_monitor_routes.py`：系统日志、系统状态、告警清理/回填

### 候选人端

- `public.py`：公开邀约、短信验证、简历上传、答题保存、提交、完成态等 HTTP 协议适配

## `backend/md_quiz/services/`

### 运行时与任务系统

- `runtime_bootstrap.py`：启动时初始化数据库、迁移旧 JSON runtime 状态、补齐旧题库数据
- `runtime_service.py`：运行时配置读取/更新、进程心跳
- `job_service.py`：任务投递、去重投递、claim、处理分发
- `runtime_jobs.py`：assignment 状态推进、超时提交、判卷任务入队、判卷后副作用与归档
- `support_deps.py`：运行时公共依赖聚合，供 services 与 API 复用

### 题库与答题

- `exam_helpers.py`：题库快照、渲染字段、资源解析、公开邀约配置
- `quiz_metadata.py`：题库摘要与展示元信息
- `assignment_service.py`：assignment token、assignment 持久化与进程内 token 级锁
- `exam_repo_sync_service.py`：Git 题库同步、绑定与重绑流程
- `exam_generation_service.py`：AI 生成测验与配图策略

### 候选人流程与判卷

- `public_flow_service.py`：公开邀约 ensure、短信验证码发送/校验、公开邀约简历上传
- `grading_service.py`：答卷评分、候选人评语、结构化分析
- `resume_service.py`：简历文本抽取与结构化解析
- `resume_ingest_service.py`：简历文件读取、解析阶段日志与 payload 装配
- `candidate_resume_admin_service.py`：后台候选人简历上传 / 重解析

### 支撑模块

- `admin_agent_service.py`：MCP 侧复用的管理员业务编排
- `aliyun_dypns.py`：阿里云短信认证服务适配
- `audit_context.py`：LLM 调用的请求内审计上下文
- `llm_client.py`：OpenAI-compatible Responses API 客户端封装
- `system_log.py` / `system_metrics.py` / `system_status_helpers.py`：系统日志、指标和状态页聚合
- `validation_helpers.py`：手机号、姓名、时间等输入校验

## `backend/md_quiz/storage/`

- `db.py`：PostgreSQL 表结构和业务读写的唯一事实来源
- `runtime_config.py`：`runtime_config` 的数据库持久化
- `job_store.py`：`runtime_job` 队列存储、claim 与状态更新
- `process_store.py`：`process_heartbeat` 持久化

## 其它目录

### `backend/md_quiz/mcp/`

- `server.py`：MCP Server、Bearer 鉴权、中间层工具注册

### `backend/md_quiz/parsers/`

- `qml.py`：QML 测验格式解析
