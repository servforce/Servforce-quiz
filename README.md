# Markdown Quiz

一个面向招聘/测评场景的在线考试系统，基于 Flask + PostgreSQL，支持：

- 后台上传 Markdown 试卷并解析为结构化题目
- 候选人管理、邀请分发、二维码/链接投递
- 姓名 + 手机号校验，支持阿里云短信验证码二次验证
- 在线答题、限时考试、最短交卷时长限制
- 客观题自动判分，简答题可接入豆包大模型判分
- 简历上传、OCR/文本提取、简历结构化解析
- 管理后台查看结果、答卷快照、系统日志和资源消耗

## 1. 适合谁先看

项目顺序：

1. `README.md`：先把启动方式和整体流程跑通
2. `app.py`：唯一主入口，路由和业务流程都在这里
3. `db.py`：数据库表结构、候选人/考试记录/系统日志
4. `services/`：分发、判分、LLM、简历解析、短信能力
5. `qml/parser.py`：试卷 Markdown 解析规则
6. `templates/` 和 `static/`：后台与考生页面

## 2. 项目结构

```text
markdown_quiz/
  app.py                  Flask 应用入口
  config.py               环境变量与全局配置
  db.py                   PostgreSQL 初始化与数据访问
  qml/                    QML Markdown 试卷解析
  services/               业务服务层
  templates/              Jinja2 页面模板
  static/                 前端静态资源
  storage/                运行时文件数据
  scripts/                辅助脚本
  tests/                  单元测试
  docs/                   补充设计文档
```

关键落盘位置：

- `storage/exams/<exam_key>/spec.json`：完整试卷，包含答案和评分规则
- `storage/exams/<exam_key>/public.json`：考生可见试卷，不包含答案
- `storage/exams/<exam_key>/assets/`：试卷引用的图片等资源
- `storage/assignments/<token>.json`：一次分发/作答记录
- `storage/qr/<token>.png`：邀请二维码
- `storage/archives/`：交卷后的归档快照

数据库里主要有三类数据：

- `candidate`：候选人基础信息和简历
- `exam_paper`：候选人与某次试卷分发/考试记录
- `system_log`：后台操作、考试流程、LLM/短信相关日志

## 3. 核心流程

管理员侧：

1. 登录后台 `/admin`
2. 上传 QML 格式 Markdown 试卷
3. 创建候选人，或者直接上传简历生成候选人
4. 选择试卷并创建分发记录，生成考试链接和二维码
5. 查看作答结果、判分结果、归档快照、系统日志

候选人侧：

1. 打开带 token 的邀请链接 `/t/<token>`
2. 输入姓名和手机号进行验证
3. 如果开启短信验证，输入验证码
4. 某些流程下需要先上传简历
5. 进入答题页 `/a/<token>` 作答并提交
6. 系统自动判分并在后台展示结果

## 4. 本地快速启动

### 4.1 环境要求

- Python 3.11+，建议使用虚拟环境
- PostgreSQL 16+，或者直接使用项目自带的 `docker-compose.yml`
- Windows 环境下如果要做 OCR，需要额外安装 Tesseract

### 4.2 安装依赖

```bash
pip install -r requirements.txt
```

### 4.3 启动 PostgreSQL

如果本机没有数据库，直接运行：

```bash
docker compose up -d
```

默认数据库配置：

- 数据库：`markdown_quiz`
- 用户名：`postgres`
- 密码：`postgres`
- 端口：`5432`

### 4.4 配置环境变量

复制一份环境变量模板：

```bash
copy .env.example .env
```

至少要确认这几个配置：

```env
DATABASE_URL=postgresql+psycopg2://postgres:password@127.0.0.1:5432/markdown_quiz
APP_SECRET_KEY=change-me
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin
PORT=5000
```

说明：

- `DATABASE_URL` 必填，否则应用会默认连本地 PostgreSQL
- `APP_SECRET_KEY` 建议改掉，避免 token/会话使用默认值
- `ADMIN_USERNAME` / `ADMIN_PASSWORD` 不填时默认都是 `admin`

### 4.5 启动项目

```bash
python app.py
```

启动后访问：

- 管理后台：`http://127.0.0.1:5000/admin`

应用启动时会自动执行数据库初始化和必要的表结构升级。

## 5. 环境变量说明

### 5.1 基础配置

- `DATABASE_URL`：PostgreSQL 连接串
- `APP_SECRET_KEY`：Flask 会话与签名密钥
- `ADMIN_USERNAME` / `ADMIN_PASSWORD`：后台登录账号
- `PORT`：服务端口，默认 `5000`
- `STORAGE_DIR`：运行时文件目录，默认是项目下的 `storage`
- `LOG_LEVEL`：日志级别

