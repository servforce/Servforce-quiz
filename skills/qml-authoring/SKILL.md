---
name: qml-authoring
description: Use this skill when authoring, reviewing, fixing, or documenting QML quiz markdown, especially question headers, answer_time, rubric and llm blocks, welcome/end images, parser edge cases, and examples that must stay consistent with the active QML parser contract.
---

# QML Authoring

## 何时使用

在以下场景优先使用这个 skill：

- 编写或修订 `quiz.md` 内容
- 维护 `quiz.md` Front Matter，包括 `title`、`description`、`tags`
- 排查 QML 解析错误
- 更新 `qml.md` 或 QML 示例
- 评审 QML 语法与 parser 行为是否一致

## 工作流

1. 先读 [references/qml-spec.md](references/qml-spec.md)
2. 若问题涉及 parser 实际边界，再读 [references/parser-truth.md](references/parser-truth.md)
3. 若当前环境能访问 parser 实现与测试，再回到本地 parser 代码和测试核对
4. 若当前环境无法访问 parser 源码，就把 `parser-truth.md` 视为默认 parser 契约，不要虚构“源码里一定如何实现”
5. 若问题是仓库结构、manifest、资源目录，而不是 QML 语法，转到 `skills/quiz-repo-spec/SKILL.md`

## 硬规则

- 不凭页面表现反推 QML 语法
- 若拿得到本地 parser 实现，优先以本地 parser 和测试为准
- 若拿不到本地 parser 实现，优先以 `parser-truth.md` 中写明的契约和边界为准
- QML 语法与 quiz 仓库规范分层维护，不混写

## 参考资料

- 语法规范： [references/qml-spec.md](references/qml-spec.md)
- parser 事实： [references/parser-truth.md](references/parser-truth.md)
