# 文档导航

## 产品与范围

- [项目愿景](vision.md)

## 协作约定

- [通用协作与编码细则](agent-rules/general.md)

## 架构

- [架构总览](architecture/overview.md)
- [后端模块分工](architecture/backend-modules.md)
- [数据模型与存储](architecture/data-model.md)
- [核心请求流程](architecture/request-flows.md)

## 配置与参考

- [配置项说明](reference/configuration.md)
- [QML 试卷格式](../qml.md)

## UI

- [UI 主题覆盖](ui/theme.md)

## 建议阅读顺序

1. 根目录 `README.md`
   先看系统定位、启动方式和最小可运行说明。
2. [项目愿景](vision.md)
   先确认边界，避免把项目误解成通用 LMS 或 SaaS 考试平台。
3. [架构总览](architecture/overview.md)
   建立入口、分层、路由面和运行模型的整体图。
4. [核心请求流程](architecture/request-flows.md)
   串起“分发 -> 验证 -> 答题 -> 交卷 -> 判卷 -> 归档”主链路。
5. [数据模型与存储](architecture/data-model.md)
   对齐 `candidate / assignment_record / exam_paper / exam_archive` 的角色关系。
6. [后端模块分工](architecture/backend-modules.md)
   再落到目录、模块边界和关键实现入口。
7. `qml/parser.py` 与 [QML 试卷格式](../qml.md)
   涉及试卷上传、题型语义或答案结构时必须一起看。

## 说明

- `docs/architecture/` 只保留项目级架构说明，不重复粘贴代码实现细节。
- 根目录 `README.md` 负责外部介绍和启动说明，`docs/` 负责长期维护的内部知识。
