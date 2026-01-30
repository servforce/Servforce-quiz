# 基于 Markdown（QML）在线能力测试系统（JSON 优先）设计文档

> 约束：**只参考 `qml.md`**；除“候选人列表”外尽量不使用数据库——试卷解析内容、答题数据等都落到 **JSON 文件** 中；HTTP 使用 **Flask（Python）**；管理员可上传 Markdown 试卷并生成候选人唯一链接/二维码；候选人身份验证后在线作答；系统自动判分（客观题）+ 大模型判分（简答题）得到总分并给出是否进入面试建议。

---

## 1. 角色与业务流程

### 1.1 角色
- **管理员**：登录后台；上传 QML（Markdown）试卷；创建候选人（入库到 PostgreSQL 候选人列表）；为候选人生成唯一答题链接/二维码；查看进度与成绩。
- **候选人**：通过唯一链接进入；输入姓名/手机号完成身份验证；在线作答并提交（或到时自动交卷）。
- **系统**：解析 QML → 生成 `spec.json`；控制尝试验证次数/计时；判分（客观题对比正确答案；简答题调用 LLM 依据 rubric 评分）；汇总总分并生成是否进行面试。

### 1.2 流程（对应需求 1~3）
1) 管理员登录 → 上传 `*.md` 试卷 → 立即解析（QML）→ 将题号/类型/分数/题目/选项/正确答案/评分标准写入 `spec.json`  
2) 管理员在后台为候选人录入个人信息（写入 PostgreSQL 候选人表）→ 为候选人生成唯一 token（写入 `assignment.json`）→ 生成链接/二维码并发送  
3) 候选人打开链接 → 输入姓名/手机号与 DB 比对（完全一致通过）  
   - 失败：累加尝试次数，达到最大次数则 token 失效（`assignment.locked=true`）  
   - 通过：进入答题页，开始计时，提交或超时自动交卷  
4) 收卷后：  
   - 客观题：从 `spec.json` 取正确答案与候选人答案比对，正确得满分、错误 0  
   - 简答题：从 `spec.json` 取 rubric（评分标准）+ 候选人答案组装 prompt 发送给 LLM，得到分数与理由  
   - 汇总主客观得分 → 与阈值比较 → 给出“进入面试/不进入面试”建议，将分数，理由，是否进入面试都存入到对应候选人表格

---

## 2. 试卷格式（QML）与解析要点（来自 `qml.md`）

### 2.1 QML 题目头
二级标题开头：
```
## Q<编号> [single|multiple|short] (分数可选) {属性可选}
```
类型：
- `single`：单选题
- `multiple`：多选题（可选 `{partial=true}`）
- `short`：简答题（建议 `{max=10}` 指定满分）

### 2.2 选项与正确答案标记
- 选项使用无序列表：`- A) 文本`
- 正确选项在字母后加 `*`：`- B*) 文本`
- `multiple` 题可能有多个 `*`

### 2.3 简答题 rubric 与 LLM 配置
- rubric：
  - `[rubric]...[/rubric]`
- 题目级 LLM（覆盖全局）：
  - `[llm] key=value ... [/llm]`；若没有 `key=` 则整段作为 `prompt_template`

---

## 3. 存储设计（JSON 优先 + PostgreSQL 仅候选人）

### 3.1 文件系统目录结构（建议）
```
storage/
  exams/
    {exam_key}/
      source.md                 # 原始上传的 Markdown
      spec.json                 # QML 解析后的结构化试卷（含正确答案/rubric）
      public.json               # 候选人视角试卷（不含正确答案/rubric）
  assignments/
    {token}.json                # token 对应一次答题实例（身份验证、计时、答案、判分）
  qr/
    {token}.png                 # token 对应二维码（可缓存）
```

### 3.2 JSON 文件写入原则
- **强一致写入**：使用“写临时文件 → 原子替换”的方式避免写一半损坏（Windows 可用 `os.replace`）。
- **并发锁**：对 `assignments/{token}.json` 进行文件锁（例如 `portalocker`），防止并发写导致覆盖。
- **审计可追溯**：`spec.json` 一经发布建议不改；若要更新则递增版本并新建目录或在 JSON 中保存 `version`。

---

## 4. JSON 结构定义（核心）

