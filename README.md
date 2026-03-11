# Markdown Quiz

基于 Flask + PostgreSQL 的在线笔试系统，面向候选人筛选、笔试邀约、在线答题、自动判卷和后台管理。

当前项目已经实现的核心能力：

- 管理员后台登录、试卷管理、候选人管理、分发管理、日志与系统状态
- 通过 QML 风格 Markdown 上传试卷，并生成可公开访问的试卷邀请链接
- 候选人姓名 + 手机号校验，支持阿里云短信验证码验证
- 在线答题、限时考试、最短交卷时长限制、自动收卷
- 客观题自动判分，简答题可接入豆包/火山方舟兼容接口做 LLM 判分
- 候选人简历上传、文本提取、基础识别、LLM 结构化解析
- 后台查看考试结果、归档快照、业务日志和系统资源消耗
- 后台 AI 辅助生成试卷

## 项目概览

主要入口和目录：

```text
markdown_quiz/
  app.py                  Flask 应用入口，主要路由都在这里
  config.py               环境变量与全局配置
  db.py                   PostgreSQL 初始化、查询与写入
  qml/                    QML Markdown 解析器
  services/               业务服务层
  templates/              Jinja2 模板
  static/                 静态资源
  storage/                运行期文件存储
  tests/                  pytest 测试
  docs/                   补充设计文档
```

运行期数据大致分布在：

- `storage/exams/<exam_key>/spec.json`: 完整试卷，包含答案和评分信息
- `storage/exams/<exam_key>/public.json`: 面向候选人的公开试卷
- `storage/exams/<exam_key>/assets/`: 试卷引用的图片等资源
- `storage/assignments/<token>.json`: 单次分发/作答记录
- `storage/archives/*.json`: 已完成考试的归档快照
- `storage/public_invites.json`: 公开邀约索引
- `storage/system_status.json`: 系统状态页阈值配置

数据库里主要有三类数据：

- `candidate`: 候选人基础信息和简历
- `exam_paper`: 候选人与试卷之间的单次考试记录
- `system_log`: 操作日志、判卷日志、系统告警和资源统计

## 当前业务流程

### 管理员侧

1. 打开 `/admin/login` 登录后台
2. 在 `/admin/exams` 上传或编辑 QML Markdown 试卷
3. 可在后台使用 AI 生成试卷草稿，再继续编辑
4. 在 `/admin/candidates` 手工创建候选人，或上传简历自动生成候选人
5. 在 `/admin/assignments` 创建单次考试邀约，生成候选人专属链接和二维码
6. 也可以对某套试卷启用“公开邀约”，得到公开报名入口和二维码
7. 在后台查看考试进度、作答详情、判卷结果、日志和系统状态

### 候选人侧

候选人有两种进入方式：

- 专属邀约：访问 `/t/<token>`
- 公开邀约：访问 `/p/<public_token>`，系统会先创建候选人和 assignment，再跳转到专属流程

实际答题流程：

1. 输入姓名和手机号
2. 如系统启用短信验证，则输入短信验证码
3. 某些流程下需要先上传简历
4. 验证通过后进入答题页 `/a/<token>`
5. 到时自动收卷，或手动提交
6. 后台异步判卷并归档结果

## 功能清单

### 后台页面

- `/admin`: 仪表盘
- `/admin/exams`: 试卷管理
- `/admin/candidates`: 候选人管理
- `/admin/assignments`: 分发与考试记录
- `/admin/logs`: 业务日志
- `/admin/status`: 系统状态与资源消耗

### 已实现能力

- 试卷上传、预览、编辑、删除
- 试卷公开邀约开关与二维码生成
- AI 辅助生成试卷
- 候选人快速创建、编辑、删除
- 简历上传、下载、重解析
- 单次考试分发、最短交卷时长限制、邀请有效期控制
- 客观题自动判卷与简答题 LLM 判卷
- 候选人作答归档与后台回看
- 系统告警、日志分类统计、每日资源用量展示

## 本地启动

### 1. 环境要求

- Python 3.10+
- PostgreSQL 16+，或使用仓库内置 `docker-compose.yml`

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 启动 PostgreSQL

如果本机没有现成数据库，可以直接启动：

```bash
docker compose up -d
```

当前 `docker-compose.yml` 默认配置为：

- 数据库名：`markdown_quiz`
- 用户名：`postgres`
- 密码：`admin`
- 本机端口：`5433`

### 4. 配置环境变量

先复制模板：

```bash
copy .env.example .env
```

最少需要确认这些配置：

```env
DATABASE_URL=postgresql+psycopg2://postgres:admin@127.0.0.1:5433/markdown_quiz
APP_SECRET_KEY=change-me
# ADMIN_USERNAME=admin
# ADMIN_PASSWORD=admin
```

说明：

- `DATABASE_URL` 不填时，会回退到 `postgresql://postgres:postgres@127.0.0.1:5432/markdown_quiz`
- `APP_SECRET_KEY` 建议修改，避免使用默认开发值
- `ADMIN_USERNAME` 默认是 `admin`
- `ADMIN_PASSWORD` 默认是 `admin`

