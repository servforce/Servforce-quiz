# MD Quiz

`md-quiz` 是一套 `code-first`、`agent-ready`、面向真实业务运行的`agent-native`评估系统。`md-quiz`不把测评理解成“做一张表、发一个链接、收一份答案”，而是把整个过程当成一套可以被定义、执行、观测、审计和持续演进的运行时：题库有版本，流程有边界，结果能回看，系统还能继续学习和扩展。

题目并不躲在后台表单里，而是和代码一样存在于仓库中；判卷并不只是静态规则，而是可以接入 LLM 的结构化推理；后台并不是唯一入口，MCP 把核心能力开放给智能体；项目知识也不只写在脑子里，而是沉淀进 `skills/`，变成可复用的维护能力。`md-quiz` 的价值不在于“会不会发题”，而在于它把内容、流程、智能和自动化收束成了一套有边界、有记忆、能协作的评估底座。

![界面截图](img/readme-overview.png)

## 适合什么场景

- 招聘筛选与在线笔试
- 内部考核与培训结课测试
- 访谈式评估、晋升评审、认证类测验
- 需要公开邀约、短信验证、版本化题库和结果留档的场景

## 核心能力

- 题库放在 Git 仓库里维护，`md-quiz-repo.yaml`、`quiz.md` 和 `assets/` 一起定义测验内容，适合评审、回滚和长期迭代
- 管理端支持仓库绑定、题库同步、版本浏览、候选人管理、邀约创建和结果回看
- 候选人端支持定向邀约与公开邀约，内置手机号短信验证码校验，可按当前状态自动进入验证、简历、答题或完成阶段
- 答题流程支持单题计时、整卷累计时长、超时自动跳题、自动交卷和跨会话重进控制
- 结果支持客观题、主观题和 `traits` 量表；可接入 LLM 做判卷、结构化评分和简历解析
- 系统同时暴露 REST API 和 `/mcp`，便于后台操作和自动化接入
- 项目知识沉淀在 `docs/` 与 `skills/`，便于团队维护，也适合 agent 协作

## 典型流程