### 4.1 `spec.json`（管理员/判分使用，包含正确答案与 rubric）
满足“题号、类型、分数、题目、选项、正确答案、评分标准分别存入 Json 文件”的要求：
```json
{
  "meta": {
    "id": "exam-demo-001",
    "title": "AI 基础测评",
    "description": "...",
    "format": "qml-v2",
    "duration_seconds": 3600,
    "pass_score": 60
  },
  "llm": {
    "model": "gpt-4o-mini",
    "temperature": 0.0,
    "prompt_template": "..."
  },
  "questions": [
    {
      "id": "Q1",
      "type": "single",
      "points": 5,
      "text_md": "题干（Markdown）",
      "options": [
        { "key": "A", "text_md": "选项A", "correct": false },
        { "key": "B", "text_md": "选项B", "correct": true }
      ],
      "correct_answer": "B",
      "partial_credit": false
    },
    {
      "id": "Q2",
      "type": "multiple",
      "points": 6,
      "text_md": "题干（Markdown）",
      "options": [
        { "key": "A", "text_md": "Adam", "correct": true },
        { "key": "B", "text_md": "Dropout", "correct": false }
      ],
      "correct_answer": ["A", "C", "D"],
      "partial_credit": true
    },
    {
      "id": "Q4",
      "type": "short",
      "max_points": 10,
      "text_md": "题干（Markdown）",
      "rubric_md": "评分标准（来自 [rubric] 块）",
      "llm_override": {
        "model": "gpt-4o-mini",
        "temperature": 0.0,
        "prompt_template": "题目级 prompt（来自 [llm] 块）"
      }
    }
  ]
}
```

### 4.2 `public.json`（候选人展示用，不泄露正确答案与 rubric）
```json
{
  "meta": { "id": "exam-demo-001", "title": "...", "duration_seconds": 3600 },
  "questions": [
    {
      "id": "Q1",
      "type": "single",
      "points": 5,
      "text_md": "...",
      "options": [ { "key": "A", "text_md": "..." }, { "key": "B", "text_md": "..." } ]
    },
    {
      "id": "Q4",
      "type": "short",
      "max_points": 10,
      "text_md": "..."
    }
  ]
}
```

### 4.3 `assignments/{token}.json`（答题实例：验证、计时、答案、判分）
```json
{
  "token": "random_token",
  "exam_key": "exam-demo-001",
  "candidate_id": "uuid-from-postgres",

  "verify": {
    "max_attempts": 3,
    "attempts": 0,
    "locked": false,
    "verified": false,
    "verified_at": null
  },

  "timing": {
    "duration_seconds": 3600,
    "started_at": null,
    "submitted_at": null,
    "auto_submitted": false
  },

  "status": "created",

  "answers": {
    "Q1": "B",
    "Q2": ["A", "D"],
    "Q4": "简答题文本..."
  },

  "grading": {
    "objective_score": 0,
    "subjective_score": 0,
    "total_score": 0,
    "passed": null,
    "per_question": {
      "Q1": { "score": 5, "reason": "match" },
      "Q4": { "score": 7, "reason": "LLM rationale..." }
    },
    "llm": {
      "Q4": {
        "model": "gpt-4o-mini",
        "prompt": "...",
        "response_raw": { "score": 7, "reason": "..." },
        "error": null
      }
    }
  },

  "updated_at": "2026-01-22T12:00:00Z"
}
```
状态字段建议枚举：
- `created`：已创建 token，未验证
- `verified`：身份验证通过
- `in_progress`：开始答题计时
- `submitted`：已交卷（人工提交或自动交卷）
- `graded`：已判分出结果
- `expired`：超时或被锁定失效

---

## 5. 数据库设计（PostgreSQL，仅候选人列表）

> 只存候选人基本信息，用于身份验证与后台候选人管理；考试/答题均不落库（落 JSON）。

### 5.1 表结构
```sql
CREATE TYPE candidate_status AS ENUM ('send', 'verified', 'finished');

CREATE TABLE IF NOT EXISTS candidate (
  id               BIGSERIAL PRIMARY KEY,
  name             TEXT NOT NULL,
  phone            TEXT NOT NULL,
  status           candidate_status NOT NULL DEFAULT 'send',
  score            INT NOT NULL DEFAULT 0 CHECK (score BETWEEN 0 AND 100),
  duration_seconds INT NULL CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
  interview        BOOLEAN NOT NULL DEFAULT FALSE,
  remark           TEXT NOT NULL DEFAULT '',
  UNIQUE (phone)
);

CREATE INDEX IF NOT EXISTS idx_candidate_phone ON candidate(phone);
CREATE INDEX IF NOT EXISTS idx_candidate_status ON candidate(status);
```

### 5.2 备注（满足“候选人表答题状态变化”的实现方式）
在“尽量不使用数据库”的边界下，考试过程细节（验证次数、计时、逐题答案、判卷明细）仍以 `storage/assignments/{token}.json` 为准；**候选人表进行状态字段枚举所进行的各类状态**：
- `created`：已创建 token，未验证
- `verified`：身份验证通过
- `in_progress`：开始答题计时
- `submitted`：已交卷（人工提交或自动交卷）
- `graded`：已判分出结果
- `expired`：超时或被锁定失效

同时在“提交/判分完成”阶段写回：`score`（0-100）、`duration_seconds`（答题时间）、`interview`（是否进入面试）、`remark`（评价/理由）。

