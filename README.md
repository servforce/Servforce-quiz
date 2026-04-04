# MD Quiz

`md-quiz` 是面向招聘测评、内部考核、培训后测试、访谈评估等场景的在线测评 / 在线笔试系统。它关注的是结构化评估、答题执行、自动处理、结果留档与回看，不是课程分发、教学管理一类 LMS。

当前项目已经收敛为一套以 `FastAPI + Worker + Scheduler` 为核心的三进程服务，管理端与候选人端都由 Alpine SPA 承载，并支持测验仓库同步、在线答题、自动判卷、系统监控与 MCP 接入。

<table width="100%">
  <tr>
    <td align="center" valign="top" width="37%">
      <img
        src="img/README-1775326878169.png"
        alt="登录界面"
        style="width: 100%; height: 240px; object-fit: cover; object-position: top center;"
      />
      <div>登录界面</div>
    </td>
    <td align="center" valign="top" width="37%">
      <img
        src="img/README-1775326831253.png"
        alt="试卷列表界面"
        style="width: 100%; height: 240px; object-fit: cover; object-position: top center;"
      />
      <div>试卷列表界面</div>
    </td>
    <td align="center" valign="top" width="26%" rowspan="2">
      <img
        src="img/README-1775327085286.png"
        alt="答题界面"
        style="height: 540px; width: auto; max-width: 100%; object-fit: contain;"
      />
      <div>答题界面</div>
    </td>
  </tr>
  <tr>
    <td align="center" valign="top" width="28%">
      <img
        src="img/README-1775326951988.png"
        alt="试卷浏览界面"
        style="width: 100%; height: 240px; object-fit: cover; object-position: top center;"
      />
      <div>试卷浏览界面</div>
    </td>
    <td align="center" valign="top" width="28%">
      <img
        src="img/README-1775327020945.png"
        alt="邀约界面"
        style="width: 100%; height: 240px; object-fit: cover; object-position: top center;"
      />
      <div>邀约界面</div>
    </td>
  </tr>
</table>

## 适用场景

- 招聘筛选与在线笔试
- 内部周期性考核
- 培训结课测试
- 访谈式评估
- 专项能力盘点与阶段性抽检

## 功能介绍

### 测验管理

- 从 Git 仓库同步测验定义、资源文件和版本快照
- 管理测验列表、版本历史、展示快照与资源访问
- 支持为测验开启或关闭公开邀约
- 支持公开邀约访问链接与二维码
- 采用“单实例单仓库”绑定模型，首次绑定后后续同步都针对当前绑定仓库
- 支持重新绑定仓库；重新绑定会清空当前实例中的测验、版本、邀约与答题归档数据，但保留候选人与简历

### 候选人与邀约

- 管理候选人基础档案与答题记录
- 支持手动创建候选人
- 支持创建定向答题邀约
- 支持公开邀约入口，候选人可通过公开 token 进入答题流程
- 邀约支持访问链接、二维码、有效起止日期等控制
- 邀约支持最小交卷时间、手机号验证、最大验证次数等约束
- 邀约支持 `ignore_timing` 模式，可关闭单题倒计时、超时自动跳题和整卷超时自动交卷

### 身份验证与入场

- 同时支持主动邀约与公开邀约两种进入路径
- 可按配置要求手机号验证码验证
- 公开邀约场景下支持姓名与手机号校验后建档
- 候选人端会根据当前状态自动进入验证、简历上传、答题或完成页

### 简历处理

- 支持通过简历上传直接创建或更新候选人
- 支持下载已上传简历
- 支持重新上传简历并重新解析
- 支持结构化简历解析结果查看
- 公开邀约下，验证码通过但未建档的用户可先上传简历再进入答题

### 在线答题

- 候选人端按线性题流执行作答
- 支持单题计时与整卷累计时长
- 支持超时自动跳题与自动交卷
- 支持跨会话重进计数与限制
- 支持公开测验快照展示，向候选人隐藏评分标准
- 支持无倒计时模式，适用于不需要时控的测评流程

### 判卷与结果

- 支持客观题与主观题混合测验
- 支持基于 LLM 的自动判卷能力
- 支持量表 / traits 类结果输出
- 支持结果归档、回放查看与分数展示
- 支持管理员补充评价与结果复核

### 运行与运维

- 提供 `API / Worker / Scheduler` 三进程拆分
- 支持异步任务队列、仓库同步任务和周期任务
- 提供系统日志、系统状态摘要和进程心跳
- 提供健康检查与系统 bootstrap 接口
- 运行时配置写入数据库，可由后台管理接口调整

### 扩展能力

- 提供远程 HTTP MCP 接口，便于智能体或自动化流程调用后台能力
- 支持 OpenAI-compatible LLM 接入
- 支持阿里云短信认证接入

## 项目特性

- 仓库驱动的测验内容管理：题目内容、资源和版本来源于外部 quiz Git 仓库，而不是直接散落在管理后台里
- 运行时配置入库：系统阈值和部分行为配置保存在数据库，不依赖纯环境变量硬编码
- 当前统一技术形态：后端为 `FastAPI`，前端为 `Alpine SPA`，不再依赖旧的 `Flask + Jinja` 页面渲染
- 不只是静态问卷发布：系统同时具备同步、答题、判卷、监控和自动化接入能力

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
postgresql+psycopg2://postgres:admin@127.0.0.1:5433/markdown_quiz
```

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
