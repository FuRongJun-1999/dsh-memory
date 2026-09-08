# Memory Bench 1000 · 记忆系统公开测试集

> 来源：灵枢（AEIS）本地认知图的 `context`（情境层）真实数据，**已脱敏**。
> 用途：记忆系统五维标尺（S/R/J/C/Safety）的**真实案例检验**。
> 2026-09-08 · 可随仓库公开分发。

---

## 1. 为什么需要它

记忆系统的评测长期缺少**真实噪声**：合成基准太干净，看不出「信号与噪声混在一起」时的表现。
本数据集取自真实运行 26 天的记忆库（60189 条情境记录），**保留真实噪声形态**（测试夹具、
系统日志、过程记录）与真实对话，用来检验：

- **R 检索**：能否从噪声里精准捞出真实对话（Precision@K / 噪声率）
- **C 信噪比**：信号与噪声的区分能力（开关「来源通道判据」的对照）
- **J 判断**：能否对噪声做出「遗忘/降权」判定
- **S 存储**：大量低价值节点是否压垮结构（分桶健康度）
- **Safety**：脱敏后是否仍可读、密级隔离是否有效

---

## 2. 数据构成（1000 条，分层抽样）

| category | 条数 | label | 说明 |
|---|---:|---|---|
| `conversation` | 250 | **signal** | 真实用户对话（有实质内容） |
| `fixture_prefeed` | 150 | **noise** | 前馈测试夹具（H1 海马体前馈的测试用例） |
| `fixture_dialogue` | 150 | **noise** | 批量对话测试夹具（`[会话X·要点N] 问题？`） |
| `sys_log` | 100 | **noise** | 系统运行日志（`[consolidation] 演练 N · 提升 M`） |
| `verify_record` | 150 | unlabeled | 白箱校验过程记录（含问答，非纯噪声） |
| `session_other` | 150 | unlabeled | 其它会话外部化记录 |
| `other` | 50 | unlabeled | 未归类 |

标签合计：**signal 250 · noise 400 · unlabeled 350**。

> `unlabeled` 是**诚实的留白**：`verify_record`/`session_other` 既非纯信号也非纯噪声，
> 留给评测方自行判定（或作为「边界样本」检验判定引擎的稳定性）。

---

## 3. 字段

```json
{
  "id": "membench-a1b2c3d4e5",   // **稳定 id**：由源节点 id 派生（重建不变，标注可累积）
  "text": "……",                 // 脱敏后的正文
  "category": "conversation",   // 见上表
  "label": "signal",            // signal | noise | unlabeled
  "importance": 0.6,            // 原库重要性评分（未改动）
  "tags": ["dsh", "user"],      // 脱敏后的标签
  "chars": 42
}
```

平均长度 136 字符。

> **id 稳定性**：id 由源节点 id 的 SHA1 前 10 位派生，因此**重复构建得到完全相同的
> id 与内容**（已验证）。人工复检的修正按 id 记录，重建后不会错位。

---

## 4. 脱敏说明（重要）

**所有敏感值已替换为「自带标识的确定性伪随机占位符」**——格式保真（记忆系统仍看到真实形态），
但一眼可辨是合成数据，且**同输入同输出**（数据集可复现）。

