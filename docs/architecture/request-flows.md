# 核心请求流程

## 管理员后台 SPA

1. 浏览器访问 `/` 时，请求直接进入 FastAPI。
2. FastAPI 读取 `api_session` 中的登录态，返回 `307` 跳转到 `/admin` 或 `/admin/login`。
3. 浏览器访问 `/admin`、`/admin/login` 或 `/admin/{full_path}` 时，FastAPI 统一返回 `static/admin/index.html` 作为后台 SPA 壳。
4. 后台 Alpine SPA 启动后先调用 `/api/admin/session`。
5. 已登录时再调用 `/api/admin/bootstrap`、状态摘要和部分列表接口。
6. `static/admin/modules/router.js` 按路径把 `static/admin/pages/*.html` 片段加载到壳层挂载点。
7. 页面级模块再按需调用 `/api/admin/*` 接口完成题库、候选人、邀约、日志和系统状态页面交互。

## 候选人端 SPA

1. 浏览器访问 `/p/{public_token}`、`/t/{token}`、`/resume/{token}`、`/quiz/{token}`、`/done/{token}` 等路径时，请求进入 FastAPI。
2. FastAPI 统一返回 `static/public/index.html` 作为候选人端 SPA 壳。
3. `static/public/modules/router.js` 先解析路径：
   - `/p/{public_token}` 会先请求 `/api/public/invites/{public_token}/ensure`
   - 其它路径直接识别为既有答题 token
4. 前端为每个 token 维护一个 `sessionStorage` 会话 ID，并在后续请求里带上 `X-Public-Session-Id`。
5. 前端请求 `/api/public/attempt/{token}` 获取当前步骤、公开测验快照、答题状态和结果状态。
6. 返回的 `step` 决定候选人端视图切到 `start / resume / question / done / unavailable`，并动态挂载 `static/public/views/*.html` 片段。

## 旧链接兼容

1. 浏览器访问 `/legacy` 或 `/legacy/{full_path}` 时，请求仍由 FastAPI 直接处理。
2. FastAPI 返回 `307` 跳转到去掉 `/legacy` 前缀后的当前真实路径。
3. 其中 `/legacy` 会跳转到 `/admin`；`/legacy/admin/quizzes?q=tag` 会跳转到 `/admin/quizzes?q=tag`，查询参数会原样保留。

## 判卷任务链路

1. 候选人主动提交、单题超时推进到末题自动提交，或公开流程回访触发结束态时，`runtime_jobs._finalize_public_submission(...)` 会把 assignment 改成 `grading`。
2. assignment 会写入：
   - `status=grading`
   - `grading.status=pending`
   - `timing.end_at`
3. 同时调用 `ensure_grade_attempt_job(token)`，向 `runtime_job` 投递或复用 `grade_attempt:<token>`。
4. Worker 轮询 `runtime_job`，原子 claim 该任务并把它切到 `running`。
5. `JobService.process()` 进入 `grade_attempt` 分支，调用 `runtime_jobs.process_grade_attempt_job(token)`。
6. 判卷任务会在一个 job 内串行完成：
   - 判卷
   - 候选人评语 / 分析
   - `quiz_paper` 状态与得分同步
   - 归档补齐
7. 完成后：
   - assignment 改为 `grading.status=done`
   - `quiz_archive` / `quiz_paper` 已可供后台与候选人完成页读取
   - `runtime_job` 改为 `done`

## 周期任务链路

1. Scheduler 定时 tick
2. 满足间隔条件后投递 `sync_metrics`
3. Worker 处理
4. API / UI 通过 `/api/system/processes` 与 `/api/admin/jobs` 可观测
