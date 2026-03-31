# Quiz Skills 维护清单

这个文件只负责总入口视角下的分流和联动检查，不重复两份规范正文。

## 子 skill 分工

- 仓库结构、`md-quiz-repo.yaml`、`quizzes/<quiz_id>/quiz.md`、`assets/`、同步失败排查：
  - 读 [../../quiz-repo-spec/SKILL.md](../../quiz-repo-spec/SKILL.md)
- QML 语法、Front Matter、题头、`[rubric]`、`[llm]`、欢迎图/结束图、parser 边界：
  - 读 [../../qml-authoring/SKILL.md](../../qml-authoring/SKILL.md)

## 联动变更检查

以下变更通常需要两侧一起核对：

- 修改仓库版本号：
  - 同步 [../../quiz-repo-spec/references/repo-contract.md](../../quiz-repo-spec/references/repo-contract.md)
  - 同步 [../../qml-authoring/references/qml-spec.md](../../qml-authoring/references/qml-spec.md)
  - 同步 `backend/md_quiz/services/exam_repo_sync_service.py`
  - 同步相关测试
- 修改 QML 头部推荐字段：
  - 同步 [../../qml-authoring/references/qml-spec.md](../../qml-authoring/references/qml-spec.md)
  - 同步 [../../qml-authoring/references/parser-truth.md](../../qml-authoring/references/parser-truth.md)
  - 同步 `backend/md_quiz/services/exam_generation_service.py`
  - 同步相关测试
- 修改资源路径规则：
  - 同步 [../../quiz-repo-spec/references/repo-contract.md](../../quiz-repo-spec/references/repo-contract.md)
  - 同步 [../../qml-authoring/references/qml-spec.md](../../qml-authoring/references/qml-spec.md) 中的示例
  - 同步 `backend/md_quiz/services/exam_repo_sync_service.py`
  - 同步 `backend/md_quiz/services/exam_generation_service.py`
  - 同步相关测试

## 推荐验证顺序

1. 先确认当前改动属于哪一个子 skill，还是两者联动
2. 改规范文档，再改运行时代码和测试
3. 检查以下项是否仍一致：
   - 仓库 manifest 版本号
   - QML `schema_version` / `format`
   - 生成器默认输出的头部字段
   - 示例中的资源路径
4. 运行与改动最相关的测试，避免只改文档不改实现，或只改实现不改规范
