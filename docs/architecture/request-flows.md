# 核心请求流程

## 管理员后台

1. 浏览器访问 `/`
2. FastAPI 将请求委托给挂载在根路径的 Flask 应用
3. Flask 根据登录态跳转到 `/admin` 或 `/admin/login`

## 旧链接兼容

1. 浏览器访问 `/legacy/admin` 或其他 `/legacy/*`
2. FastAPI 返回 307 跳转到去掉 `/legacy` 前缀后的真实路径
3. 浏览器重新访问 `/admin/*` 或对应旧路径

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
