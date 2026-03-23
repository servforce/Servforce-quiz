# 架构总览

## 当前目标形态

### 进程

- `API`：FastAPI，对外提供 `/api/*`、会话、静态资源和 UI 壳层
- `Worker`：执行异步任务
- `Scheduler`：投递周期任务

### 前端

- `ui/`：前端源码工作区
- `static/app/`：运行时静态产物

### 兼容面

- 旧 Flask 单体仍在 `web/`，通过 `/legacy` 暂时桥接
- 新系统默认不再以旧模板作为长期实现

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

ui/
  src/
  templates/
  scripts/

web/
  ... legacy flask monolith ...
```

## 核心边界

- 路由层只做协议适配
- 服务层负责业务编排
- 存储层负责持久化边界
- Worker / Scheduler 脱离请求线程
- UI 构建与运行解耦：构建阶段用 Node，运行阶段只读静态文件

## 当前阶段说明

第一阶段已落地：

- FastAPI 应用骨架
- runtime config / job / process heartbeat 的独立存储边界
- worker / scheduler 进程入口
- ui/ 工作区与构建流程
- legacy bridge

后续迁移重点：

- 真实业务 API 逐步从 `web/routes/` 迁到 `backend/md_quiz/api/`
- 旧模板页逐步迁到 `ui/`
- 旧 `admin_dashboard.html` 等重复实现逐步退出
