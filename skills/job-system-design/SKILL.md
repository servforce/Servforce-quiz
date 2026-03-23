---
name: job-system-design
description: Use this skill when designing, reviewing, or refactoring a job system, worker, scheduler, queue, retry policy, lease/heartbeat recovery, atomic claim flow, idempotency model, concurrency guardrails, observability, or parent-child task orchestration.
---

# Job System Design

## 何时使用

在以下场景优先使用这个 skill：

- 设计或重构任务系统
- 调整 `worker / scheduler / queue` 协作模型
- 设计或评审 `retry / lease / heartbeat / recovery`
- 设计原子领取（atomic claim）与幂等机制
- 设计外部依赖并发门控
- 设计父子任务编排与进度聚合
- 设计任务系统的日志、指标与排障视图

## 工作流

1. 先判断当前任务属于“设计评审”还是“实现改造”。
2. 先确认任务系统是否满足这些基础约束：
   - 单一事实源
   - Web/API 与执行面解耦
   - 原子领取
   - 幂等写入
   - 故障恢复与回收
   - 可观测性
3. 如果要进入细节设计，再读取 [references/principles.md](references/principles.md)。
4. 如果是项目内实现任务，最后再回到项目自身的模型、数据库和接口约束，不要把通用原则直接当成实现细节。

## 检查清单

- 真实执行状态是否落在统一任务存储中，而不是只存在内存里
- 请求线程是否只负责创建 / 查询 / 运维，而不直接跑重活
- `pending -> running` 是否通过原子 claim 完成
- 长任务是否有 lease / heartbeat / recovery
- 写入侧是否具备幂等锚点
- 外部依赖是否有明确并发门控
- 父子任务的状态与进度是否可解释
- 日志 / 指标 / 错误信息是否足够排障且默认脱敏

## 参考资料

- 通用原则： [references/principles.md](references/principles.md)
- 项目内落地： [../../docs/architecture/job-system.md](../../docs/architecture/job-system.md)
