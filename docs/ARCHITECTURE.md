# Architecture

## 当前入口

- 兼容入口：`app.py`
- 应用工厂：`web/app_factory.py`
- 启动脚本：`scripts/dev/run-web.sh`
- 测试脚本：`scripts/dev/test.sh`

## 分层边界

- `core/`
  - 配置装载与日志初始化
- `storage/`
  - 运行目录准备
- `web/app_factory.py`
  - Flask 应用装配
- `web/runtime_setup.py`
  - 启动期初始化、数据库校验、后台线程启动
- `web/routes/`
  - `shared.py`：模板过滤器和公共路由
  - `admin.py`：管理端路由装配
  - `public.py`：候选人端路由装配
- `web/support/`
  - `validation.py`：校验与通用工具
  - `system_status.py`：系统状态与日志上下文
  - `exams.py`：试卷/公开邀约相关流程
  - `runtime_jobs.py`：判卷、归档、状态同步
- `web/runtime_support.py`
  - 兼容聚合导出，避免旧导入路径立刻失效
- `services/`
  - 业务服务与外部依赖

## 这次重构的目标

- `app.py` 不再承载 6000 行入口与路由混写逻辑
- 配置读取收敛到 `core/settings.py`
- JSON 存储职责收敛到 `storage/json_store.py`
- Flask 装配、启动初始化、管理端路由、候选人端路由分开维护
- 保留原有 `app` 模块上的辅助函数导出，避免测试和旧调用方式直接失效

## 当前稳定边界

- 启动流程只负责目录准备、数据库初始化和后台线程启动
- 运行期业务数据统一进入 PostgreSQL：`exam_definition`、`assignment_record`、`exam_paper`、`exam_asset`、`exam_archive`、`runtime_kv`、`runtime_daily_metric`
- 判卷与自动收卷仍是进程内后台线程，尚未拆成独立 worker
