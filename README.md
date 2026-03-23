# Markdown Quiz

`md-quiz` 正在从旧的 `Flask + Jinja` 单体后台，重构到新的 `FastAPI + API / Worker / Scheduler + ui/` 工作区。

当前仓库里两套实现并存：

- **新系统**：`backend/md_quiz/` + `ui/` + `scripts/dev/run-*.sh`
- **旧系统**：`app.py` + `web/` + `templates/` + `static/`

这次重构的目标不是继续在旧模板上修补，而是把后端边界、前端工作区、任务系统、脚本和文档全部拉直到新形态；同时通过 `legacy bridge` 暂时保留旧后台，避免功能瞬间中断。

## 新架构概览

### 进程形态

- `API`：FastAPI 应用，负责 `/api/*`、会话、静态资源挂载、新 UI 壳层
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
ui/
  src/                 前端源码
  templates/           前端入口模板
  scripts/build-ui.cjs UI 构建脚本
static/
  app/                 ui/ 的构建产物
web/
  ...                  旧 Flask 单体实现（通过 legacy bridge 暂时保留）
```

### Legacy Bridge

新 API 默认会把旧 Flask 应用挂到 `/legacy`：

- 新 UI：`http://127.0.0.1:8000/`
- 旧后台：`http://127.0.0.1:8000/legacy/admin`

这样做的原因很简单：

- 新骨架可以独立启动
- 旧功能还能继续访问
- 后续可以按领域逐页迁走，而不是一次性大爆炸迁移

## 主题与前端约束

- 当前前端基础配色 **保留**：蓝色 + 绿色，不照搬参考项目 `raelyn` 的深色主题
- 新 UI 源码位于 `ui/`
- 构建产物输出到 `static/app/`
- 运行时不依赖 Node，只读取已构建好的静态文件

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
scripts/dev/devctl.sh build-ui
```

也可以分别启动：

```bash
scripts/dev/run-api.sh
scripts/dev/run-worker.sh
scripts/dev/run-scheduler.sh
```

默认地址：

- 新 UI：`http://127.0.0.1:8000/`
- 系统健康检查：`http://127.0.0.1:8000/api/system/health`
- 旧后台桥接：`http://127.0.0.1:8000/legacy/admin`

### 3. 构建 UI

```bash
scripts/dev/build-ui.sh
```

构建完成后会生成：

- `static/app/index.html`
- `static/app/assets/app.css`
- `static/app/assets/app.js`
- `static/app/views/*.html`

## 当前阶段说明

这轮已经完成的是：

- 新 FastAPI API 入口
- Worker / Scheduler 入口
- 运行时配置与任务系统的轻量存储边界
- `ui/` 工作区与构建脚本
- 统一开发脚本
- 新文档骨架与最小测试

这轮**还没有**完全迁完的是：

- 试卷、候选人、邀约、答题、判卷、归档的真实业务 API
- 旧后台页面到新 UI 的整页迁移
- 旧 `web/` / `templates/` / `static/` 的彻底删除

也就是说，仓库已经进入“新系统可运行，旧系统可桥接，后续按领域迁移”的状态。

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
- [前端工作区说明](docs/ui/frontend-workspace.md)
