# Quiz 仓库规范

## 目标

本规范定义“什么样的 Git 仓库可以被 `md-quiz` 同步”。

- QML 只负责 `quiz.md` 文件内容如何写
- quiz 仓库规范只负责这些文件在仓库里如何组织、同步器如何接受

## 唯一正式结构

```text
<repo>/
  md-quiz-repo.yaml
  README.md
  quizzes/
    <quiz_id>/
      quiz.md
      assets/
        ...
```

### 根目录要求

- 必须存在 `md-quiz-repo.yaml`
- 必须存在 `README.md`
- 新增、删除或重命名 quiz 后，必须同步更新 `md-quiz-repo.yaml` 与 `README.md`
- 不再支持根目录散落 `*.md`

### manifest 要求

文件：`md-quiz-repo.yaml`

```yaml
schema_version: 2
kind: md-quiz-repo
quizzes:
  - path: quizzes/common-ability-2025/quiz.md
```

规则：

- `schema_version` 必须为 `2`
- `kind` 必须为 `md-quiz-repo`
- `quizzes` 必须是非空列表
- 每个 `path` 只能是 `quizzes/<quiz_id>/quiz.md`
- `path` 不能重复，不能越界，必须真实存在
- 新增或删除 quiz 时，`quizzes` 列表必须同步反映实际仓库内容
- 当前仓库规范版本号与 QML 头部推荐的 `schema_version: 2` / `format: qml-v2` 保持同一代际

## Quiz 目录规则

- 每份 quiz 一个目录：`quizzes/<quiz_id>/`
- 试卷入口文件固定名：`quiz.md`
- `quiz.md` 的 Front Matter `id` 必须等于目录名 `<quiz_id>`
- `quiz.md` 可包含 `tags` 作为 quiz 级元数据；`tags` 属于 `quiz.md` Front Matter，不属于 `md-quiz-repo.yaml`
- 同步时 `source_path` 保存 repo-relative path，例如 `quizzes/common-ability-2025/quiz.md`

## 资源规则

- 资源示例统一写成 `./assets/...`
- 同步实现接受 `./assets/...` 与 `assets/...`
- 只允许引用当前 quiz 目录下的图片资源
- 不允许：
  - 跨 quiz 目录引用
  - 仓库根目录共享资源
  - 非图片资源
  - 越界路径

示例：

```markdown
![intro](./assets/welcome.png)

## Q1 [single] (5) {media=./assets/q1.png}
题干 ![](./assets/q1-detail.png)
```

## 与现有内部模型的关系

- 仓库外部语义统一使用 `quiz`
- 当前内部运行时仍映射到现有 `exam_definition` / `exam_version` / `exam_key`
- 这层映射属于实现细节，不影响仓库作者

## 非目标

以下内容不在本规范中定义：

- QML 题头语法
- `[rubric]` / `[llm]` 语法
- parser 报错边界

这些内容交给 `skills/qml-authoring/`。
