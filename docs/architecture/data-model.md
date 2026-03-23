# 数据模型与存储

## 总体原则

- PostgreSQL 是业务权威源。
- 运行目录中的文件用于上传件和临时产物，不承担业务状态真相源职责。
- 表结构事实以 `db.py:init_db()` 为准；文档只做说明，不替代 schema。

## 核心表

### `candidate`

- 候选人基础信息。
- 存储姓名、手机号、创建时间、删除时间，以及简历文件和解析结果。
- 当前不再直接承载考试状态、分数、开考时间等字段。

### `exam_paper`

- 单个候选人在单个 token 下的一次考试实例。
- 保存 `candidate_id`、`phone`、`exam_key`、`token`、邀请窗口和考试状态。
- 用于支撑“同一候选人多次邀约/多次作答”的独立记录。

### `assignment_record`

- 管理员创建的分发记录。
- 保存邀请时间窗、时间限制、最短交卷时长、验证次数、通过阈值、答案和流程状态。
- 是公开链接、专属链接和交卷推进的重要载体。

### `exam_definition`

- 试卷定义主表。
- 保存原始 Markdown、结构化试卷、公开邀约配置以及创建时间。

### `exam_asset`

- 试卷关联资源。
- 以 `exam_key + relpath` 唯一约束保存题面图片等二进制资源。

### `exam_archive`

- 已完成考试的归档快照。
- 保存候选人、试卷、答案结果和回放所需信息，供后台回看。

### `runtime_kv`

- 低频系统级配置，例如系统状态面板配置。

### `runtime_daily_metric`

- 按天聚合的运行指标。
- 典型内容包括短信调用量、LLM token 使用量和告警状态。

### `system_log`

- 操作日志、系统事件、LLM 调用成本和告警事件。
- 支持按 `event_type`、`candidate_id`、`exam_key`、`token` 检索。

## 关系理解

- `candidate` 是候选人主实体。
- `assignment_record` 描述“某次分发/邀约”。
- `exam_paper` 描述“某个 token 对应的实际考试实例”。
- `exam_archive` 描述“考试结束后的冻结快照”。
- `exam_definition` 和 `exam_asset` 共同组成试卷静态定义。

## 运行目录

- 默认运行目录由 `STORAGE_DIR` 控制，未配置时为项目根下的 `storage/`。
- 该目录通常保存上传简历、导出文件或临时产物。
- 即使运行目录内容丢失，数据库仍应保留主要业务状态。
