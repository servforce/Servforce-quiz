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

## 阶段性说明

第一阶段先用 JSON store 把“配置 / 任务 / 进程状态”从旧 Flask 进程内状态中拆出来；
后续迁移真实业务主数据时，再把旧 `db.py` 拆成 repository / query 层。
