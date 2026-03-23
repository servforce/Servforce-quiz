# 文档导航

## 产品与范围

- [项目愿景](vision.md)

## 协作约定

- [通用协作与编码细则](agent-rules/general.md)

## 架构

- [架构总览](architecture/overview.md)
- [运行拓扑](architecture/runtime-topology.md)
- [后端模块分工](architecture/backend-modules.md)
- [数据模型与存储](architecture/data-model.md)
- [核心请求流程](architecture/request-flows.md)

## 配置与参考

- [配置项说明](reference/configuration.md)
- [REST API 约定](reference/api.md)
- [QML 试卷格式](../qml.md)

## UI

- [UI 主题覆盖](ui/theme.md)
- [前端工作区说明](ui/frontend-workspace.md)

## 建议阅读顺序

1. 根目录 [README.md](../README.md)
2. [项目愿景](vision.md)
3. [架构总览](architecture/overview.md)
4. [运行拓扑](architecture/runtime-topology.md)
5. [后端模块分工](architecture/backend-modules.md)
6. [数据模型与存储](architecture/data-model.md)
7. [REST API 约定](reference/api.md)
8. [前端工作区说明](ui/frontend-workspace.md)

## 说明

- `docs/architecture/` 记录目标形态和稳定边界，不再把旧 Flask 单体实现当作唯一事实来源。
- 旧系统仍通过 `legacy bridge` 暂时保留，但文档默认面向新架构。
