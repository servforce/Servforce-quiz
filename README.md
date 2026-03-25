# Markdown Quiz

`md-quiz` 当前保留旧的 `Flask + Jinja` 后台页面作为正式管理端入口，同时引入 `FastAPI + Worker + Scheduler` 来承接新的 API、任务与进程边界。

当前仓库的主实现分为两部分：

- `backend/md_quiz/`：FastAPI API、Worker、Scheduler、运行时配置与任务存储
- `app.py` + `web/` + `templates/` + `static/`：正式使用中的后台与候选人端页面

## 新架构概览

### 进程形态

- `API`：FastAPI 应用，负责 `/api/*`、会话、静态资源挂载与旧 Flask 页面挂载
- `Worker`：后台任务执行器，轮询 job store 并处理任务
- `Scheduler`：定时任务投递器，负责自动投递指标同步等周期任务

### 目录

```text
backend/
  md_quiz/
    api/               FastAPI 路由层
    services/          业务编排
    storage/           轻量存储层（第一阶段先落 JSON store）
    models/            Pydantic 模型
    app.py             FastAPI 装配
    main.py            API 入口
    worker.py          Worker 入口
    scheduler.py       Scheduler 入口
web/
  ...                  旧 Flask 管理端与候选人端实现
```

### 后台入口

- 默认入口：`http://127.0.0.1:8000/admin`
- 根路径：`http://127.0.0.1:8000/` 由旧 Flask 应用按登录态跳转到后台首页或登录页
- 兼容跳转：`http://127.0.0.1:8000/legacy/admin` 会重定向到 `http://127.0.0.1:8000/admin`

## 前端约束

- 当前管理端与候选人端继续使用 `templates/` + `static/`
- 当前前端基础配色 **保留**：蓝色 + 绿色，不照搬参考项目 `raelyn` 的深色主题

## 本地启动

### 1. Python 环境

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt pytest
```

### 2. 启动新系统

```bash
scripts/dev/devctl.sh start
```

常用命令：

```bash
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

- 默认后台入口：`http://127.0.0.1:8000/admin`
- 根路径：`http://127.0.0.1:8000/`
- 系统健康检查：`http://127.0.0.1:8000/api/system/health`
- 兼容跳转：`http://127.0.0.1:8000/legacy/admin`

## 当前阶段说明

这轮已经完成的是：

- 新 FastAPI API 入口
- Worker / Scheduler 入口
- 运行时配置与任务系统的轻量存储边界
- 统一开发脚本
- 新文档骨架与最小测试

这轮**还没有**完全迁完的是：

- 试卷、候选人、邀约、答题、判卷、归档的真实业务 API
- 旧后台内部代码结构的进一步收敛
- 旧 `web/`、`templates/`、`static/` 与新后端服务边界的继续整理

也就是说，仓库当前是“旧后台继续承载业务，新后端负责 API / 任务 / 进程边界”的状态。

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
