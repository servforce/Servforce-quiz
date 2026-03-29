# Agent instructions

本文件只保留高频、全局、必须立即生效的规则；详细协作细则放到 `docs/` 分层维护。

- 通用协作与编码细则见 [docs/agent-rules/general.md](docs/agent-rules/general.md)。

## 通用规则

- 默认使用中文回复；代码注释、文档说明优先使用中文。
- 先读文档、代码、日志和测试，再改实现；没有证据时不要猜接口行为。
- 涉及试卷格式时，先核对 [qml.md](qml.md) 和 `qml/parser.py`，不要凭页面表现反推语法。
- 涉及数据库行为时，先核对 `db.py` 中的表结构和读写函数；表结构以代码中的 `init_db()` 为准。
- 优先修根因，不用绕路兼容、吞错、重复兜底来掩盖问题。
- 代码优先直线化、可读性和可验证性；避免无收益的抽象、层层转发和隐式状态。
- 涉及页面或布局调整时，默认按组件级或页面级重新设计结构与响应式，不在旧布局上持续叠加补丁式修补。
- 禁止在回复、日志、命令输出中暴露密钥、短信凭据、数据库密码、候选人隐私数据。`
- 禁止执行会覆盖或清空工作区的操作，例如 `git reset --hard`、`git clean -fd`、`git restore .`。
- 新增或调整测试时，优先覆盖真实模块边界；只有用户明确要求时才默认使用 mock。

## PLAN 规则

- 必须区分“事实/证据”和“推断/猜测”；证据不足时先补上下文。
- 给方案时，默认只保留当前场景下最优的可执行方案；保留备选项时必须写清适用边界。

## 文档协作约定

- 项目愿景与范围维护在 [docs/vision.md](docs/vision.md)。
- 文档导航维护在 [docs/README.md](docs/README.md)。
- 架构总览维护在 [docs/architecture/overview.md](docs/architecture/overview.md)。
- 配置项说明维护在 [docs/reference/configuration.md](docs/reference/configuration.md)。
- 修改专题内容时，优先更新对应专题文档，不要把细节堆回总览页。
- 新增重要文档或调整路径时，需同步更新 [docs/README.md](docs/README.md) 中的导航。

## 项目内 Skills 使用约定

- `skills/job-system-design/SKILL.md`：涉及后台线程、任务状态、重试、调度、可观测性时优先使用。
- `skills/static-ui/SKILL.md`：涉及 `templates/`、`static/`、管理端或候选人端页面改造时优先使用。
- `skills/python-web-refactor/SKILL.md`：涉及 Flask 入口、路由拆分、配置治理、测试补齐、文档补齐时优先使用。

## 维护边界

- `docs/` 承载项目文档与规则索引。
- `skills/` 承载专项执行方法。
- `README.md` 负责对外介绍、启动方式和最小可运行说明，不承载完整架构细节。
