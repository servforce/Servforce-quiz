# Markdown Quiz

`md-quiz` 已收敛为 `FastAPI + Worker + Scheduler` 单栈服务：

- 管理端：`/admin*` Alpine SPA
- 候选人端：`/p/*`、`/t/*`、`/resume/*`、`/exam/*`、`/done/*`、`/a/*` Alpine SPA
- 数据接口：统一走 `/api/admin/*`、`/api/public/*`、`/api/system/*`
- Python 应用代码：统一放在 `backend/md_quiz/`

旧 Flask、Jinja 页面和 `a2wsgi` 桥接不再是运行时依赖；`/legacy/*` 仅保留 307 跳转兼容面。

## 架构概览

### 进程

- `API`：FastAPI，负责会话、SPA 入口、业务 API、静态资源与试卷资源路由
- `Worker`：后台任务执行器，处理试卷同步、判卷等异步任务
- `Scheduler`：周期任务投递器，负责指标同步等定时工作

### 目录

```text
backend/
  md_quiz/
    api/               FastAPI 路由层
    services/          业务编排与运行时 helper
    storage/           PostgreSQL 持久化边界
    parsers/           QML 等解析器
    models/            Pydantic 模型
    app.py             FastAPI 装配入口
    main.py            API 入口
    worker.py          Worker 入口
    scheduler.py       Scheduler 入口
static/
  admin/              管理端 SPA 壳
  public/             候选人端 SPA 壳
  assets/css/         Tailwind v4 输入源
```

## 本地启动

### 1. Python 环境

```bash
scripts/dev/install-deps.sh python
```

推荐本地数据库连接串：

```text
postgresql+psycopg2://postgres:admin@127.0.0.1:5433/markdown_quiz
```

复制环境变量模板：

```bash
cp .env.example .env
```

### 2. 前端静态资源构建

```bash
scripts/dev/install-deps.sh node
cd static && npm run build:css
```

### 3. 启动服务

```bash
scripts/dev/install-deps.sh
scripts/dev/devctl.sh start
```

常用命令：

```bash
scripts/dev/install-deps.sh
scripts/dev/install-deps.sh python
scripts/dev/install-deps.sh node
scripts/dev/devctl.sh start
scripts/dev/devctl.sh stop
scripts/dev/devctl.sh restart
scripts/dev/devctl.sh status
scripts/dev/devctl.sh logs
```

也可以分别启动：

```bash
scripts/dev/run-api.sh
scripts/dev/run-worker.sh
scripts/dev/run-scheduler.sh
```

默认地址：

- 管理端：`http://127.0.0.1:8000/admin`
- 根路径：`http://127.0.0.1:8000/`
- 候选人端公开邀约：`http://127.0.0.1:8000/p/<token>`
- 系统健康检查：`http://127.0.0.1:8000/api/system/health`
- 兼容跳转：`http://127.0.0.1:8000/legacy/admin`

## 测试

```bash
scripts/dev/test.sh tests/test_fastapi_app.py -q
scripts/dev/test.sh -q
```

## 参考文档

- [文档导航](docs/README.md)
- [架构总览](docs/architecture/overview.md)
- [运行拓扑](docs/architecture/runtime-topology.md)
- [配置项说明](docs/reference/configuration.md)
- [REST API 约定](docs/reference/api.md)
- [UI 主题覆盖](docs/ui/theme.md)
