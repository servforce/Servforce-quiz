# 项目愿景

`md-quiz` 是面向招聘场景的在线笔试系统，覆盖：

- 试卷配置
- 候选人管理
- 邀约与验证
- 在线答题
- 自动判卷
- 归档回看
- 运行监控

## 当前重构目标

项目正在从旧的 `Flask + Jinja` 单体实现，升级到新的：

- `FastAPI` 后端
- `API / Worker / Scheduler` 三进程
- 独立 `ui/` 工作区
- 本地构建、运行时静态输出

## 不变约束

- 业务主题仍是“招聘考试”，不是通用 LMS
- 前端基础品牌配色保留当前蓝绿体系
- 核心业务概念不丢：
  - `candidate`
  - `exam_definition`
  - `assignment`
  - `attempt`
  - `archive/result`
  - `system_metric`
  - `operation_log`
  - `runtime_config`
  - `job`