### 5.2 LLM 判分与简历解析

项目当前只封装了豆包/火山方舟兼容接口：

- `DOUBAO_API_KEY` 或 `ARK_API_KEY`
- `DOUBAO_MODEL`
- `DOUBAO_BASE_URL`
- `LLM_RESPONSE_FORMAT_JSON`
- `LLM_RETRY_MAX`
- `LLM_RETRY_BACKOFF`
- `LLM_TIMEOUT_STRUCTURED`

验证 LLM 是否通：

```bash
python scripts/llm_smoke_test.py
```

如果不配置 LLM：

- 客观题仍可正常判分
- 简答题相关的大模型判分能力不可用
- 简历结构化解析能力会受限

### 5.3 OCR 与简历处理

- `TESSERACT_CMD`：Tesseract 可执行文件路径
- `RESUME_OCR_LANG`：默认 `chi_sim+eng`
- `RESUME_OCR_ZOOM`
- `RESUME_PDF_MAX_PAGES`
- `RESUME_PDF_OCR`
- `RESUME_PDF_MIN_TEXT_CHARS`

支持的简历文件类型：

- `pdf`
- `docx`

### 5.4 短信验证

如果要启用阿里云短信验证码：

- `ALIYUN_ACCESS_KEY_ID`
- `ALIYUN_ACCESS_KEY_SECRET`
- `ALIYUN_DYPNS_ENDPOINT`
- `ALIYUN_SMS_SIGN_NAME`
- `ALIYUN_SMS_TEMPLATE_CODE`
- `ALIYUN_SMS_TEMPLATE_PARAM`

不配置时，短信相关验证流程无法正常工作。

## 6. 试卷格式

试卷使用 QML 风格 Markdown，解析逻辑在 `qml/parser.py`。

支持题型：

- `single`：单选题
- `multiple`：多选题
- `short`：简答题

一个最小示例：

```md
---
title: Python 基础测试
---

## Q1 [single] (5)
Python 中用于定义函数的关键字是？
- A) func
- B*) def
- C) function

## Q2 [short] {max=10}
请简述列表和元组的区别。
[rubric]
回答出可变性、使用场景、性能差异等要点即可得分。
[/rubric]
```

可以直接参考：

- `qml.md`
- `examples/exam-demo.md`

## 7. 管理后台功能

后台主要页面：

- `/admin`：首页仪表盘
- `/admin/exams`：试卷管理
- `/admin/candidates`：候选人管理
- `/admin/assignments`：分发与考试记录
- `/admin/logs`：系统日志
- `/admin/status`：系统状态与资源使用

已实现的典型能力：

- 试卷上传、编辑、删除、预览
- AI 辅助生成试卷
- 创建公开邀请链接
- 候选人手动创建、简历上传创建、编辑、删除
- 简历下载与重新解析
- 分发考试并配置时间限制、通过阈值、验证次数
- 查看某次考试详情、结果、归档快照

## 8. 测试

运行全部测试：

```bash
pytest
```

当前测试主要覆盖：

- QML/Markdown 解析
- 简历提取与分段
- 判分逻辑
- 最短交卷时长
- 候选人查询条件
- 静态资源解析

## 9. 常见问题

### 9.1 项目启动后数据库报错

优先检查：

- PostgreSQL 是否真的启动了
- `DATABASE_URL` 是否指向正确数据库
- 用户名、密码、端口是否正确

### 9.2 后台能打开，但简答题判分失败

通常是 LLM 配置问题，优先检查：

- `DOUBAO_API_KEY`
- `DOUBAO_MODEL`
- `DOUBAO_BASE_URL`

建议先执行：

```bash
python scripts/llm_smoke_test.py
```

### 9.3 简历上传后识别效果差

优先检查：

- 是否安装了 Tesseract
- `TESSERACT_CMD` 是否正确
- PDF 是否是扫描件
- `RESUME_PDF_OCR` 是否开启

### 9.4 短信发送失败

优先检查：

- 阿里云 AK/SK 是否有效
- 短信模板和签名是否已审核通过
- 模板参数格式是否与控制台一致

## 10. 建议第一次排查的文件

- `app.py`：看完整业务入口
- `db.py`：看表结构和数据流转
- `services/assignment_service.py`：看分发记录和 token 生成
- `services/grading_service.py`：看判分逻辑
- `services/resume_service.py`：看简历解析和 OCR
- `services/llm_client.py`：看豆包接口调用
- `qml/parser.py`：看试卷格式约束

