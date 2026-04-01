---
name: quiz-repo-spec
description: Use this skill when defining, reviewing, migrating, or debugging a syncable quiz repository, especially md-quiz-repo.yaml, quizzes/<quiz_id>/quiz.md layout, asset path rules, repo-relative source_path, and exam repo sync failures.
---

# Quiz Repo Spec

## 何时使用

在以下场景优先使用这个 skill：

- 若任务同时涉及 quiz 仓库规范和 QML 定义，优先先看 [../md-quiz/SKILL.md](../md-quiz/SKILL.md) 作为总入口
- 设计或调整可同步的 quiz 仓库结构
- 处理 `md-quiz-repo.yaml`、`quizzes/<quiz_id>/quiz.md`、`assets/` 相关问题
- 评审 `quiz.md` Front Matter 元数据是否符合仓库使用约定，例如 `id`、`tags`
- 排查 quiz 仓库同步失败、资源路径失败、路径迁移失败
- 评审“仓库规范”与同步实现是否一致

## 工作流

1. 先读 [references/repo-contract.md](references/repo-contract.md)
2. 若问题表现为同步失败，再读 [references/sync-troubleshooting.md](references/sync-troubleshooting.md)
3. 回到项目实现核对 `backend/md_quiz/services/exam_repo_sync_service.py` 与相关测试
4. 若问题其实是 QML 语法本身，不要继续在本 skill 里猜，转到 `skills/qml-authoring/SKILL.md`

## 硬规则

- 当前唯一正式仓库规范是 `md-quiz-repo.yaml + quizzes/<quiz_id>/quiz.md`
- 资源路径只讨论“仓库如何组织与同步如何接受”，不定义 QML 语法
- `source_path` 以 repo-relative path 为准
- 旧的根目录 `.md + images/` 结构不再作为正式规范

## 参考资料

- 规范正文： [references/repo-contract.md](references/repo-contract.md)
- 排错顺序： [references/sync-troubleshooting.md](references/sync-troubleshooting.md)
