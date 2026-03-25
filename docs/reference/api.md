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
