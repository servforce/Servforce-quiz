# 核心请求流程

## 1. 试卷创建与发布

1. 管理员登录后台。
2. 在 `/admin/exams/upload` 上传 QML Markdown，或通过 `/admin/exams/ai` 生成草稿。
3. 解析后的试卷结构和资源写入 `exam_definition` / `exam_asset`。
4. 管理员可继续编辑、预览、查看试卷纸面版，或开启公开邀约。

## 2. 专属邀约流程

1. 管理员在 `/admin/assignments` 选择候选人和试卷，创建 assignment。
2. `assignment_record` 生成短 token，同时尽量补齐对应 `exam_paper`。
3. 候选人通过 `/t/<token>` 进入验证流程。
4. 验证成功后进入 `/a/<token>` 或 `/exam/<token>` 答题页。

## 3. 公开邀约流程

1. 试卷启用公开邀约后，候选人通过 `/p/<public_token>` 进入。
2. 系统按输入信息创建候选人和 assignment。
3. 后续流程与专属邀约一致，最终仍落到 token 维度的作答链路。

## 4. 验证与入场

1. 候选人提交姓名、手机号等基础信息。
2. 若启用短信或本机号码认证，则通过 `/api/public/sms/send` 和 `/api/public/verify` 完成校验。
3. 某些试卷要求先上传简历，简历入口在 `/resume/<token>`。
4. 验证通过后，assignment / exam_paper 状态推进到 `verified` 或 `in_exam`。

## 5. 作答与交卷

1. 页面通过 `/api/public/answers/<token>` 或 `/api/public/answers_bulk/<token>` 暂存答案。
2. 交卷时调用 `/api/public/submit/<token>`。
3. 系统校验时间限制、最短交卷时长和当前状态，随后推进到 `grading`。
4. 自动收卷线程也会对超时记录执行同类推进。

## 6. 判卷与归档

1. 客观题直接在 `services/grading_service.py` 中判分。
2. 简答题在配置了 LLM 时走 `services/llm_client.py` 的 Responses API。
3. 判卷结果回写 assignment，并生成 `exam_archive` 快照。
4. 后台通过 `/admin/result/<token>`、`/admin/attempt/<token>` 或候选人详情页回看结果。

## 7. 运行监控

1. 系统事件写入 `system_log`。
2. LLM token、短信调用等每日指标写入 `runtime_daily_metric`。
3. 后台 `/admin/status` 和相关 API 用于展示当前状态与告警信息。
