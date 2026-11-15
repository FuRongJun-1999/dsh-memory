---
access_count: 0
condition_space: {"time_window": [1790870400.0, 1790874000.0]}
confidence: 0.6
created_at: 1790870400.0
edges: []
evidence_count: 0
id: "profile-event-2026-10-02"
importance: 0.6
last_access: 0
layer: "knowledge"
lifecycle_state: "active"
modality: "text"
negative_evidence: 0
non_applicable_conditions: ["正文未出现的属性不在本卡", "同名不合并"]
positive_evidence: 0
tags: ["event", "profile", "event:2026-10-02", "card_source:declared"]
verification_basis: null
verification_state: "unverified"
---
# 功能名：事件资料：2026-10-02
# 生效条件：查询提到「2026-10-02」或其属性（姓名/年龄/职业/地点/日期）时
# 子功能：① 事实序列（按日期升序，每条带来源节点）
# 执行：由 profiles.build 从既有节点确定性聚合（无模型抽取）
# 验证方式：tests/test_profiles.py
# 不适用条件：正文未出现的属性不在本卡；同名不合并

- 2026-10-02 | 曾在示例工坊做过学徒（来源 source1）
