# REST API 约定

## System

### `GET /api/system/health`

返回 API 健康状态。

### `GET /api/system/processes`

返回 API / Worker / Scheduler 心跳列表。

### `GET /api/system/bootstrap`

返回品牌信息、后台入口、运行时配置。

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

### `GET /api/admin/exams`

返回试卷列表、分页信息与当前同步状态。

### `GET /api/admin/exams/{exam_key}`

返回试卷详情、版本历史、公开邀约状态与试卷快照。

### `POST /api/admin/exams/sync`

创建或复用试卷仓库同步任务。

### `POST /api/admin/exams/{exam_key}/public-invite`

开启或关闭公开邀约。

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

### `POST /api/admin/assignments`

创建新的答题邀约。

### `GET /api/admin/attempts/{token}`

返回 assignment 与归档详情；`/api/admin/results/{token}` 为同义接口。

### `GET /api/admin/assignments/{token}/qr.png`

返回邀约二维码 PNG。

### `GET /api/admin/logs`

返回系统日志列表、分类计数，以及近 N 天的分类趋势序列。

### `GET /api/admin/logs/updates`

按 `after_id` 返回增量日志。

### `GET /api/admin/system-status/summary`

返回当天系统状态摘要。

### `GET /api/admin/system-status`

返回区间系统状态数据。

### `PUT /api/admin/system-status/config`

更新系统状态阈值。

### `GET /api/admin/config`

返回 runtime config。

### `PUT /api/admin/config`

更新 runtime config。

### `GET /api/admin/jobs`

列出任务。

### `POST /api/admin/jobs`

投递任务。

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

### `POST /api/public/invites/{public_token}/ensure`

根据公开邀约 token 复用或创建答题实例。

### `GET /api/public/invites/{public_token}/qr.png`

返回公开邀约二维码 PNG。

### `GET /api/public/attempt/{token}`

返回候选人端当前步骤、答题状态、简历状态或判卷结果。

### `POST /api/public/attempt/{token}/enter`

进入答题页并启动倒计时。

### `POST /api/public/sms/send`

发送短信验证码。

### `POST /api/public/verify`

验证姓名、手机号与短信验证码。

### `POST /api/public/resume/upload`

公开邀约场景上传简历并创建候选人。

### `POST /api/public/answers/{token}`

保存单题答案。

### `POST /api/public/answers_bulk/{token}`

批量保存答案。

### `POST /api/public/submit/{token}`

提交答卷并触发后台判卷。
