# 运行拓扑

## 进程图

```text
browser
  -> FastAPI API
      -> /api/system/*
      -> /api/admin/*
      -> /api/public/*
      -> /static/*
      -> /legacy/*  (bridge 到旧 Flask)

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
- UI：`/` -> `static/app/index.html`

### Worker

- 入口：`backend/md_quiz/worker.py`
- 当前职责：轮询 job store 并执行轻量任务处理器

### Scheduler

- 入口：`backend/md_quiz/scheduler.py`
- 当前职责：定时投递 `sync_metrics` 等周期任务

## 当前存储边界

第一阶段为了先把边界拉直，运行时数据先落在：

- `storage/runtime/runtime-config.json`
- `storage/runtime/jobs.json`
- `storage/runtime/processes.json`

后续再把真实业务主数据迁到正式 repository / database 层。
