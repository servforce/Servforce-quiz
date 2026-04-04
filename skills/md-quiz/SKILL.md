---
name: md-quiz
description: Use this skill as the default entry point when creating, editing, reviewing, migrating, or debugging md-quiz repositories and quiz.md files. It routes quiz content and QML syntax work to qml-authoring, and routes repository structure, md-quiz-repo.yaml, quiz paths, assets, and sync contract work to quiz-repo-spec.
---

# MD Quiz

## 何时使用

在以下场景优先使用这个总入口 skill：

- 新建一份 `md-quiz` 问卷
- 维护或修订 `quizzes/<quiz_id>/quiz.md`
- 调整 `md-quiz-repo.yaml`、`assets/` 或 quiz 目录结构
- 排查 QML 语法问题、parser 契约问题、repo sync 问题
- 用户只知道“要维护问卷”，但还没明确是语法问题还是仓库问题

## 路由规则

1. 先判断任务是“题目内容/QML 语法”还是“仓库结构/同步契约”
2. 若是以下内容，转到 [../qml-authoring/SKILL.md](../qml-authoring/SKILL.md)：
   - Front Matter 元数据，如 `title`、`description`、`tags`
   - `quiz.md` 题头、题型、`answer_time`
   - 选项写法、`[rubric]`、`[llm]`
   - `single + {scoring=traits}` 量表题
   - traits 维度含义、分析建议与结果解释口径
   - `trait` 元数据是否与题面实际使用一致
   - `intro` / `outro` 图片是否需要补充，以及是否适合横幅展示
   - welcome/end image
   - QML parser 契约与边界
3. 若是以下内容，转到 [../quiz-repo-spec/SKILL.md](../quiz-repo-spec/SKILL.md)：
   - `md-quiz-repo.yaml`
   - `quizzes/<quiz_id>/quiz.md` 路径和目录命名
   - `assets/` 资源组织
   - repo-relative `source_path`
   - 同步失败、路径失败、资源越界
4. 若任务同时涉及两类问题：
   - 先按 `quiz-repo-spec` 确认仓库落点和路径
   - 再按 `qml-authoring` 处理 `quiz.md` 内容与语法

## 工作流

1. 用户只提“维护问卷”时，默认先使用本 skill 做分流
2. 若要新增或修改题目，先读 [../qml-authoring/references/qml-spec.md](../qml-authoring/references/qml-spec.md)
3. 若要改 manifest、目录结构或资源路径，先读 [../quiz-repo-spec/references/repo-contract.md](../quiz-repo-spec/references/repo-contract.md)
4. 若问题跨两层，不要混猜，按“仓库层先、QML 层后”的顺序处理

## 硬规则

- 本 skill 是总入口，不重复维护底层细节规范
- QML 语法规则以 `qml-authoring` 为准
- 仓库结构和同步契约以 `quiz-repo-spec` 为准
- 当任务边界不清楚时，优先使用本 skill 分流，而不是跳过判断直接修改
