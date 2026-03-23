# 配置项说明

## 读取方式

- 应用启动时由 `core/settings.py` 加载 `.env`。
- 根目录 [.env.example](../../.env.example) 提供最常用模板。
- 部分配置虽然未写进模板，但代码已支持，下面一并列出。

## 基础配置

- `DATABASE_URL`：PostgreSQL 连接串。支持 `postgresql://` 和 `postgresql+psycopg2://`，内部会标准化。
- `APP_SECRET_KEY`：Flask session / flash 签名密钥。
- `SECRET_KEY`：仅作为 `APP_SECRET_KEY` 的兼容回退。
- `ADMIN_USERNAME`：后台登录用户名，默认 `admin`。
- `ADMIN_PASSWORD`：后台登录密码，默认 `password`。
- `LOG_LEVEL`：日志级别，默认 `INFO`。
- `PORT`：本地直接运行 `app.py` 时监听端口，默认 `5000`。
- `STORAGE_DIR`：运行目录，默认项目根下 `storage/`。
- `ENABLE_AUTO_COLLECT`：是否启用自动收卷后台线程，默认启用。

## LLM 配置

- `OPENAI_API_KEY`：必填，否则 LLM 功能不可用。
- `OPENAI_MODEL`：模型名。
- `OPENAI_BASE_URL`：OpenAI-compatible 基础地址，默认 `https://ark.cn-beijing.volces.com/api/v3`。
- `LLM_RESPONSE_FORMAT_JSON`：是否要求 JSON 输出。
- `LLM_RETRY_MAX`：最大重试次数。
- `LLM_RETRY_BACKOFF`：重试退避秒数。
- `LLM_TIMEOUT_JSON`：JSON 调用超时。
- `LLM_TIMEOUT_TEXT`：文本调用超时。
- `LLM_TIMEOUT_STRUCTURED`：结构化调用超时。
- `LLM_TIMEOUT_VISION`：视觉调用超时。

未配置 LLM 时：

- 客观题判分仍可工作。
- 简答题 LLM 判分不可用。
- AI 生成试卷不可用。
- 简历结构化质量会下降，部分视觉/OCR 路径不可用。

## Assignment 与考试流程

- `ASSIGNMENT_TOKEN_SECRET`：assignment token 独立签名密钥；不填时回退到应用密钥。

## 简历处理

- `RESUME_USE_LLM`：是否优先启用 LLM 做简历结构化。
- `RESUME_PDF_MAX_PAGES`：PDF 简历解析页数上限。
- `RESUME_DETAILS_TEXT_MAX_CHARS`
- `RESUME_DETAILS_FOCUS_MAX_CHARS`
- `RESUME_EXPERIENCE_RAW_MAX_CHARS`
- `RESUME_DETAILS_PROMPT_MAX_CHARS`

支持的简历输入包括常见 PDF、DOCX 和图片格式；具体处理逻辑以 `services/resume_service.py` 为准。

## 短信与号码认证

- `ALIYUN_ACCESS_KEY_ID`
- `ALIYUN_ACCESS_KEY_SECRET`
- `ALIYUN_SMS_ENDPOINT`
- `ALIYUN_SMS_REGION_ID`
- `ALIYUN_SMS_SIGN_NAME`
- `ALIYUN_SMS_TEMPLATE_CODE`
- `ALIYUN_SMS_TEMPLATE_PARAM`
- `ALIYUN_SMS_OUT_ID`
- `ALIYUN_SMS_UP_EXTEND_CODE`
- `ALIYUN_SMS_CODE_TTL_SECONDS`
- `ALIYUN_SMS_CODE_LENGTH`
- `ALIYUN_SMS_VALID_TIME`
- `ALIYUN_SMS_SCHEME_NAME`
- `ALIYUN_SMS_COUNTRY_CODE`
- `ALIYUN_SMS_CASE_AUTH_POLICY`
- `ALIYUN_DYPNS_ENDPOINT`
- `ALIYUN_DYPNS_REGION_ID`

未配置阿里云凭据时：

- 基础考试流程仍可运行。
- 短信验证码与本机号码认证流程不可用。

## AI 出题附加配置

- `AI_EXAM_DIAGRAM_MODE`：控制 AI 生成图示时优先走模型输出还是本地模板。
