# 灵枢语义层 · IR Schema v0.1

> 语义语言层的中间表示（IR）——大脑（md_cg）的上游，语言的下游。
> 存储：JSON（机器）+ MD（人读）。真源为本目录下的 JSON/MD 文件。

## 语义原子（Semantic Atom）

不可再分的语义单元。type 六类：entity / substance / property / event / state / relation。

文件：atoms.json
结构：{ meta, atoms: [ { id, zh, type, layer, degree, importance, bucket } ] }

## 语义组合（Semantic Composition）

两个及以上原子按角色组合，产生新概念。

文件：compositions.json（待建）
结构：{ id, type, roles: [{role, atom}], surface: {zh, en}, memory_anchor }

## 组合算子（v0）

| 算子 | 类型约束 | 例 |
|---|---|---|
| COMPOSE | SOURCE(animal) × MATERIAL(substance) → PRODUCT(food) | 牛+肉→牛肉 |
| AGENT | agent(entity) × action(event) | 人+吃 |
| MODIFY | property × entity | 大+脑 |
| CLASSIFY | category × entity | 热力学+定律 |

## 与认知图的对接

语义原子 id → 认知图节点 id（通过 anchors 字段）
语义组合 id → 认知图节点 id + N 条边
检索归一：surface query → semantic → canonical → 认知图节点
