# 项目结构（概览）

```
markdown_quiz/
  app.py                  # 兼容入口（直接运行时启动 Flask）
  core/settings.py        # 配置装载与日志初始化
  web/app_factory.py      # Flask 应用工厂
  web/routes/             # shared/admin/public 路由装配与分域模块
  web/runtime_setup.py    # 启动初始化、数据库校验、后台线程
  web/support/            # 按领域拆分的共享业务/工具函数
  web/runtime_support.py  # 兼容聚合导出
  config.py               # 兼容配置导出
  db.py                   # PostgreSQL：candidate / exam_paper / assignment_record / exam_definition / exam_asset / exam_archive / runtime_*
  storage/json_store.py   # 运行目录准备
  qml/                    # QML Markdown 解析
  services/               # 业务服务：分发/判分/LLM 调用
  templates/              # Jinja2 模板（前端页面）
  static/                 # 静态资源（全局 UI 样式在 static/ui.css）
  storage/                # 运行时数据（试卷/assignment/二维码等）
  scripts/dev/            # 本地运行/测试脚本
  docs/                   # 学习与文档
```

关键数据落地位置：
- 试卷：PostgreSQL 表 `exam_definition`
- 分发记录：PostgreSQL 表 `assignment_record`
- 归档快照：PostgreSQL 表 `exam_archive`
- 试卷图片资源：PostgreSQL 表 `exam_asset`
- 候选人与考试状态：PostgreSQL 表 `candidate` / `exam_paper`
- 系统状态配置与每日指标：PostgreSQL 表 `runtime_kv` / `runtime_daily_metric`
- 日志与告警：PostgreSQL 表 `system_log`