| 类型 | 占位形式 |
|---|---|
| 手机号 | `1700000XXXX`（170 虚拟运营商 + 哨兵 0000） |
| 身份证 | `11000019000101XXXX` |
| 银行卡 | `622200000000XXXX` |
| 邮箱 | `user<h6>@example.com`（保留域） |
| OpenAI key | `sk-PLACEHOLDER<h36>` |
| GitHub PAT | `ghp_PLACEHOLDER<h24>` |
| AWS AKID | `AKIAPLACEHOLDER<X>` |
| Bearer | `Bearer PLACEHOLDER-<h28>` |
| **AppID / AppSecret** | `<PLACEHOLDER-APPID-…>` / `<PLACEHOLDER-APPSECRET-…>` |
| 密码/密钥 KV | `<PLACEHOLDER-PWD-…>` / `<PLACEHOLDER-KEY-…>` |
| **高熵 token** | `PLACEHOLDER<h24>`（纯字母数字 ≥20 字符、熵 ≥3.5、大小写数字混合 → 判为密钥）|
| 姓名 | `张三/李四/…`（中文占位名） |
| 工号 | `EMP-PLACEHOLDER-<h6>` |
| 住址 | `某某省某某市某某区某某路N号` |
| 用户名/账号 | `userPLACEHOLDER<h6>` / `PLACEHOLDER_<h6>` |
| 绝对路径 | `<PATH>\最后一段` |
| 长 hex | `PLACEHOLDER<h24>` |
| IPv4 | `10.0.X.Y`（内网段） |

**复检**：**统一门禁 `verify_bench.py`** 四道检查全部 **0 命中**，退出码 0（可发布）：
① 隐私 PII（手机/邮箱/身份证/银行卡/密钥/路径/姓名/住址…）
② 凭据 KV（appid/appsecret/token/password/cookie…）
③ **熵检测**（纯字母数字 ≥20 字符 ∧ 熵 ≥3.5 ∧ 大小写+数字混合 → 判为密钥）
④ 内容政策（性/成人 + 政治敏感）

白名单仅放行自带 `PLACEHOLDER` 标识 / 哨兵值。门禁脚本含敏感词表，故存放在私有仓库
（`AEIS/tools/verify_bench.py`），不随公开仓库分发。

---

## 5. 内容政策（公开数据集合规声明）

本数据集**经过内容政策过滤**，不含以下内容：

| 类别 | 处理 |
|---|---|
| **性 / 成人内容** | 全部剔除（含本项目早期成人视觉研究相关记录：大胸/巨乳/胸部/阴部/vulva/性相关术语及对应会话）|
| **政治敏感内容** | 全部剔除（政治人物、历史事件、分裂/颠覆类表述等）|

**过滤方式**：`build_memory_bench.py` 内置 `POLICY_DENY` 正则（70+ 模式），
在分层抽样阶段即跳过违规条目，并从同层补充样本，保持 1000 条配额与分布不变。
另有 `EXCLUDE_ORIG_IDS` **显式排除名单**（人工复检判定「应删除」的源节点，按 id 永久排除）。

**复检**：统一门禁 `verify_bench.py` 独立重扫 → 性/成人 **0 命中**、政治敏感 **0 命中**。
（`乳` 已排除「哺乳动物」、`性交` 已排除「非线性交互」这类子串误判。）

> 本数据集仅用于记忆系统评测，不承载任何违规内容；如仍有遗漏，请通过 Issue 反馈，我们会立即下架修正。

---

## 6. 用法

```python
import json
rows = [json.loads(l) for l in open('data/memory-bench-1000.jsonl', encoding='utf-8')]

# 检索精度：用 signal 条目作查询，看 Top-K 命中率与噪声率
signals = [r for r in rows if r['label'] == 'signal']
for q in signals[:20]:
    hits = my_memory.search(q['text'][:30], k=10)
    ...
```

建议指标：`Precision@K`（Top-K 中 label=signal 占比）、`噪声率`、`unlabeled 边界稳定性`。

---

## 7. 已知边界（诚实声明）

- 数据来自**单一项目的 26 天运行**，领域偏技术/工程，不代表通用分布。
- `label` 是**基于来源标签的粗标注**（`dsh/user` → signal、夹具/日志 → noise），
  **不是人工逐条判定**；边界样本（`unlabeled`）故意留白。
- 脱敏是**模式化**的：非常规写法的敏感信息（如自然语言描述的手机号）可能未被捕获。
  **请勿把它当作"绝对无隐私"的保证**，只作为公开测试集使用。

---
*数据集由 `build_memory_bench.py` 生成；发布前经统一门禁 `verify_bench.py` 四道检查（0 残留）。*
