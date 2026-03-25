# 架构总览

## 当前目标形态

### 进程

- `API`：FastAPI，对外提供 `/api/*`、会话、静态资源和根路径下的 Flask 挂载
- `Worker`：执行异步任务
- `Scheduler`：投递周期任务

### 兼容面

- 旧 Flask 单体仍在 `web/`
- `/legacy/*` 只保留为到当前真实路径的兼容跳转

## 代码结构

```text
backend/md_quiz/
  api/
  models/
  services/
  storage/
  app.py
  main.py
  worker.py
  scheduler.py

web/
  ... flask admin/public routes ...
```

## 核心边界

- 路由层只做协议适配
- 服务层负责业务编排
- 存储层负责持久化边界
- Worker / Scheduler 脱离请求线程
- 管理端页面继续沿用 `templates/` + `static/`

## 当前阶段说明

第一阶段已落地：

- FastAPI 应用骨架
- runtime config / job / process heartbeat 的独立存储边界
- worker / scheduler 进程入口
- 根路径下的 Flask 挂载

后续迁移重点：

- 真实业务 API 逐步从 `web/routes/` 迁到 `backend/md_quiz/api/`
- 旧后台内部模块继续拆直
- 旧 `admin_dashboard.html` 等重复实现逐步退出
