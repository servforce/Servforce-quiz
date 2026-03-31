# QML（Quiz Markdown Language）

`qml.md` 只保留快速入口与最小示例。

- 完整 QML 语法规范：[`skills/qml-authoring/references/qml-spec.md`](skills/qml-authoring/references/qml-spec.md)
- parser 实际边界与报错口径：[`skills/qml-authoring/references/parser-truth.md`](skills/qml-authoring/references/parser-truth.md)
- quiz 仓库结构与同步规则：[`skills/quiz-repo-spec/references/repo-contract.md`](skills/quiz-repo-spec/references/repo-contract.md)

## 关键提醒

- QML 只定义 `quiz.md` 文件内容如何写，不定义仓库目录结构。
- 仓库结构、manifest、资源目录规则属于 `quiz-repo-spec`，不要混进 QML 语法里。
- 示例中的资源路径统一使用 `./assets/...`。
- 解析事实来源是 `backend/md_quiz/parsers/qml.py` 和相关测试。

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
