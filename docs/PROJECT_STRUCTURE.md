# 项目结构（概览）

```
markdown_quiz/
  app.py                  # Flask 入口与路由
  config.py               # 环境变量/配置
  db.py                   # PostgreSQL：候选人表（唯一使用数据库的部分）
  qml/                    # QML Markdown 解析
  services/               # 业务服务：分发/判分/LLM 调用
  templates/              # Jinja2 模板（前端页面）
  static/                 # 静态资源（全局 UI 样式在 static/ui.css）
  storage/                # 运行时数据（试卷/assignment/二维码等）
  scripts/                # 辅助脚本（例如 LLM 连通性测试）
  docs/                   # 学习与文档
```

关键数据落地位置：
- 试卷：`storage/exams/<exam_key>/spec.json`（含答案/rubric）与 `public.json`（候选人可见）
- 分发记录：`storage/assignments/<token>.json`
- 二维码：`storage/qr/<token>.png`
- 候选人列表：PostgreSQL 表 `candidate`

