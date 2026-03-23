# START HERE

如果你要学习这个项目，建议按下面顺序阅读：

1) `README.md`
   - 了解系统做什么、怎么启动、环境变量怎么配。

2) `web/app_factory.py`
   - 应用装配入口：创建 Flask app，注册启动初始化和路由模块。

3) `web/runtime_setup.py`
   - 启动期逻辑：目录准备、数据库初始化、后台线程启动。

4) `web/routes/admin.py` + `web/routes/public.py`
   - 管理端和候选人端的 HTTP 装配层。
   - 重点关注：
     - 管理端：`/admin`、`/admin/candidates`、`/admin/assignments`
     - 候选人端：`/t/<token>`、`/exam/<token>`、`/api/public/submit/<token>`

5) `web/support/`
   - 当前共享业务与工具函数的主目录：
     - `validation.py`
     - `system_status.py`
     - `exams.py`
     - `runtime_jobs.py`

6) `db.py`
   - 只负责 PostgreSQL 访问与表结构初始化。

7) `services/`
   - `services/assignment_service.py`：token/assignment 的数据库读写与并发锁
   - `services/grading_service.py`：判分逻辑（客观题 + 简答题）
   - `services/llm_client.py`：大模型调用（OpenAI-compatible /responses）

8) `qml/parser.py`
   - QML Markdown 解析，把试卷转成结构化对象，随后写入 PostgreSQL。

9) `templates/` + `static/ui.css`
   - 页面结构与 UI 风格（统一玻璃拟态风格）。
