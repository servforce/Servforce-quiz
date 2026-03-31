---
name: quiz-workflow
description: Use this skill when a task spans both quiz repository specification and QML authoring, or when you need a single entry point to install, maintain, review, or navigate the quiz-related skills in this repo, including md-quiz-repo.yaml, quizzes/<quiz_id>/quiz.md, assets, QML syntax, parser boundaries, sync behavior, and generated quiz headers.
---

# Quiz Workflow

## 何时使用

在以下场景优先使用这个 skill：

- 需要一个统一入口处理 quiz 相关 skill 的安装、维护和导航
- 任务同时涉及 quiz 仓库规范和 QML 定义
- 评审或设计 quiz 的端到端交付形态，包括仓库、`quiz.md`、资源目录、同步、生成和解析
- 不确定当前问题应先看 `quiz-repo-spec` 还是 `qml-authoring`

## 工作流

1. 先读 [references/maintenance-checklist.md](references/maintenance-checklist.md)
2. 判断当前问题归属：
   - 仓库结构、manifest、资源目录、同步失败：转到 [../quiz-repo-spec/SKILL.md](../quiz-repo-spec/SKILL.md)
   - QML 语法、parser 边界、示例修订：转到 [../qml-authoring/SKILL.md](../qml-authoring/SKILL.md)
   - 两者都涉及：两个子 skill 都要核对，不要只改一侧
3. 修改实现后，回到本 skill 的维护清单，检查文档、测试和版本号是否同步

## 硬规则

- 这个 skill 是总入口，不重复维护两份子 skill 的完整规范正文
- 仓库规范与 QML 定义分层维护，但版本代际和示例要保持一致
- 涉及生成器默认输出时，要同时检查生成内容、规范示例和测试是否一致

## 参考资料

- 维护清单： [references/maintenance-checklist.md](references/maintenance-checklist.md)
- 仓库规范子 skill： [../quiz-repo-spec/SKILL.md](../quiz-repo-spec/SKILL.md)
- QML 子 skill： [../qml-authoring/SKILL.md](../qml-authoring/SKILL.md)