1. 绑定一个测验仓库并执行同步。可以直接用示例仓库 [Scisaga/Shire](https://github.com/Scisaga/Shire) 体验完整流程。
2. 在后台创建候选人或开启公开邀约，系统会保存版本快照、资源路径和测验历史。
3. 候选人通过手机号短信验证码进入流程，再根据配置继续上传简历、开始答题或恢复未完成会话。
4. 系统按线性题流执行测验，并在提交后生成可回看的结果记录；如已配置 LLM，还可以补充自动评分和结构化分析。
5. 管理员可在后台查看结果、日志、任务和系统状态；需要自动化时，也可以通过 MCP 调用同一套能力。

## 系统形态

### 进程

- `API`：对外提供 `/api/*`、会话、SPA 入口、静态资源和测验资源路由
- `Worker`：执行异步任务，例如测验仓库同步、判卷等后台工作
- `Scheduler`：投递周期任务，例如指标同步

### 对外入口

- 管理端：`/admin`
- 候选人端：`/p/*`、`/t/*`、`/resume/*`、`/quiz/*`、`/done/*`、`/a/*`
- REST API：`/api/admin/*`、`/api/public/*`、`/api/system/*`
- MCP：`/mcp`

更细的架构说明见 [docs/architecture/overview.md](docs/architecture/overview.md)。

## 快速开始

### 前置依赖

- Python 3
- Node.js 与 npm
- PostgreSQL 16

仓库自带本地数据库编排：

```bash
docker compose up -d db
```

### 1. 复制环境变量

```bash
cp .env.example .env
```

本地开发可优先使用仓库默认数据库：

```text
postgresql+psycopg2://admin:pasword@127.0.0.1:5433/markdown_quiz
```

如果你本地已经用旧配置初始化过 `pgdata`，仅修改 `docker-compose.yml` 不会自动重建数据库账号；需要删除旧 volume 后再重新执行 `docker compose up -d db`。

### 2. 安装依赖

```bash
./scripts/dev/install-deps.sh
```

也可以按需分别安装：

```bash
./scripts/dev/install-deps.sh python
./scripts/dev/install-deps.sh node
```

### 3. 启动服务

```bash
./scripts/dev/devctl.sh start
```

常用命令：

```bash
./scripts/dev/devctl.sh stop
./scripts/dev/devctl.sh restart
./scripts/dev/devctl.sh status
./scripts/dev/devctl.sh logs
```

单进程调试：

```bash
./scripts/dev/run-api.sh
./scripts/dev/run-worker.sh
./scripts/dev/run-scheduler.sh
```

默认访问地址：

- 管理端：`http://127.0.0.1:8000/admin`
- 根路径：`http://127.0.0.1:8000/`
- 健康检查：`http://127.0.0.1:8000/api/system/health`
- MCP：`http://127.0.0.1:8000/mcp`
- 公开邀约示例：`http://127.0.0.1:8000/p/<token>`

## 关键配置

### 基础运行

- `DATABASE_URL`：PostgreSQL 连接串
- `APP_SECRET_KEY`：会话签名密钥
- `ADMIN_USERNAME` / `ADMIN_PASSWORD`：后台登录账号
- `APP_HOST` / `PORT`：服务监听地址和端口

### LLM 配置

- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_BASE_URL`

用于自动判卷、简历解析等依赖 OpenAI-compatible 接口的能力。

推荐服务商：

- 火山引擎方舟：当前 `.env.example` 默认就是按方舟接入编写，适合作为国内部署的优先选项。官方文档提供了 `OpenAI` SDK + `Responses API` 的直接调用方式，`base_url` 可配置为 `https://ark.cn-beijing.volces.com/api/v3`。
- OpenAI 官方：如果你希望直接对齐标准 `Responses API`，这是最直接的接入路径。本项目底层使用的是 OpenAI Python SDK，并通过 `responses.create(...)` 发起请求。

接入路径：

1. 在对应服务商控制台开通模型服务，获取 API Key，并确认可用的模型 ID。
2. 在 `.env` 中填写这 3 个变量：

```text
# 火山引擎方舟
OPENAI_API_KEY=<ARK_API_KEY>
OPENAI_MODEL=<你的模型 ID>
OPENAI_BASE_URL=https://ark.cn-beijing.volces.com/api/v3

# OpenAI 官方
OPENAI_API_KEY=<OPENAI_API_KEY>
OPENAI_MODEL=<你的模型 ID>
OPENAI_BASE_URL=https://api.openai.com/v1
```

3. 重启服务后，通过简历解析、自动判卷或后台系统状态页验证接入是否生效。
4. 如果要接入其它“OpenAI-compatible” 平台，先确认它支持 `Responses API`，而不是只兼容 `chat/completions`。

当前实现边界：

- 当前代码位于 `backend/md_quiz/services/llm_client.py`，实际调用的是 `client.responses.create(...)`。
- 这意味着“只兼容 Chat Completions、不兼容 Responses”的平台不能直接接入。
- 例如阿里云百炼官方文档明确提供 OpenAI 兼容接入，但当前公开示例主要围绕 `chat/completions`。如果要接入百炼，需要先确认目标模型与地域支持 `Responses API`；若不支持，则需要改造 LLM 客户端。这一点是根据官方文档和当前代码形态做出的判断。

官方资料：

- OpenAI Responses API：https://platform.openai.com/docs/api-reference/responses
- 火山引擎方舟 OpenAI SDK / Responses API：https://www.volcengine.com/docs/82379/1338552
- 阿里云百炼 OpenAI 兼容说明：https://help.aliyun.com/zh/model-studio/what-is-model-studio

### MCP 配置

- `MCP_ENABLED=1`
- `MCP_AUTH_TOKEN=<token>`
- `MCP_CORS_ALLOW_ORIGINS=...`

启用后可通过 `/mcp` 暴露远程 HTTP MCP 服务，后台说明页位于 `/admin/mcp`。

### 短信配置

- `ALIYUN_ACCESS_KEY_ID`
- `ALIYUN_ACCESS_KEY_SECRET`
- `ALIYUN_PNVS_SIGN_NAME`
- `ALIYUN_PNVS_TEMPLATE_CODE`

用于手机号验证码认证能力。

推荐服务商：

- 阿里云号码认证服务（短信认证服务）：这是当前项目唯一可以直接免改代码接入的短信认证方案。现有实现已经固定对接阿里云 DYPNS / PNVS OpenAPI，并调用 `SendSmsVerifyCode` 与 `CheckSmsVerifyCode` 完成验证码发送与校验。

接入路径：

1. 在阿里云开通号码认证服务中的“短信认证服务”。
2. 进入控制台配置短信签名与模板。阿里云官方文档推荐优先使用平台赠送的签名和模板，以减少审核和报备成本，并提升发送成功率。
3. 在 `.env` 中至少配置以下变量：

```text
ALIYUN_ACCESS_KEY_ID=<你的 AccessKey ID>
ALIYUN_ACCESS_KEY_SECRET=<你的 AccessKey Secret>
ALIYUN_PNVS_SIGN_NAME=<短信签名>
ALIYUN_PNVS_TEMPLATE_CODE=<短信模板 ID>
```

4. 如有需要，再补充 `ALIYUN_PNVS_REGION_ID`、`ALIYUN_PNVS_TEMPLATE_PARAM`、`ALIYUN_PNVS_VALID_TIME`、`ALIYUN_PNVS_CASE_AUTH_POLICY` 等高级参数。
5. 重启服务后，通过候选人验证流程或公开邀约验证流程触发短信发送与验证码校验。

当前实现边界：

- 当前短信接入代码位于 `backend/md_quiz/services/aliyun_dypns.py`。
- 如果要换成腾讯云、华为云或自建短信网关，现有代码不能只改环境变量直接切换，需要新增服务适配层。

官方资料：

- 阿里云短信认证服务说明：https://help.aliyun.com/zh/pnvs/user-guide/sms-authentication-service/
- 阿里云号码认证服务版本说明（含 `SendSmsVerifyCode` / `CheckSmsVerifyCode`）：https://help.aliyun.com/zh/pnvs/developer-reference/api-dypnsapi-2017-05-25-changeset

完整变量说明见 [docs/reference/configuration.md](docs/reference/configuration.md)。

## 使用约定

- 一套 `md-quiz` 实例只绑定一个测验仓库
- 首次绑定后，“立即同步”只会针对当前绑定仓库执行
- 更换仓库必须走显式“重新绑定”流程
- 运行时阈值和主题等配置保存在数据库，不以 `.env` 为唯一事实来源
- `/legacy/*` 只保留为兼容跳转入口，不作为正式使用路径

## 测试

```bash
./scripts/dev/test.sh -q
```

如果只想跑 FastAPI 相关测试：

```bash
./scripts/dev/test.sh tests/test_fastapi_app.py -q
```

## 参考文档

- [文档导航](docs/README.md)
- [架构总览](docs/architecture/overview.md)
- [运行拓扑](docs/architecture/runtime-topology.md)
- [配置项说明](docs/reference/configuration.md)
- [REST API 约定](docs/reference/api.md)
- [MCP 能力说明](docs/reference/mcp.md)
- [UI 主题覆盖](docs/ui/theme.md)