---

## 6. 主要功能模块与任务定义（Python/Flask）

### 6.1 模块划分（建议）
- `web/admin.py`：管理员登录、上传试卷、创建候选人/生成 token、查看结果
- `web/public.py`：候选人验证、取题、保存答案、提交、查询状态
- `qml/parser.py`：按 `qml.md` 解析 Markdown → `spec.json`
- `storage/json_store.py`：JSON 读写（锁、原子替换、路径校验）
- `services/assignment_service.py`：token 创建、二维码生成、验证次数控制、计时逻辑
- `services/grading_service.py`：客观题判分、汇总逻辑
- `services/llm_service.py`：LLM 调用与结果解析（score + reason）
- `tasks/worker.py`（可选）：异步判分任务（LLM 评分可能耗时）

### 6.2 异步任务（推荐）
> 避免 HTTP 请求因 LLM 耗时而超时；不依赖 DB，可通过 JSON 状态驱动。

- `grade_objective(token)`：读取 `spec.json` + `assignment.json.answers` → 写入 `grading.per_question` 与 `objective_score`
- `grade_subjective(token)`：对所有 `short` 题生成 prompt → 调用 LLM → 写入 `grading.llm`、`subjective_score`
- `finalize_grade(token)`：计算 `total_score` 与 `passed` → 更新 `status='graded'`

任务触发时机：
- `POST /api/public/submit` 后触发 `enqueue(grade_all, token)`  

---

## 7. 判分规则（满足需求 3 的“正确得满分，错误不得分”）

### 7.1 客观题
- `single`：候选答案与 `correct_answer` 相等 → 得 `points`，否则 0
- `multiple`：本需求默认“全对才得分、否则 0”  
  - 若 QML `{partial=true}`：可以扩展“部分得分”，但必须在设计中固定算法并写入 `spec.json.partial_credit`（例如仍然 0/满分，或按命中率比例）

### 7.2 简答题（LLM）
输入来自 `spec.json`：
- 题干：`text_md`
- 评分标准：`rubric_md`
- 满分：`max_points`
- Prompt 模板：全局 `spec.llm.prompt_template`，若题目有 `llm_override.prompt_template` 则覆盖

建议约束模型输出为 JSON，减少解析失败：
```text
你是严格的阅卷老师。请只输出 JSON：{"score": <0~max_points数字>, "reason": "<简短理由>"}。
【题目】{question}
【评分标准】{rubric}
【考生回答】{answer}
【满分】{max_points}
```

---

## 8. HTTP 接口定义（Flask）

> 分两类：管理员端（需要登录）与候选人端（token 驱动）。本设计给出最小闭环接口集合。

