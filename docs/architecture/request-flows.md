# 核心请求流程

## 管理员后台

1. 浏览器访问 `/`
2. FastAPI 返回 `static/app/index.html`
3. UI 读取 `/api/system/bootstrap`
4. 后台登录通过 `/api/admin/session/login`
5. 页面通过 `/api/admin/*` 拉取数据
6. 尚未迁移的功能通过 `/legacy/admin/*` 访问旧系统

## 任务链路

1. 管理端调用 `/api/admin/jobs`
2. API 写入 job store
3. Worker 轮询并 claim job
4. 处理完成后写回 job 状态
5. UI 刷新任务列表

## 周期任务链路

1. Scheduler 定时 tick
2. 满足间隔条件后投递 `sync_metrics`
3. Worker 处理
4. API / UI 通过 `/api/system/processes` 与 `/api/admin/jobs` 可观测
