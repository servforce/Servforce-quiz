# START HERE

如果你要学习这个项目，建议按下面顺序阅读：

1) `README.md`
   - 了解系统做什么、怎么启动、环境变量怎么配。

2) `app.py`
   - 项目入口：所有路由都在这里串起来。
   - 重点关注：
     - 管理端：`/admin`、`/admin/candidates`、`/admin/assignments`
     - 候选人端：`/t/<token>`、`/a/<token>`、`/api/public/submit/<token>`

3) `db.py`
   - 只负责候选人表（PostgreSQL）。
   - 你可以从这里理解候选人状态：`send` → `verified` → `finished`。

4) `services/`
   - `services/assignment_service.py`：token/assignment 文件（JSON）读写
   - `services/grading_service.py`：判分逻辑（客观题 + 简答题）
- `services/llm_client.py`：大模型调用（豆包 /responses）

5) `qml/parser.py`
   - QML Markdown 解析，把试卷转成结构化 JSON（`spec.json` / `public.json`）。

6) `templates/` + `static/ui.css`
   - 页面结构与 UI 风格（统一玻璃拟态风格）。
