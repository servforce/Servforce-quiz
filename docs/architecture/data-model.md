# 数据模型与存储

## 业务概念

后续正式迁移时，以下业务概念保持不变：

- `candidate`
- `exam_definition`
- `assignment`
- `attempt`
- `archive/result`
- `system_metric`
- `operation_log`
- `runtime_config`
- `job`

## 当前新架构已落地的存储

### `runtime_config`

用于保存运行时行为开关，例如：

- 是否启用短信验证
- token / 短信阈值
- 是否允许公开邀约
- 最短交卷时长
- UI 主题名

### `job`

当前字段包括：

- `id`
- `kind`
- `status`
- `payload`
- `source`
- `attempts`
- `worker_name`
- `created_at / updated_at / started_at / finished_at`

### `process heartbeat`

用于展示：

- API
- Worker
- Scheduler

的当前状态与最近更新时间。

## 当前数据库表

运行时状态现在统一保存在 PostgreSQL 中：

- `runtime_kv`
  - 保存 `runtime_config`
  - 保存 exam repo sync 状态、运行时迁移标记等键值数据
- `runtime_daily_metric`
  - 保存系统状态页按日聚合指标与告警快照
- `runtime_job`
  - 保存后台任务队列、执行状态与结果
- `process_heartbeat`
  - 保存 API / Worker / Scheduler 心跳

## 迁移说明

历史 `storage/runtime/*.json` 只在需要兼容旧部署数据时作为一次性迁移输入源：

- 首次启动时若检测到旧 JSON，会自动导入数据库
- 导入完成后不再继续写入这些文件
- 后续运行时状态以数据库为唯一事实来源
- 若仓库里已经没有旧运行时 JSON，根目录 `storage/` 目录本身也不再是运行时依赖
