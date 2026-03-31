# Quiz 仓库同步排错

## 核对顺序

遇到同步失败时，按这个顺序排：

1. 仓库根目录是否有 `md-quiz-repo.yaml`
2. 仓库根目录是否有 `README.md`
3. manifest 的 `schema_version` / `kind` / `quizzes` 是否合法
4. manifest `path` 是否严格是 `quizzes/<quiz_id>/quiz.md`
5. `quiz.md` 是否存在，且 Front Matter `id` 是否等于目录名
6. Markdown 是否只引用图片，不包含普通链接
7. 图片是否都在当前 quiz 目录 `assets/` 下
8. 图片是否存在、未越界、未超 1MB、扩展名合法
9. 仓库内是否出现重复 quiz id

## 常见错误与含义

### `仓库缺少 md-quiz-repo.yaml`

- 当前仓库不是新版 quiz 仓库
- 常见于旧的根目录 `.md + images/` 结构

### `仓库缺少 README.md`

- 仓库未满足最小发布面要求

### `md-quiz-repo.yaml kind 必须为 md-quiz-repo`

- manifest 类型错误

### `md-quiz-repo.yaml 仅支持 schema_version: 2`

- 当前仓库规范版本号不匹配
- 应与 quiz 头部推荐的 `schema_version: 2` / `format: qml-v2` 保持同一代际

### `manifest path 只支持 quizzes/<quiz_id>/quiz.md`

- 当前 path 不符合标准目录结构
- 例如：根目录 `demo.md`、`exam/demo.md`、`quizzes/demo/demo.md` 都不合法

### `Front matter id 必须与目录名一致`

- `quizzes/backend-basic/quiz.md` 的 `id` 只能是 `backend-basic`

### `Markdown 只允许引用图片`

- QML 内容里出现了普通 Markdown 链接

### `图片必须位于当前 quiz 目录 assets/ 下`

- 使用了 `images/`、`../`、其他 quiz 的路径、或仓库根共享资源

## 实现事实来源

- 同步实现：`backend/md_quiz/services/exam_repo_sync_service.py`
- 相关测试：`tests/test_exam_repo_sync_service.py`
