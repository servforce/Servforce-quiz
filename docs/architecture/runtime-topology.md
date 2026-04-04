# 运行拓扑

## 进程图

```text
browser
  -> FastAPI API
      -> /api/system/*
      -> /api/admin/*
      -> /api/public/*
      -> /mcp
      -> /static/*
      -> /quizzes/* /exams/* assets
      -> /legacy/*  (307 跳转到真实路径)
      -> /admin*    (后台 Alpine SPA)
      -> /p/* /t/* /resume/* /quiz/* /exam/* /done/* /a/* (候选人 Alpine SPA)

scheduler
  -> enqueue jobs

worker
  -> claim runtime_job
  -> process jobs
```

## 默认容器拓扑

```text
docker-compose
  -> db (PostgreSQL)
  -> app
       -> python -m backend.md_quiz.multi_process
            -> api
            -> worker
            -> scheduler
```

- 默认 `docker compose` 只起两个容器：`db` 与 `app`
- `app` 容器内由 `backend/md_quiz/multi_process.py` 统一托管 `api / worker / scheduler`
- `.env` 通过 Compose `env_file` 注入；仅 `DATABASE_URL` 在容器内固定覆盖为 `db:5432`
- 前端静态资源在镜像构建阶段完成 `admin.css / public.css` 编译与 Alpine / MathJax 本地资源同步

## 当前实现

### API

- 入口：`backend/md_quiz/main.py`
- 装配：`backend/md_quiz/app.py`
- 会话：`SessionMiddleware`，后台登录态保存在 `api_session`
- 静态资源：`/static/*`
- 内部健康检查：`/healthz`
- 默认后台入口：`/admin`
- 根路径：按登录态 307 跳转到 `/admin` 或 `/admin/login`
- `/legacy/*`：兼容跳转到当前真实路径
- 公开测验资源：`/quizzes/{quiz_key}/assets/*`、`/quizzes/versions/{version_id}/assets/*`
- 候选人端与后台端都走 SPA 壳 + REST API，不再由后端渲染业务页面

### Worker

- 入口：`backend/md_quiz/worker.py`
- 当前职责：轮询 `runtime_job`、claim 任务、执行处理器，并写回任务状态
- 当前已接入的真实任务包括：
  - `git_sync_exams`
  - `resume_parse`
  - `grade_attempt`
  - `sync_metrics`
- 判卷已统一走 `grade_attempt`，不再在 API 进程内起后台线程

### Scheduler

- 入口：`backend/md_quiz/scheduler.py`
- 当前职责：定时投递 `sync_metrics`
- 当前实现仍是简单轮询循环，不引入额外调度框架

## 当前任务模型

`runtime_job` 已经是后台任务的单一事实源：

- API / Scheduler 负责投递任务
- Worker 通过原子 `claim_next` 把任务从 `pending` 领取到 `running`
- `claim_next` 会先处理 `pending`，然后回收 lease 过期的 `running`
- `grade_attempt` 使用 `dedupe_key=grade_attempt:<token>`，防止同一答卷并发重复判卷
- lease 时长当前是静态策略：
  - `grade_attempt`：1800 秒
  - `resume_parse` / `git_sync_exams`：600 秒
  - 其它任务：300 秒

## 当前存储边界

运行时状态已经统一入库：

- `runtime_kv`
- `runtime_daily_metric`
- `runtime_job`
- `process_heartbeat`

根目录 `storage/` 不再是当前运行时依赖；历史 `storage/runtime/*.json` 仅在兼容旧部署数据时作为一次性迁移输入源读取一次。
