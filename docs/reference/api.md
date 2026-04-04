# REST API 约定

## System

### `GET /api/system/health`

返回 API 健康状态。

### `GET /api/system/processes`

返回 API / Worker / Scheduler 心跳列表。

### `GET /api/system/bootstrap`

返回品牌信息、后台入口、运行时配置，以及 MCP 接入摘要。

其中 `mcp` 字段包括：

- `enabled`
- `path`
- `transport`
- `auth_scheme`
- `docs_path`

说明：

- 管理端和候选人端仍以 REST 为主协议面
- 智能体自动化链路可通过 `/mcp` 调用同一批后台业务能力

## Admin

### `POST /api/admin/session/login`

请求：

```json
{ "username": "admin", "password": "password" }
```

### `POST /api/admin/session/logout`

清空后台会话。

### `GET /api/admin/session`

返回当前后台登录状态。

### `GET /api/admin/bootstrap`

返回后台入口导航与概览卡片。

### `GET /api/admin/quizzes`

返回测验列表、分页信息、实例级仓库绑定信息与当前同步状态。

### `GET /api/admin/quizzes/{quiz_key}`

返回测验详情、版本历史、公开邀约状态与测验快照。

题目快照中的展示字段约定：

- `stem_md` / `rubric` / `options[].text`：原始文本
- `stem_html` / `rubric_html` / `options[].text_html`：供前端直接展示的 HTML
- `rubric_html` 仅在管理端详情与答题回放接口返回，公开答题接口不暴露评分标准

### `POST /api/admin/quizzes/binding`

首次绑定测验仓库，并自动尝试创建同步任务。

请求：

```json
{ "repo_url": "https://github.com/example/repo.git" }
```

### `POST /api/admin/quizzes/binding/rebind`

重新绑定测验仓库。会删除当前实例中的测验、版本、邀约与答题归档数据，但保留候选人与简历；成功后自动尝试创建同步任务。

请求：

```json
{
  "repo_url": "https://github.com/example/new-repo.git",
  "confirmation_text": "重新绑定"
}
```

### `POST /api/admin/quizzes/sync`

为当前已绑定仓库创建或复用同步任务。

说明：

- 未绑定仓库时返回 `409`
- 请求体中的 `repo_url` 仅为兼容保留，服务端会忽略它，不允许借此覆盖当前绑定仓库

### `POST /api/admin/quizzes/{quiz_key}/public-invite`

开启或关闭公开邀约。

返回字段包括：

- `enabled`
- `token`
- `public_url`
- `qr_url`

当关闭公开邀约时，`public_url` 和 `qr_url` 会返回空字符串。

### `GET /api/admin/candidates`

返回候选人列表与筛选条件。

### `POST /api/admin/candidates`

创建候选人。

### `POST /api/admin/candidates/resume/upload`

从简历直接创建或更新候选人。

### `GET /api/admin/candidates/{candidate_id}`

返回候选人详情、简历解析结果与答题记录。

### `POST /api/admin/candidates/{candidate_id}/evaluation`

追加管理员评价。

### `GET /api/admin/candidates/{candidate_id}/resume`

下载候选人简历。

### `POST /api/admin/candidates/{candidate_id}/resume/reparse`

上传新简历并重新解析。

### `DELETE /api/admin/candidates/{candidate_id}`

删除候选人；若已有答题记录则执行软删除。

### `GET /api/admin/assignments`

返回邀约与答题实例列表。

支持筛选参数：

- `q`
- `start_from`
- `start_to`
- `end_from`
- `end_to`
- `page`

列表项会返回邀约访问地址 `url` 与二维码地址 `qr_url`。

### `POST /api/admin/assignments`

创建新的答题邀约。整卷答题时长不再由请求手填，服务端会按测验中每道题的 `answer_time` 自动累计写入 assignment。

- `ignore_timing=true` 时，当前邀约会关闭单题倒计时、超时自动跳题和整卷超时自动交卷。
- 返回的 assignment/list item 会包含 `ignore_timing` 字段。

### `GET /api/admin/attempts/{token}`

返回 assignment 与归档详情；`/api/admin/results/{token}` 为同义接口。

`review.answers[*]` 中会同时返回：

