# 架构总览

## 当前形态

### 进程

- `API`：FastAPI，对外提供 `/api/*`、会话、SPA 入口、静态资源和试卷资源路由
- `Worker`：执行异步任务
- `Scheduler`：投递周期任务

### 兼容面

- `/legacy/*` 只保留为到当前真实路径的兼容跳转

## 代码结构

```text
backend/md_quiz/
  api/
  models/
  parsers/
  services/
  storage/
  app.py
  main.py
  worker.py
  scheduler.py

static/
  admin/
  public/
  assets/css/
```

## 核心边界

- 路由层只做协议适配
- 服务层负责业务编排
- 存储层负责持久化边界
- Worker / Scheduler 脱离请求线程
- 管理端与候选人端都由 Alpine SPA 承载，不再依赖 Jinja 页面渲染
- 仓库内应用 Python 代码统一收敛到 `backend/md_quiz/`
