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
- 推荐头部补充：
  - `tags`
  - `schema_version: 2`
  - `question_count`
  - `question_counts`
  - `estimated_duration_minutes`
- QML 语法层不定义 manifest、repo path、目录结构

### trait 元数据（可选）

当问卷包含 `single + {scoring=traits}` 的量表题时，可在 Front Matter 中补充 `trait` 元数据。

推荐结构：

```yaml
trait:
  dimensions: [I, E, S, N, T, F, J, P]
  dimension_meanings:
    I: 更偏向独立思考、独处恢复和表达前先整理。
    E: 更偏向外部互动、即时反馈和从交流中获得能量。
  analysis_guidance:
    paired_dimensions:
      - I/E：比较独立内化与外向互动的主导倾向。
    scoring_method:
      - 将每组对立维度分别累计总分，取分高的一侧作为主倾向。
    interpretation:
      - 优先看成对维度的差值，而不是只看单个标签。
```

说明：

- `trait` 只应在问卷实际包含 traits 量表题时出现；若题面没有 `scoring=traits` 或选项级 `traits`，应删除整段 `trait` 元数据
- `dimensions` 用于声明允许出现的 trait key
- `dimension_meanings` 推荐显式写明每个维度的含义，方便消费端解释
- `analysis_guidance` 推荐写明成对维度、计分方式和解释建议

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
- `intro` / `outro` 图片都属于可选项，不是问卷必填内容
- 若使用首图或尾图，建议优先使用横幅图，推荐宽高比约为 `2:1`

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
  dimension_meanings:
    I: 更偏向独立思考、独处恢复精力、表达前先内化整理。
    E: 更偏向外部互动、即时表达、从社交和讨论中获得能量。
    S: 更偏向经验、事实与可验证细节，重视现实可行性。
    N: 更偏向可能性、趋势和抽象联想，重视概念与潜在机会。
    T: 更偏向一致标准、逻辑推理和客观判断。
    F: 更偏向关系感受、共情反馈和人的影响。
    J: 更偏向计划、秩序、提前安排和明确边界。
    P: 更偏向灵活应变、边走边看和根据变化调整。
    A: 更偏向情绪稳定、自我接纳和压力下保持平衡。
    TU: 更偏向敏感波动、反复反思和更强的不确定感受。
  analysis_guidance:
    paired_dimensions:
      - I/E：比较独处内化与外向互动的主导倾向。
      - S/N：比较经验务实与抽象联想的主导倾向。
      - T/F：比较逻辑标准与关系感受的主导倾向。
      - J/P：比较计划秩序与灵活应变的主导倾向。
      - A/TU：比较稳定果断与敏感波动的主导倾向。
    scoring_method:
      - 将每组对立维度分别累计总分，取分高的一侧作为该组主倾向。
      - 若同组平分，则依次比较 +2 次数、+1 次数；若仍平分，固定落位 I/S/T/J/A。
    interpretation:
      - 优先看每组两侧的相对差值，差值越大说明偏好越稳定。
      - 若某组差值很小，更适合解释为情境依赖，而不是强行贴类型标签。
---

## Q1 [single] (0) {scoring=traits, answer_time=20s}
我通常会在做决定前先把计划排到比较细。

- A) 非常同意 {traits=J:2}
- B) 比较同意 {traits=J:1}
- C) 中立
- D) 比较不同意 {traits=P:1}
- E) 非常不同意 {traits=P:2}
```
