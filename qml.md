# QML（Quiz-Markdown Language）轻量 DSL（推荐）

## 设计目标

让“写题”像写普通 Markdown，一眼能看懂；少符号、少缩进；仍然可无损映射到你现有的后端数据结构。

## 基本规则

* 题目以二级标题开头：`## Q<编号> [类型] (分值) {可选属性...}`

  * 类型：`[single] | [multiple] | [short]`
  * 分值：能力题用 `(5)`；简答用 `{max=10}`
  * 其他属性：`{partial=true}`、`{media=img/q1.png}` 等
* 题干：标题下一段文本/图片
* 选项：使用无序列表，格式 `- A) 文本`

  * 正确选项：在 **选项字母后加星号**，如 `- B*) 文本`
  * 性向增量：在选项行尾加 `{traits:S=1,N=-1}`
  * 选项自带分：在行尾加 `{points=2}`（可选）
* 简答题 rubric/LLM：用成对的标记块

  * `[rubric]...[/rubric]`
  * `[llm] key=value 行式配置，可选 [/llm]`

## 完整示例

```markdown
---
id: exam-demo-001
title: AI 基础测评
description: |
  本试卷包含基础能力与性向维度两部分内容。
welcome_image: img/welcome.png
end_image: img/thanks.png
llm:
  model: gpt-4o-mini
  temperature: 0.0
  prompt_template: |
    请依据评分标准对答案打分，仅输出一个0-{{max_points}}的整数分值。
    【题目】{{question}}
    【评分标准】{{rubric}}
    【考生回答】{{answer}}
trait:
  dimensions: [I, E, S, N, T, F, J, P]
  chart:
    type: mermaid
    template: |
      pie title 维度得分
      "I" : {{I}} "E" : {{E}} "S" : {{S}} "N" : {{N}}
      "T" : {{T}} "F" : {{F}} "J" : {{J}} "P" : {{P}}
format: qml-v2
---

## Q1 [single] (5) {media=}
选择正确的描述：Transformer 的自注意力用于？

- A) 仅用于解码器，建模语言的因果依赖
- B*) 计算序列内部依赖与加权聚合
- C) 仅替代卷积以降维
- D) 仅做位置编码

## Q2 [multiple] (6) {partial=true}
下列哪些属于常见优化器？

- A*) Adam
- B)  Dropout
- C*) SGD
- D*) AdamW

## Q3 [single]
你更偏好哪种学习方式？

- A) 实操演练 {traits:S=1}
- B) 概念推演 {traits:N=1}

## Q4 [short] {max=10}
用不超过150字解释“过拟合”的定义与危害。

[rubric]
1) 准确定义：训练误差低测试误差高；
2) 原因与迹象；
3) 可能危害；
4) 表达清晰。
[/rubric]

[llm]
prompt_template=你是严格的阅卷老师，请仅输出分数数字（0-{{max_points}}）。
[/llm]
```

**映射到后端字段**

* `## Q1 [single] (5) {media=...}` → `Question.id/type/points/media/partial_credit/...`
* 选项行 `- B*) 文本 {traits:S=1}` → `Option.key='B'`, `correct` 自动收集，`traits={'S':1}`
* 简答 `[short]{max=10}` + `[rubric]...` → `max_points/rubric`；`[llm]` → 题目级 `LLMConfig`

## 优点

* 极简、友好、git diff 清晰；编辑器高亮良好。
* 100% 可无损映射到你已有的数据模型与评分规则。

## 潜在问题/边界
* 少量自定义语法需解析（但远比 YAML 嵌套简单）；
* 若出现极端复杂的题目元信息（很少见），可能仍需回退到 YAML。
* **唯一性**：`QID` 必须唯一；解析器应校验并给出行号/列号。
* **多选的 `partial_credit`**：缺省 `false`，仅当题头或属性有 `{partial=true}` 时启用。
* **traits 合法性**：允许正负与 0，维度键不做强校验（保持扩展性）。
* **LLM 覆盖**：题目级 `[llm]` 优先于 Front Matter；解析器需要层级合并。
* **标识符**：建议 Front Matter 加 `format: qml-v2`，便于导入器做分支。