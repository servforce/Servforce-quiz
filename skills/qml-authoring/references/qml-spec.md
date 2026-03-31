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
format: qml-v2
---
```

说明：

- `id`：在采用 `quiz-repo-spec` 的仓库中，应与目录名一致
- `title` / `description` / `format`：按需填写
- QML 语法层不定义 manifest、repo path、目录结构

## 题头格式

```markdown
## Q1 [single] (5) {answer_time=45s}
## Q2 [multiple] (6) {partial=true}
## Q3 [short] {max=10, answer_time=10m}
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

规则：

- 正确答案在选项字母后加 `*`
- 可追加 traits / points 等属性

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
format: qml-v2
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
