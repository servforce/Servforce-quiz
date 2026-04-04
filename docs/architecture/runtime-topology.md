# 运行拓扑

## 进程图

```text
browser
  -> FastAPI API
      -> /api/system/*
      -> /api/admin/*
      -> /api/public/*
      -> /static/*
      -> /legacy/*  (307 跳转到真实路径)
      -> /admin*    (后台 Alpine SPA)
      -> /p/* /t/* /resume/* /quiz/* /done/* /a/* (候选人 Alpine SPA)

scheduler
  -> enqueue jobs

worker
  -> claim jobs
  -> process jobs
```

## 当前实现

### API

- 入口：`backend/md_quiz/main.py`
- 装配：`backend/md_quiz/app.py`
- 静态资源：`/static/*`
- 默认后台入口：`/admin`
- 根路径：按登录态 307 跳转到 `/admin` 或 `/admin/login`
- `/legacy/*`：兼容跳转到当前真实路径

### Worker

- 入口：`backend/md_quiz/worker.py`
- 当前职责：轮询 job store 并执行轻量任务处理器

### Scheduler

- 入口：`backend/md_quiz/scheduler.py`
- 当前职责：定时投递 `sync_metrics` 等周期任务

## 当前存储边界

运行时状态已经统一入库：

- `runtime_kv`
- `runtime_daily_metric`
- `runtime_job`
- `process_heartbeat`

根目录 `storage/` 不再是当前运行时依赖；历史 `storage/runtime/*.json` 仅在兼容旧部署数据时作为一次性迁移输入源读取一次。
