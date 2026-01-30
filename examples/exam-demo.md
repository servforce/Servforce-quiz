---
id: exam-demo-001
title: AI 基础测评（示例）
description: |
  这是一个最小示例试卷，用于验证 QML 解析、分发、作答与判分流程。
format: qml-v2
llm:
  prompt_template: |
    你是严格的阅卷老师。只根据评分标准给分。
    请输出 JSON：{"score":0..{{max_points}},"reason":"..."}。
    【题目】{{question}}
    【评分标准】{{rubric}}
    【考生回答】{{answer}}
---

## Q1 [single] (5)
Transformer 的自注意力主要用于？

- A) 仅用于位置编码
- B*) 计算序列内部依赖并进行加权聚合
- C) 仅用于卷积降维

## Q2 [multiple] (6) {partial=true}
以下哪些属于常见优化器？

- A*) Adam
- B) Dropout
- C*) SGD
- D*) AdamW

## Q3 [short] {max=10}
用不超过 150 字解释“过拟合”的定义与危害。

[rubric]
1) 给出清晰定义（训练误差低、测试误差高等）；
2) 说明原因或表现；
3) 描述危害；
4) 表达清晰。
[/rubric]