- `stem_html`
- `rubric_html`
- `options[].text_html`

### `GET /api/admin/assignments/{token}/qr.png`

返回邀约二维码 PNG。

### `GET /api/admin/logs`

返回系统日志列表、分类计数，以及近 N 天的分类趋势序列。

### `GET /api/admin/logs/updates`

按 `after_id` 返回增量日志。

### `GET /api/admin/system-status/summary`

返回当天系统状态摘要。

- `llm` / `sms` 除了当天用量、阈值、配置缺失信息外，还会返回当前接入摘要：
  - `integration.title`
  - `integration.summary`

### `GET /api/admin/system-status`

返回区间系统状态数据；其中 `summary` 字段与 `GET /api/admin/system-status/summary` 保持一致。

### `PUT /api/admin/system-status/config`

更新系统状态阈值。

### `GET /api/admin/config`

返回 runtime config。

### `PUT /api/admin/config`

更新 runtime config。

### `GET /api/admin/jobs`

列出任务。

返回的任务项当前至少包括：

- `id`
- `kind`
- `status`
- `payload`
- `source`
- `dedupe_key`
- `attempts`
- `error`
- `result`
- `worker_name`
- `created_at`
- `updated_at`
- `started_at`
- `lease_expires_at`
- `finished_at`

### `POST /api/admin/jobs`

投递任务。

说明：

- 这是通用后台/运维入口
- `grade_attempt` 通常不会由前端手工调用，而是由公开提交流程自动幂等投递

请求：

```json
{
  "kind": "scan_exams",
  "payload": {}
}
```

## Public

### `GET /api/public/bootstrap`

返回候选人端入口配置与功能开关。

### `GET /api/public/attempt/{token}`

返回候选人当前答题状态与公开测验快照。

其中 `quiz.spec.questions[*]` 的展示字段包括：

- `stem_html`
- `options[].text_html`

公开接口不返回 `rubric` / `rubric_html`。

### `POST /api/public/invites/{public_token}/ensure`

根据公开邀约 token 复用或创建答题实例。

### `GET /api/public/invites/{public_token}/qr.png`

返回公开邀约二维码 PNG。

### `GET /api/public/attempt/{token}`

返回候选人端当前步骤、答题状态、线性题流状态、简历状态或判卷结果。

- `step=verify`：返回开始卡片所需的验证信息；主动邀约只返回手机号掩码和验证码入口，公开邀约返回姓名/手机号/验证码入口。
- `step=resume`：公开邀约验证码通过但尚未建档时返回简历上传卡片信息。
- `step=quiz`：返回开始卡片或当前题卡片需要的公开测验快照、当前题索引、当前题开始时间、跨会话重进计数等；若 assignment 的 `ignore_timing=true`，倒计时相关字段会归零。
- `step=done`：返回结束卡片与判卷状态。

### `POST /api/public/attempt/{token}/enter`

进入第 1 题并启动线性答题流程。请求头会读取 `X-Public-Session-Id`，用于识别跨会话重进。

### `POST /api/public/sms/send`

发送短信验证码。

- 主动邀约 + 短信验证：只依赖 token 对应候选人的目标手机号，不再要求前端填写姓名/手机号。
- 公开邀约：仍要求姓名与手机号。

### `POST /api/public/verify`

验证短信认证并推进到下一步。

- 主动邀约：只要求验证码。
- 公开邀约：要求姓名、手机号与验证码；验证成功后进入简历上传或直接进入开始卡片。

### `POST /api/public/resume/upload`

公开邀约场景上传简历并创建候选人。上传成功后立即放行到开始卡片，简历结构化解析改为异步 job 回填。

### `POST /api/public/answers/{token}`

保存当前题答案，并可按请求语义推进到下一题或直接提交。旧题保存会返回冲突，候选人端据此禁止回退修改。

### `POST /api/public/answers_bulk/{token}`

兼容旧接口；当前仅接受“单题自动保存”语义，不再支持整卷批量保存。

### `POST /api/public/submit/{token}`

直接提交当前答卷并触发后台判卷。线性答题模式下，前端通常在最后一题通过 `POST /api/public/answers/{token}` 的 `submit=true` 直接完成提交。
