# Servforce Quiz（Flask + PostgreSQL(候选人表) + JSON）

## 从哪里开始看（学习路线）
1) `README.md`：先了解运行方式和整体流程  
2) `app.py`：路由入口（管理员端/候选人端）与业务流程串联  
3) `db.py`：候选人表（PostgreSQL）与状态流转  
4) `services/`：
   - `services/assignment_service.py`：token 分发、assignment JSON 存取
   - `services/grading_service.py`：判卷（客观题 + 简答题调用大模型）
- `services/llm_client.py`：大模型调用封装（豆包 /responses）
5) `qml/`：QML Markdown 解析（`qml/parser.py`）  
6) `templates/` + `static/ui.css`：前端页面与统一 UI 风格

## 运行
1) 安装依赖：`pip install -r requirements.txt`
   2) 配置环境变量（可写到 `.env`）：
    - `DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/dbname`
    - `ADMIN_USERNAME=admin` / `ADMIN_PASSWORD=admin`
    - 简答题大模型（可选）：
      - 豆包（火山方舟 / OpenAI 兼容 HTTP）：
        - `DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3`
        - `DOUBAO_API_KEY=...`（或 `ARK_API_KEY=...`）
        - `DOUBAO_MODEL=...`（建议填火山方舟的 endpoint id 或模型名）
        - `LLM_RESPONSE_FORMAT_JSON=0`
3) 启动：`python app.py`
4) 打开后台：`http://127.0.0.1:5000/admin`

可用 `python scripts/llm_smoke_test.py` 快速验证大模型配置。

## 使用流程（MVP）
- 后台上传 QML 格式 Markdown（参考 `qml.md` 的示例）。
- 后台创建候选人（写入 PostgreSQL 的 `candidate` 表）。
- 后台选择试卷 + 候选人生成链接/二维码（候选人状态置为 `send`）。
- 候选人打开链接输入姓名/手机号验证（通过后状态 `verified`），进入作答页。
- 提交/超时交卷（状态 `finished`），系统自动判分并回写候选人表的 `score/duration_seconds`。
