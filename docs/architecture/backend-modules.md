# 后端模块分工

### `backend/md_quiz/config.py`

- 环境变量读取
- 路径与目录定义
- 运行时默认值与单栈配置事实来源

### `backend/md_quiz/app.py`

- FastAPI 装配
- SessionMiddleware
- API 路由注册
- MCP 挂载与会话管理
- SPA 入口路由
- 静态资源与测验资源路由
- `/legacy/*` 兼容跳转

### `backend/md_quiz/api/`

- `system.py`：健康检查、进程状态、系统 bootstrap
- `admin.py`：后台会话、测验、候选人、邀约、日志、系统状态
- `public.py`：公开邀约、短信验证、简历上传、答题保存、提交、完成态

### `backend/md_quiz/services/`

- `runtime_service.py`：runtime config 与进程心跳
- `job_service.py`：job 投递、领取与处理
- `admin_agent_service.py`：MCP 侧复用的管理员业务编排
- `exam_helpers.py` / `runtime_jobs.py`：测验资源、答题状态机与归档
- `resume_service.py` / `grading_service.py`：简历解析与判卷
- `exam_repo_sync_service.py`：测验仓库同步
- `runtime_bootstrap.py`：运行时启动准备

### `backend/md_quiz/mcp/`

- `server.py`：MCP Server 定义、Bearer 鉴权、中间层工具注册

### `backend/md_quiz/storage/`

- `db.py`：PostgreSQL 表结构与业务读写事实来源
- `runtime_config.py`：运行时配置数据库存储
- `job_store.py`：任务队列数据库存储
- `process_store.py`：进程心跳数据库存储
- `fs.py`：业务存储目录准备

### 入口

- `main.py`：API
- `worker.py`：Worker
- `scheduler.py`：Scheduler

### `backend/md_quiz/parsers/`

- `qml.py`：QML 测验格式解析
