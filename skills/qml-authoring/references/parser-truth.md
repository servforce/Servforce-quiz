# QML Parser 契约与边界

本文档是 `qml-authoring` 的自包含 parser 契约。

- 如果当前环境能访问实际 parser 实现与测试，应以本地实现为准，并把本文档当成“默认口径”
- 如果当前环境不能访问源码，本文档就是该 skill 可依赖的最小事实集

## 默认支持的行为

### Front Matter

- 若存在 Front Matter，必须以 `---` 开始并闭合
- Front Matter 必须是 YAML mapping
- 若缺少 `id`，允许 parser 生成临时 id；但接入 quiz 仓库规范的同步器通常不会接受这种 quiz

### 题头

- 题头正则只接受：
  - `## <label> [single|multiple|short]`
  - 选项题可带 `(points)`
  - 属性块写在 `{...}`
- 若 `label` 不符合 `Q...`，parser 会自动生成 `Q1/Q2/...`
- 重复 QID 会报 `Duplicate QID`

### answer_time

- 支持整数秒，或 `s/m/h` 后缀
- 范围必须在 `1..3600` 秒

### 选项题

- `single` / `multiple` 必须有选项
- `single` 必须恰好一个正确答案
- `multiple` 至少一个正确答案

### 简答题

- `short` 必须包含 `[rubric]`
- `max_points` 来自 `{max=...}`

### 首图 / 尾图

- 仅当首题前或末题后是“单独一张 Markdown 图片”时才会被识别
- parser 会保留原始路径字符串，不负责判断这个路径是否可被同步

## 默认不由 parser 负责的事

以下校验不属于 QML parser，而属于 quiz repo 同步层：

- `id` 是否等于目录名
- 图片是否位于 `assets/`
- 仓库是否有 manifest
- 普通 Markdown 链接是否合法
- 图片是否存在、是否越界、是否超 1MB

这些问题去看 `skills/quiz-repo-spec/`。

## 使用约束

- 不要把“某个项目里的 parser 文件路径”写成此 skill 的前提
- 不要假设所有接入方都公开了 parser 源码
- 当外部环境的实际 parser 行为与本文档冲突时，应优先记录冲突点，再按接入方实现修正
