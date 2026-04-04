# 数据模型与存储

## 业务概念

当前代码中的核心业务概念包括：

- `candidate`
- `candidate_resume`
- `quiz_definition`
- `quiz_version`
- `assignment`
- `quiz_paper`
- `quiz_archive`
- `system_metric`
- `operation_log`
- `runtime_config`
- `job`
- `process heartbeat`

## 当前运行时配置与状态存储

### `runtime_config`

用于保存运行时行为开关，例如：

- token / 短信阈值
- 是否允许公开邀约
- 最短交卷时长
- UI 主题名

### `job`

当前任务记录保存在 `runtime_job` 表。核心字段包括：

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
- `created_at / updated_at / started_at / lease_expires_at / finished_at`

当前任务模型约束：

- `status` 目前只有 `pending / running / done / failed`
- `grade_attempt` 使用 `dedupe_key=grade_attempt:<token>`
- 同一 `dedupe_key` 在 `pending / running` 状态下只能有一条活跃记录
- `running` 且 lease 过期的任务可以被 Worker 回收重跑

### `process heartbeat`

用于展示：

- API
- Worker
- Scheduler

的当前状态与最近更新时间。

## 当前数据库表

运行时状态统一保存在 PostgreSQL 中：

- `runtime_kv`
  - 保存 `runtime_config`
  - 保存测验仓库绑定、同步状态、运行时迁移标记等键值数据
- `runtime_daily_metric`
  - 保存系统状态页按日聚合指标与告警快照
- `runtime_job`
  - 保存后台任务队列、执行状态与结果
- `process_heartbeat`
  - 保存 API / Worker / Scheduler 心跳

业务主数据同样已经落在 PostgreSQL，对应表结构以 `backend/md_quiz/storage/db.py:init_db()` 为准。

## 迁移说明

历史 `storage/runtime/*.json` 只在需要兼容旧部署数据时作为一次性迁移输入源：

- 首次启动时若检测到旧 JSON，会自动导入数据库
- 导入完成后不再继续写入这些文件
- 后续运行时状态以数据库为唯一事实来源
- 若仓库里已经没有旧运行时 JSON，根目录 `storage/` 目录本身也不再是运行时依赖
