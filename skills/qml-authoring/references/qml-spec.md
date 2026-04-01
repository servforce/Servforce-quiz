# QML 规范

## 目标

QML 是 quiz markdown 的轻量 DSL。它定义的是 `quiz.md` 文件内容如何写，不定义仓库目录结构。

## Front Matter

推荐字段：

```yaml
---
id: common-ability-2025
title: 共性能力测评
description: |
  面向候选人的基础能力测评。
  本试卷共 10 题，其中单选 6 题、多选 2 题、简答 2 题，预计 34 分钟完成。
tags: [common-ability, recruiting]
schema_version: 2
format: qml-v2
question_count: 10
question_counts:
  single: 6
  multiple: 2
  short: 2
estimated_duration_minutes: 34
---
```

说明：

- `id`：在采用 `quiz-repo-spec` 的仓库中，应与目录名一致
- `title` / `description` / `format`：按需填写
- `tags`：可选，推荐写成 YAML 字符串列表，用于分类、检索和筛选
- `tags` 在同步时会做 trim、去空、去重、保序；推荐直接在仓库里保持整洁
- 推荐头部补充：
  - `tags`
  - `schema_version: 2`
  - `question_count`
  - `question_counts`
  - `estimated_duration_minutes`
- `question_count` / `question_counts` / `estimated_duration_minutes` 属于可推导字段；仓库可填写，但外部仓库同步时会按题目内容重算并覆盖
- 当前服务端重算 `estimated_duration_minutes` 时，若题目里存在 `answer_time`，会优先按所有题目的 `answer_time` 累计秒数向上折算为分钟；若未配置 `answer_time`，才回退为按题型估算
- QML 语法层不定义 manifest、repo path、目录结构

## 题头格式

```markdown
## Q1 [single] (5) {answer_time=45s}
## Q2 [multiple] (6) {partial=true}
## Q3 [short] {max=10, answer_time=10m}
## Q4 [single] (0) {scoring=traits, answer_time=20s}
```

规则：

- 题目以二级标题开头
- 类型：`single` / `multiple` / `short`
- `single`、`multiple` 必须有 `(分值)`
- `short` 必须有 `{max=分值}`
- 可选属性：
  - `partial=true`
  - `media=./assets/q1.png`
  - `answer_time=45s`
  - `scoring=traits`
- 默认情况下，`single` 是“有正确答案的单选题”
- 当 `single` 使用 `{scoring=traits}` 时，它表示“无正确答案的量表题”
- trait 量表题推荐使用 `(0)`，因为其得分来自选项权重，而不是答题正确性

## 题干与图片

- 题干是题头后的正文
- 题干中可使用 Markdown 图片或 HTML `<img>`
- 示例路径统一使用 `./assets/...`

## 选项题

格式：

```markdown
- A) 选项文本
- B*) 正确选项
```

trait 量表题示例：

```markdown
## Q1 [single] (0) {scoring=traits, answer_time=20s}

我通常会在做决定前先把计划排到比较细。

- A) 非常同意 {traits=J:2}
- B) 比较同意 {traits=J:1}
- C) 中立
- D) 比较不同意 {traits=P:1}
- E) 非常不同意 {traits=P:2}
```

规则：

- 默认模式下，正确答案在选项字母后加 `*`
- `single` + `{scoring=traits}` 模式下不得出现 `*`
- trait 量表题的得分来自选项上的 `traits`
- 选项可追加 traits / points 等属性
- `traits` 的格式为 `KEY:INT[,KEY:INT...]`
- 当题目使用 `{scoring=traits}` 时，建议至少一个非中立选项带 `traits`

## 简答题

必须包含 `[rubric]...[/rubric]`

```markdown
[rubric]
1) 关键点一
2) 关键点二
3) 表达清晰
[/rubric]
```

可选 `[llm]...[/llm]`

```markdown
[llm]
prompt_template=请只输出分数数字。
[/llm]
```

## 首图与尾图

- 首题前仅支持单独一张 Markdown 图片，映射为 `welcome_image`
- 末题后仅支持单独一张 Markdown 图片，映射为 `end_image`

示例：

```markdown
![intro](./assets/welcome.png)
...
![bye](./assets/thanks.png)
```

## 最小示例

```markdown
---
id: common-ability-2025
title: 共性能力测评
description: |
  面向候选人的基础能力测评。
  本试卷共 2 题，其中单选 1 题、多选 0 题、简答 1 题，预计 12 分钟完成。
tags: [common-ability, demo]
schema_version: 2
format: qml-v2
question_count: 2
question_counts:
  single: 1
  multiple: 0
  short: 1
estimated_duration_minutes: 12
---

![intro](./assets/welcome.png)

## Q1 [single] (5) {media=./assets/q1.png, answer_time=45s}
选择正确描述：

- A) 选项A
- B*) 选项B

## Q2 [short] {max=10}
请简述原因。

[rubric]
1) 观点准确
2) 论证清晰
3) 表达完整
[/rubric]

![bye](./assets/thanks.png)
```

## 人格量表示例

```markdown
---
id: personality-type-5d-80
title: 人格类型测试（五维版·80题）
description: |
  基于公开人格维度框架设计的原创量表。
  本试卷共 80 题，均为 5 级同意度单选题，预计 27 分钟完成。
tags: [personality, mbti-style, traits]
schema_version: 2
format: qml-v2
question_count: 80
question_counts:
  single: 80
  multiple: 0
  short: 0
estimated_duration_minutes: 27
trait:
  dimensions: [I, E, S, N, T, F, J, P, A, TU]
---

## Q1 [single] (0) {scoring=traits, answer_time=20s}
我通常会在做决定前先把计划排到比较细。

- A) 非常同意 {traits=J:2}
- B) 比较同意 {traits=J:1}
- C) 中立
- D) 比较不同意 {traits=P:1}
- E) 非常不同意 {traits=P:2}
```
