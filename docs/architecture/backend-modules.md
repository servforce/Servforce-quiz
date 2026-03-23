# 后端模块分工

## 新后端

### `backend/md_quiz/config.py`

- 环境变量读取
- 路径与目录定义
- 运行时默认值

### `backend/md_quiz/app.py`

- FastAPI 装配
- SessionMiddleware
- API 路由注册
- 静态资源与 UI fallback
- legacy bridge 挂载

### `backend/md_quiz/api/`

- `system.py`：健康检查、进程状态、bootstrap
- `admin.py`：后台会话、runtime config、jobs
- `public.py`：候选人端 bootstrap

### `backend/md_quiz/services/`

- `runtime_service.py`：runtime config 与进程心跳
- `job_service.py`：job 投递、领取与处理

### `backend/md_quiz/storage/`

- `runtime_config.py`：运行时配置存储
- `job_store.py`：任务队列存储
- `process_store.py`：进程心跳存储
- `json_store.py`：原子 JSON 读写基类

### 入口

- `main.py`：API
- `worker.py`：Worker
- `scheduler.py`：Scheduler

## 旧后端

旧实现仍位于：

- `app.py`
- `web/`
- `services/`
- `db.py`

当前不再作为新架构推荐入口，但仍通过 `/legacy` 暂时提供兼容访问。
