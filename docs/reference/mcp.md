# MCP 能力说明

## 入口

- MCP 服务默认挂载到 `/mcp`
- 传输方式固定为 `Streamable HTTP`
- 后台说明页入口为 `/admin/mcp`
- 文档直链为 `/docs/reference/mcp.md`

## 鉴权

- 远程 MCP 使用 `Bearer Token`
- 不复用后台浏览器登录态
- 启用 MCP 时必须设置 `MCP_AUTH_TOKEN`

## 环境变量

- `MCP_ENABLED`
- `MCP_AUTH_TOKEN`
- `MCP_CORS_ALLOW_ORIGINS`

## 工具清单

### 系统与运维

- `system_health`
- `system_processes`
- `runtime_config_get`
- `runtime_config_update`
- `system_status_summary`
- `system_status_range`
- `system_status_update_thresholds`
- `job_list`
- `job_get`
- `job_wait`

### 测验与同步

- `quiz_repo_get_binding`
- `quiz_repo_bind`
- `quiz_repo_rebind`
- `quiz_repo_sync`
- `quiz_list`
- `quiz_get`
- `quiz_set_public_invite`

### 候选人与档案

- `candidate_list`
- `candidate_ensure`
- `candidate_get`
- `candidate_add_evaluation`
- `candidate_delete`

### 邀约与结果

- `assignment_list`
- `assignment_create`
- `assignment_get`
- `assignment_set_handling`
- `assignment_delete`

## 默认脱敏规则

- 候选人手机号默认脱敏
- 简历原文与结构化原始内容默认不直接返回
- 答卷明细默认只返回摘要，不直接返回完整答案
- 需要明文时，工具调用需显式传 `include_sensitive=true`

## 高危确认规则

以下操作默认只返回预检结果；只有传 `confirm=true` 才真正执行：

- `quiz_repo_rebind`
- `candidate_delete`
- `assignment_delete`

## 典型智能体流程

1. `quiz_repo_get_binding` 查看当前仓库状态
2. `quiz_repo_bind` 或 `quiz_repo_sync` 准备题库
3. `candidate_ensure` 建立候选人
4. `assignment_create` 创建邀约
5. `assignment_get` / `assignment_list` 查看作答和结果
6. `system_status_summary` / `runtime_config_update` 查看或调整系统状态

## 后台说明页

- 后台左侧导航新增 `MCP`
- 页面路径固定为 `/admin/mcp`
- 该页只展示接入摘要、能力范围、典型流程和安全规则
- 页面不渲染 Markdown，不承担文档编辑功能；完整说明仍以本页为准
