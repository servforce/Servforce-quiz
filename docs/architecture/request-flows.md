# 核心请求流程

## 管理员后台

1. 浏览器访问 `/` 时，请求直接进入 FastAPI。
2. FastAPI 读取 `api_session` 中的登录态，返回 `307` 跳转到 `/admin` 或 `/admin/login`。
3. 浏览器访问 `/admin`、`/admin/login` 或 `/admin/{full_path}` 时，FastAPI 统一返回 `static/admin/index.html` 作为后台 SPA 壳。
4. 后台 Alpine SPA 启动后调用 `/api/admin/session`，再按登录态决定停留在登录页还是继续加载 `/api/admin/*` 数据接口。

## 旧链接兼容

1. 浏览器访问 `/legacy` 或 `/legacy/{full_path}` 时，请求仍由 FastAPI 直接处理。
2. FastAPI 返回 `307` 跳转到去掉 `/legacy` 前缀后的当前真实路径。
3. 其中 `/legacy` 会跳转到 `/admin`；`/legacy/admin/exams?q=tag` 会跳转到 `/admin/exams?q=tag`，查询参数会原样保留。

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