### 5. 启动应用

```bash
python app.py
```

默认访问地址：

- 后台登录页：`http://127.0.0.1:5000/admin/login`
- 后台首页：`http://127.0.0.1:5000/admin`

应用启动时会自动执行数据库初始化和必要的表结构升级。

## 环境变量

### 基础配置

- `DATABASE_URL`: PostgreSQL 连接串
- `APP_SECRET_KEY`: Flask 会话和签名密钥
- `ADMIN_USERNAME`: 后台用户名，默认 `admin`
- `ADMIN_PASSWORD`: 后台密码，默认 `admin`
- `PORT`: Web 端口，默认 `5000`
- `STORAGE_DIR`: 文件存储目录，默认项目下的 `storage`
- `LOG_LEVEL`: 日志级别

### LLM 与 AI 判分

项目当前封装的是豆包 / Volcengine Ark 兼容接口：

- `DOUBAO_API_KEY` 或 `ARK_API_KEY`
- `DOUBAO_MODEL`
- `DOUBAO_BASE_URL`
- `LLM_RESPONSE_FORMAT_JSON`
- `LLM_RETRY_MAX`
- `LLM_RETRY_BACKOFF`
- `LLM_TIMEOUT_STRUCTURED`

如果不配置 LLM：

- 客观题仍可正常判分
- 简答题 LLM 判分不可用
- 简历结构化解析能力会下降
- 后台 AI 生成试卷不可用

### assignment token

- `ASSIGNMENT_TOKEN_SECRET`: assignment token 的签名密钥，建议显式设置

### 简历解析

- `RESUME_DETAILS_TEXT_MAX_CHARS`
- `RESUME_DETAILS_FOCUS_MAX_CHARS`
- `RESUME_EXPERIENCE_RAW_MAX_CHARS`
- `RESUME_DETAILS_PROMPT_MAX_CHARS`

当前支持的简历文件类型：

- `pdf`
- `docx`
- `png`
- `jpg`
- `jpeg`

### 短信验证

项目当前接入的是阿里云短信能力，常用变量包括：

- `ALIYUN_ACCESS_KEY_ID`
- `ALIYUN_ACCESS_KEY_SECRET`
- `ALIYUN_SMS_ENDPOINT`
- `ALIYUN_SMS_REGION_ID`
- `ALIYUN_SMS_SIGN_NAME`
- `ALIYUN_SMS_TEMPLATE_CODE`
- `ALIYUN_SMS_TEMPLATE_PARAM`
- `ALIYUN_SMS_CODE_TTL_SECONDS`
- `ALIYUN_SMS_CODE_LENGTH`

未配置短信能力时，短信验证码流程不可用。

## 试卷格式

试卷使用 QML 风格 Markdown，解析器位于 `qml/parser.py`。

支持的题型：

- `single`: 单选题
- `multiple`: 多选题
- `short`: 简答题

最小示例：

```md
---
title: Python 基础测试
---

## Q1 [single] (5)
Python 中定义函数使用哪个关键字？
- A) func
- B*) def
- C) function

## Q2 [short] {max=10}
请简述列表和元组的区别。
[rubric]
回答出可变性、使用场景或性能差异即可得分。
[/rubric]
```

可参考：

- `qml.md`
- `examples/exam-demo.md`

## 测试

运行全部测试：

```bash
pytest
```

当前测试主要覆盖：

- QML / Markdown 解析
- 简历文本提取与分段
- LLM 判分相关逻辑
- 最短交卷时长
- 候选人查询条件
- 静态资源解析

## 常见问题

### 1. 启动时报数据库连接错误

优先检查：

- PostgreSQL 是否真的启动
- `DATABASE_URL` 是否指向正确主机和端口
- 用户名、密码、数据库名是否正确

### 2. 后台能打开，但简答题判分失败

通常是 LLM 配置问题，优先检查：

- `DOUBAO_API_KEY`
- `DOUBAO_MODEL`
- `DOUBAO_BASE_URL`

### 3. 简历上传后解析效果不稳定

优先检查：

- 简历文件本身是否可正常提取文本
- 图片/PDF 是否是扫描件，文字是否清晰
- LLM 配置是否完整

### 4. 短信发送失败

优先检查：

- 阿里云 AK/SK 是否有效
- 短信签名和模板是否审核通过
- `ALIYUN_SMS_TEMPLATE_PARAM` 格式是否与模板变量一致

## 建议先读的文件

- `app.py`: 业务主入口和路由
- `db.py`: 表结构与数据库访问
- `services/assignment_service.py`: assignment 存取和加锁
- `services/grading_service.py`: 判卷逻辑
- `services/resume_service.py`: 简历提取与解析
- `services/llm_client.py`: 豆包接口调用
- `services/exam_generation_service.py`: AI 出题
- `qml/parser.py`: QML 试卷格式约束