### 8.1 管理员认证（不入库）
管理员账号密码建议放在环境变量或配置文件：
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD_HASH`（bcrypt/argon2）

接口：
- `GET /`：管理员登录页（HTML）
- `POST /admin/login`：表单登录（写 session）
- `POST /admin/logout`：退出

### 8.2 试卷管理
- `GET /admin/exams`：试卷列表（从 `storage/exams/*/spec.json` 扫描或维护 `index.json`）
- `POST /admin/exams/upload`
  - form-data：`file=@exam.md`，可选 `duration_seconds`、`pass_score`
  - 行为：解析 QML → 写入 `storage/exams/{exam_key}/source.md` + `spec.json` + `public.json`
  - 返回：`{ "exam_key": "...", "question_count": 10 }`

### 8.3 候选人管理与生成链接/二维码
- `GET /admin/candidates`：候选人列表（PostgreSQL）
- `POST /admin/candidates`：创建候选人（PostgreSQL）
  - body：`{ "name": "...", "phone": "..." }`
- `POST /admin/assignments`
  - body：`{ "exam_key": "...", "candidate_id": "..." , "max_attempts": 3 }`
  - 行为：生成 `token`，写入 `storage/assignments/{token}.json`，生成二维码 `storage/qr/{token}.png`，并将候选人表 `status` 更新为 `send`
  - 返回：
    ```json
    {
      "token": "xxx",
      "url": "https://host/t/xxx",
      "qr_png_url": "/admin/qr/xxx.png"
    }
    ```
- `GET /admin/qr/{token}.png`：返回二维码 PNG

### 8.4 候选人入口与验证
- `GET /t/{token}`：候选人验证页（HTML）
- `POST /api/public/verify`
  - body：`{ "token": "...", "name": "...", "phone": "..." }`
  - 行为：读取 `assignments/{token}.json` → 若 locked/expired 返回 410  
    - DB 查询 candidate：姓名/手机号完全一致才通过  
    - 通过则将候选人表 `status` 更新为 `verified`
    - 失败则 `verify.attempts++`，达到上限则 `locked=true` 并返回 410
  - 返回：
    - 200：`{ "ok": true, "next_url": "/a/{token}" }`
    - 403：`{ "ok": false, "remaining": 2 }`
    - 410：`{ "ok": false, "error": "link_locked" }`

### 8.5 答题与提交
- `GET /a/{token}`：答题页（HTML）
- `GET /api/public/exam/{token}`
  - 返回 `public.json` + 当前 `status/remaining_seconds`
- `PUT /api/public/answers/{token}`
  - body：`{ "question_id": "Q1", "answer": "B" }`（single）
  - body：`{ "question_id": "Q2", "answer": ["A","D"] }`（multiple）
  - body：`{ "question_id": "Q4", "answer": "..." }`（short）
  - 行为：写入 `assignments/{token}.json.answers`（带锁）
- `POST /api/public/submit/{token}`
  - 行为：标记 `submitted_at`，`status='submitted'`；触发判分任务；并将候选人表 `status` 更新为 `finished`
  - 返回：`{ "ok": true }`
- `GET /api/public/status/{token}`
  - 返回：`{ "status": "...", "remaining_seconds": 123 }`

### 8.6 成绩（管理员/候选人）
候选人是否可见成绩可配置：
- `GET /api/public/result/{token}`（可选）：返回 `grading.total_score/passed`（若允许）
- `GET /admin/result/{token}`：管理员查看该 token 的完整判分细节（含 LLM 理由、逐题得分）

---

## 9. 前端页面设计（Flask + Jinja + 少量 JS）

### 9.1 管理员登录页 `/`
- 输入：账号、密码
- 提示：登录失败原因（不暴露具体字段）

### 9.2 管理员控制台（示例 `/admin`）
模块：
- **上传试卷**
  - 上传 `.md`，上传成功后展示：标题、题目数、总分、解析耗时、错误定位（如行号）
- **候选人管理**
  - 新增候选人：姓名、手机号
  - 候选人列表：搜索（手机号/姓名）
- **生成链接/二维码**
  - 选择试卷（`exam_key`）+ 选择候选人（`candidate_id`）
  - 生成后显示：
    - 复制链接按钮
    - 二维码预览与下载按钮
- **结果列表**
  - 依据 `storage/assignments/*.json` 扫描汇总：状态、得分、是否通过

### 9.3 候选人验证页 `/t/{token}`
- 输入：姓名、手机号
- 展示：
  - 剩余验证次数
  - 链接失效提示（locked/expired）

### 9.4 候选人答题页 `/a/{token}`
布局：
- 顶部：倒计时（来自后端 `started_at + duration_seconds`）、提交按钮
- 中间：题目卡片（single/multiple/short）
- 交互：
  - 自动保存：答题变更后 `PUT /api/public/answers/{token}`
  - 超时：前端主动提交；后端也要兜底强制收卷（以服务器时间判断）

---

## 10. 安全与边界条件处理

- **管理员认证**：使用密码哈希 + session；开启 CSRF（后台表单/接口）
- **Token 安全**：随机不可猜（建议 32 字节以上），只作为资源定位，不包含候选人信息
- **防路径穿越**：所有 `exam_key/token` 只允许 `[A-Za-z0-9_-]`，拼路径前必须校验
- **验证次数限制**：以 `assignments/{token}.json.verify` 为准；达到上限立即锁定
- **计时不可篡改**：后端记录 `started_at`，根据服务器时间判断是否超时
- **数据泄露**：候选人 API 永不返回 `spec.json`（包含正确答案/rubric）
- **LLM 失败兜底**：记录 error；可重试 N 次；失败时 `score=0` 或标记待人工复核
- **并发写冲突**：JSON 文件写入必须加锁 + 原子替换

---

## 11. 部署与配置（示例）

### 11.1 环境变量
- `DATABASE_URL=postgresql://...`（仅 candidate）
- `SECRET_KEY=...`
- `ADMIN_USERNAME=...`
- `ADMIN_PASSWORD_HASH=...`
- `STORAGE_DIR=.../storage`
- `LLM_PROVIDER=openai|azure|mock`
- `OPENAI_API_KEY=...`

### 11.2 进程
- Web：Flask/Gunicorn
- Worker（可选）：RQ/Celery（处理 LLM 判分与汇总）

---

## 12. 最小 MVP 交付清单（建议）

1) QML 解析（仅按 `qml.md` 的 single/multiple/short + rubric + llm）→ 生成 `spec.json/public.json`  
2) 管理员登录页 + 控制台：上传试卷、创建候选人、生成 token 链接与二维码  
3) 候选人：验证（姓名/手机号）→ 在线答题 → 提交/超时收卷  
4) 判分：客观题全对满分/错 0；简答题调用 LLM 返回分数+理由；汇总总分并给出阈值判断  
