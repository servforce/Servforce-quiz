---
name: python-web-refactor
description: Use this skill when refactoring, straightening, or reviewing a messy Python web service or API project, especially FastAPI-first and Flask-compatible cases involving module boundaries, entrypoint cleanup, configuration governance, async job separation, test strategy, documentation, and platform collaboration rules.
---

# Python Web Refactor

## 何时使用

在以下场景优先使用这个 skill：

- 重构混乱的 Python Web 项目
- 整理 FastAPI / Flask 服务的目录、入口和模块边界
- 收敛“路由里塞业务、脚本里塞流程、配置散落各处”的服务
- 设计 API / worker / scheduler 的职责拆分
- 统一配置治理、启动脚本、测试和文档入口
- 在改代码前先输出可执行的服务重构方案

## 核心原则

- 先读现有接口说明、启动脚本、目录和入口代码，再下结论
- 先区分事实/证据与推断/建议，不凭经验猜项目行为
- 先把进程边界和模块职责拉直，再谈局部实现优化
- 默认优先简单、可验证、可迁移的重构路径，不先引入复杂框架
- 若项目没有异步重任务，不强推 `worker / scheduler`
- 方案输出要覆盖代码结构，也覆盖配置、测试、文档和协作治理

## 工作流

1. 先建立事实表
   - 读取接口文档、README、启动脚本、配置文件、主入口、测试目录
   - 列出当前进程形态、目录职责、配置来源、运行方式、测试形态
2. 判断主问题属于哪一类
   - 单进程耦合：请求线程里直接跑重任务、脚本和 API 混在一起
   - 边界混乱：`router/model/script` 混写业务，入口和配置分散
3. 先收敛目标形态
   - 需要几个进程
   - 目录如何分层
   - 配置如何分级
   - 接口、测试、文档各放在哪里
4. 再输出分阶段重构方案
   - 先入口和配置，再模块分层，再异步边界，再测试和文档
   - 禁止一上来做“大搬家式”改造但不给迁移顺序
5. 每一步都明确
   - 事实依据是什么
   - 为什么这样拆
   - 哪些是当前必须改，哪些可以后置

## 无文档项目处理流程

如果目标项目连 README、接口说明、架构说明都没有，不要先进入“重构实施”，先进入“事实建档”。

1. 先找运行事实
   - 主入口：`main.py`、`app.py`、`wsgi.py`、`asgi.py`、`manage.py`
   - 依赖与框架：`requirements.txt`、`pyproject.toml`
   - 启动与部署：`Dockerfile`、`docker-compose.yml`、`scripts/`、CI 配置
   - 配置来源：`.env.example`、配置类、硬编码常量、启动参数
   - 对外接口：路由注册、OpenAPI、测试、日志、调用脚本
2. 先补最小事实文档
   - 当前服务怎么启动
   - 主入口在哪里
   - 当前有哪些进程或模块
   - 配置从哪里来
   - 当前核心接口或任务链路是什么
3. 先做特征化验证
   - 先把服务跑起来
   - 记录关键接口的输入输出、状态码、日志和落库行为
   - 补最小集成测试，优先覆盖主链路
   - 目标是保住现状行为，不是证明当前实现合理
4. 再进入分阶段重构
   - 先收敛入口和启动方式
   - 再收敛配置来源
   - 再抽服务层和模块边界
   - 只有确认存在真实需求时，再拆异步执行面
   - 最后补完整文档

补充要求：

- 没有文档不等于没有依据，代码、脚本、配置、日志和运行结果本身就是依据
- 禁止在“无文档”状态下凭经验直接定义接口行为和目录结构
- 若关键行为无法从代码或运行结果确认，先标注未知项，再决定是否需要人工澄清

## Python 虚拟环境处理

在重构 Python Web 项目前，默认先把本地 Python 运行环境收敛清楚；没有可复现的 `venv`，后续的启动、测试和依赖判断都不可靠。

1. 先确认 Python 与依赖入口
   - 优先看 `requirements.txt`、`requirements-dev.txt`、`pyproject.toml`
   - 确认项目要求的 Python 版本、安装入口和依赖分组
2. 默认在项目根目录创建 `.venv`
   - 推荐命令：`python3 -m venv .venv`
   - 若项目明确要求其他目录名，再遵循项目既有约定
3. 激活后升级基础工具
   - `source .venv/bin/activate`
   - `python -m pip install --upgrade pip`
4. 按项目真实依赖入口安装
   - 若是 `requirements.txt`：`python -m pip install -r requirements.txt`
   - 若是带后端子目录的项目，按真实路径安装，例如 `python -m pip install -r backend/requirements.txt`
   - 若是 `pyproject.toml` 项目，先读其构建与依赖声明，再决定用 `pip install -e .`、`pip install .` 或项目已有工具
5. 把 `venv` 也纳入事实表
   - 当前 Python 版本
   - 当前依赖安装入口
   - 是否已有 `.venv`
   - 是否需要额外系统依赖才能创建或补全环境

补充要求：

- 优先使用项目本地 `.venv`，不要默认把依赖装到系统 Python
- 先根据项目已有依赖文件决定安装命令，不要凭经验乱装包
- 若 `venv` 创建失败，应先记录缺失条件，例如 `python3-venv`、`ensurepip`、编译依赖或系统库
- 若仓库已有统一启动脚本，应把脚本中对 `.venv` 的使用方式一并纳入重构方案

## 目标结构准则

- 入口装配层独立：主入口只负责创建 app、挂载 router、初始化依赖
- 路由层只做协议适配：参数解析、鉴权、响应组装，不承载核心业务
- 服务层承载业务编排：把跨模型、跨依赖的流程从路由和脚本里抽出
- 异步执行层独立：只有真实重任务时才引入 job/worker/scheduler
- 工具脚本独立：开发脚本、迁移脚本、运维脚本不要混到业务模块
- 配置分层清晰：环境变量负责进程级配置，运行时配置负责行为开关
- 文档有入口：愿景、架构、接口、配置、运维说明分开维护
- 测试围绕链路：优先真实集成，再补必要的局部单测

## 输出要求

- 输出方案时优先给一套支配性的重构路径，不堆非 dominant 方案
- 若保留次优方案，必须写清适用边界和保留原因
- 对外给结论时，先写“事实/证据”，再写“推断/建议”
- 若当前仓库要求方案阶段同步产出 issue / 任务单，按仓库规则执行
- 实施时默认优先小步重构：入口、配置、模块边界、测试、文档依次收敛

## 验收清单

- 入口是否单一且可运行
- 路由层是否只做协议适配
- 业务逻辑是否从 `router/model/script` 拉回服务层
- 配置是否可枚举、可分层、可说明
- 重任务是否已脱离请求线程
- 没有异步需求时，是否避免过度设计
- 测试是否围绕真实运行链路
- 文档是否能支撑后续维护与交接

## 参考资料

- 项目内可迁移模式： [references/raelyn-patterns.md](references/raelyn-patterns.md)
- 跨项目检查清单： [references/refactor-checklist.md](references/refactor-checklist.md)
- 方案输出模板： [references/migration-template.md](references/migration-template.md)
