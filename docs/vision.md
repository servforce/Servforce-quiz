# 项目愿景

`md-quiz` 是面向测评与考核场景的在线问卷 / 在线笔试系统，当前重点覆盖以下核心与典型使用场景：

- 招聘测评
- 内部周期性考核
- 访谈性评估
- 培训后测试
- 晋升 / 认证类评估
- 专项能力盘点与阶段性抽检

系统能力覆盖：

- 测验配置
- 候选人管理
- 邀约与验证
- 在线答题
- 自动判卷
- 归档回看
- 运行监控

## 当前系统基线

当前代码已经收敛到以下稳定基线：

- `FastAPI` 作为统一 HTTP 入口
- `API / Worker / Scheduler` 三进程执行面
- 双 Alpine SPA：`static/admin/` 与 `static/public/`
- 运行时配置、任务队列和进程心跳统一入库
- 题库同步、判卷、简历解析等重任务脱离请求线程

## 不变约束

- 业务主题仍是“测评 / 考核”，不是通用 LMS
- 招聘测评、内部周期性考核、访谈性评估等都是核心场景，不把产品收窄为单一招聘工具
- 产品更偏向“结构化评估、问卷执行、结果留档与回看”，而不是课程教学、课件分发、学员运营这类 LMS 能力
- 前端基础品牌配色保留当前蓝绿体系
- 核心业务概念不丢：
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
