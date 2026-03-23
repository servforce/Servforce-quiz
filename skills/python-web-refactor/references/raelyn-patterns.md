# `raelyn` 可迁移模式

本文只记录适合抽象成通用方法的模式，不把项目私有业务细节原样搬进 skill。

## 1. 进程边界

项目当前采用 `API + worker + scheduler + 挂载式 MCP` 的形态：

- API 进程负责 HTTP / WebSocket / SPA 壳与依赖初始化
- worker 负责领取和执行异步任务
- scheduler 负责分钟级调度
- MCP 复用现有 DB / service / enqueue 能力，不再额外包一层 API

可迁移结论：

- 有真实重任务时，把执行面从请求线程拆出去
- 没有真实重任务时，不强推独立 worker
- API 入口应以“装配”为主，而不是堆业务逻辑

代码依据：

- `backend/raelyn/main.py`
- `backend/raelyn/worker.py`
- `backend/raelyn/scheduler.py`

## 2. 模块分层

后端目录当前按职责拆成：

- `api/`：路由、请求体、响应体、HTTP 协议适配
- `services/`：业务编排与外部依赖交互
- `jobs/`：异步任务投递、领取、执行、恢复
- `mcp/`：挂载式 MCP 协议适配
- `tools/`：运维与一次性工具脚本
- `tests/`：测试

可迁移结论：

- 路由不要直接承载业务编排
- 外部依赖调用、领域流程、状态转换应聚到服务层
- 重任务执行逻辑不要散落在 API 和脚本里

代码依据：

- `backend/raelyn/api/`
- `backend/raelyn/services/`
- `backend/raelyn/jobs/`
- `backend/raelyn/tools/`

## 3. 配置治理

项目将配置拆成两层：

- 环境变量：进程启动时读取，放在 `backend/raelyn/config.py`
- 运行时配置：保存在 `app_config`，通过 API 修改

可迁移结论：

- 基础设施、连接串、进程级开关放环境变量
- 可在线调整的业务开关放运行时配置
- 不要把“需要重启的配置”和“运行时行为开关”混成一坨

代码与文档依据：

- `backend/raelyn/config.py`
- `backend/raelyn/models.py` 中 `AppConfig`
- `docs/reference/configuration.md`

## 4. 启动治理

项目通过统一 shell 入口约束开发运行方式：

- `scripts/dev/run-api.sh`
- `scripts/dev/run-worker.sh`
- `scripts/dev/run-scheduler.sh`

这些脚本统一处理：

- 切到项目根目录
- 自动加载 `.env`
- 优先使用 `.venv/bin/python`
- 显式设置 `PYTHONPATH`

可迁移结论：

- 启动方式要单一、显式、可复制
- 不要让每个开发者手工拼启动命令
- 本地依赖、虚拟环境、环境变量加载应有固定入口

## 5. 文档入口

项目把不同类型信息拆到不同文档：

- `docs/vision.md`：项目愿景与范围
- `docs/architecture/overview.md`：架构总览与导航
- `docs/api/rest.md`：接口说明
- `docs/reference/configuration.md`：配置说明
- `docs/README.md`：文档索引

可迁移结论：

- 愿景、架构、接口、配置不要混写到一个 README
- 文档必须有统一入口
- 方案输出应优先更新对应专题文档，而不是把细节堆到总览页

## 6. 测试策略

项目当前同时存在 API、服务、任务相关测试，强调：

- 优先围绕真实链路校验
- 只有必要时才做小范围 mock
- 测试命名与职责边界保持一致

可迁移结论：

- 服务重构不能只改目录不补验证
- 先补住关键链路，再收紧局部实现
- 测试目录最好能映射模块职责，而不是随意堆放
