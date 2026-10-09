# 灵枢悬赏板 · 规则（v0.1）

> 一句话：把本仓的 issue 池变成**可认领的悬赏任务**——外部人或 AI agent 认领 → 交付 →
> 过**验收四闸** → 记入**可追溯的声誉账本**。
> **不涉资金**：结算是声誉制（可查、可降、可追溯），不是钱。

设计稿：[悬赏板设计 v0.1](../plans/悬赏板设计_v0.1.md)（2026-10-09）。
机械件：workflow [`.github/workflows/bounty.yml`](../../.github/workflows/bounty.yml)（薄壳·只做事件路由）／
状态机 [`scripts/bounty_board.py`](../../scripts/bounty_board.py)（可本地跑·可离线演练·可测）／
发布模板 [`.github/ISSUE_TEMPLATE/bounty.yml`](../../.github/ISSUE_TEMPLATE/bounty.yml)。
账本 [`ledger.json`](ledger.json) ｜ 荣誉榜 [`board.md`](board.md)。

---

## 一、状态机（六态 · 映射 GitHub labels）

```
bounty:open ──/claim──▶ bounty:claimed ──/deliver──▶ bounty:delivered ──验收──▶ bounty:verified ──▶ bounty:settled
                              │                                                    │
                              └── 72h 超时未交付 ──▶ 回板 bounty:open               └── 争议 ──▶ bounty:disputed
```

- **入选标记**：`bounty`（维护者打——打了才算悬赏任务）。
- **难度标签**：`difficulty:{easy|medium|hard|expert}`（决定结算分，见 §四）。
- **态标签**：`bounty:{open|claimed|delivered|verified|settled|expired|disputed}`。
- 权威记录不是标签，而是**评论里的机器标记**（`<!-- bounty:v1 {…} -->`）：标签是人眼视图，
  标记是账（持有者、到期时间、轮次都在里面）。两者不一致时以标记为准。
- **`bounty:expired` 在 v0.1 不驻留**：超时那一刻直接回板 `bounty:open`，只把
  「超时」这条事件与评论留在痕里（`expired` 仍属可认领态，以便外部工具识别该窗口）。

## 二、命令面（MVP 只做 GitHub 评论命令）

**只认「命令在最前、行首」的词**：`/claim` 必须是评论首个非空行的第一个词。
正文中间的 `/claim`（例如「我觉得应该 /claim 一下」）**不是命令**，机器人不响应。

| 命令 | 谁用 | 校验（未过即回评说明原因） | 效果 |
|---|---|---|---|
| `/claim` | 任何人 | ① 无当前持有者 ② `bounty` 标签在且在 `open`/`expired` 态 ③ 本人并发认领数 ≤ **2** | 上锁 + 记到期时间（**72h**） |
| `/deliver <PR 链接或证据块>` | 认领者 | ① 仅认领人可交付 ② 必带链接或证据块 ③ 轮次 ≤ **3** | 转 `bounty:delivered`，等验收 |
| `/withdraw` | 认领者 | 仅认领人可释放 | 主动释放，任务回板；**不影响声誉** |
| `/dispute <理由>` | 双方（认领者／维护者／issue 作者） | 必带理由 | 转 `bounty:disputed`，我方仲裁并留痕 |
| `/verify [pass\|fail] <理由>` | 维护者 | 态为 `delivered` | 通过 ⇒ `bounty:verified`；不通过 ⇒ 记 −5 并退回返工 |
| `/settle` | 维护者 | 态为 `verified` | 结算，按难度记正分入账本 |

补充口径（白箱、可核）：

- **「必带链接或证据块」**：载荷里出现 `http(s)://…` 链接，**或**评论正文里有围栏代码块
  （``` 里贴可复跑读数）——分析 / 复现类走证据块，修码类走 PR 链接。
- **「最多 3 轮修改」**：同一悬赏的第 4 次 `/deliver` 会被拒；此时请走 `/dispute` 交我方裁定。
- `/verify`、`/settle` 是维护者动作的命令化（设计稿只写了「我方打 `bounty:verified`」
  与 `verified → settled`，未指定触发形态）——若你希望改为纯标签操作，请在 issue 里提出。

## 三、验收四闸（逐道可查 · 不通过就说不通过）

1. **CI 全绿**：该 PR 上本仓的门禁全绿（机器判，不可辩）。
2. **复现读数**：属「可复现缺陷」类 ⇒ 贴**原始读数**（改前 vs 改后逐项对照）。
3. **守卫 + 定点变异**：修码类必须带守卫件，以及「**注入必失败 ⇒ 断言必红并点名**」的
   定点变异自证（本仓既有惯例：判据不设反面证明就等于没有判据）。
4. **维护者人审**：我方 `/verify` 给出判定与理由（含用哪份读数、哪些存疑）。

**防作弊**：交付必带**可复跑**读数；最多 3 轮修改；超时回板；声誉**可降**。

## 四、声誉计分（可追溯账本）

写入 `docs/bounty/ledger.json`（**append-only** 事件流；按事件 id 幂等去重）：

| 事件 | 分值 |
|---|---|
| 结算 easy / medium / hard / expert | **+1 / +3 / +6 / +10** |
| 虚假交付（`/verify fail`） | **−5** |
| 超时未交付（72h 回板） | **−1** |
| 主动释放（`/withdraw`） | 0（不影响声誉） |
| 争议提起与败诉 | 0（**记录在案、不扣本金**） |
| 被拒命令 | 0（记在**尝试者**头上——刷单 / 重复认领的可查痕） |

荣誉榜 `docs/bounty/board.md` 由账本机械生成（不手改）。分数口径是设计稿的**建议值**，
待设计者裁定（改口径只改 `scripts/bounty_board.py` 的 `DIFFICULTY_SCORES` 与负分常量）。

**我们的差异点**（相对纯分数制）：灵枢的声誉可以进**可检索、可追溯的认知图**——
「这个贡献者做过什么、交付质量如何」是能查的，不是一串数字。v0.1 先落公开账本；
认知图侧镜像待裁定。

## 五、争议流程

1. 任一方在 issue 里 `/dispute <理由>`（持有者 / issue 作者 / 维护者）⇒ 转 `bounty:disputed`。
2. 我方在 issue 线程内给出仲裁：**判定在前、读数对照在中、处置与边界在后**（体例参照本仓
   既有 PR 审核细则）；仲裁结论以评论留痕。
3. 不扣本金，但争议记录在案（荣誉榜可见）。

## 六、参与方式

- **发布**（我方）：用 [发布模板](../../.github/ISSUE_TEMPLATE/bounty.yml) 建 issue——**验收标准必填**、
  难度、期望交付形态、参考材料；维护者补 `difficulty:*` 标签。
- **认领**（任何人）：在该 issue 评论 `/claim`（首次认领前请读一遍验收标准——我们只按那份判）。
- **交付**：评论 `/deliver <PR 链接或证据块>`。
- **等验收**：维护者按 §三 四闸裁决；通过后 `/settle` 入账。

## 七、超时回板（自动）

每 6 小时扫描一次：`bounty:claimed` 且已过 72 小时未交付 ⇒ 自动回板 `bounty:open`
（回评说明原持有者、到期时间与超期时长；记 −1）。任何人可重新认领。

## 八、账本收口（维护者看这一节）

workflow 只持 `issues: write` ＋ `pull-requests: read`（最小面），**不持** `contents: write`，
故它不自己提交账本；每次运行把本批事件写成 JSONL 挂 artifact（保留 90 天）。落地：

```bash
# 把 workflow 产出的 events.jsonl 并入公开账本（append-only、id 幂等）
python -X utf8 scripts/bounty_board.py --ledger-append <events.jsonl>

# 从账本重生成荣誉榜
python -X utf8 scripts/bounty_board.py --board-out docs/bounty/board.md
```

本地离线核验（**不触网**）：

```bash
# 一键演完整生命周期：认领 → 交付 → 验收 → 结算 ＋ 超时回板 ＋ 各拒绝面
python -X utf8 scripts/bounty_board.py --dry-run

# 状态机守卫（逐条判据 ＋ 定点变异自证）
python -X utf8 scripts/test_bounty_board.py
python -X utf8 scripts/test_bounty_board.py --mutate
```

## 九、诚实边界（v0.1 未做 / 待裁）

- **复现机器人尚未移植到本仓**（现只在身体仓）——「四闸②复现读数」当前靠人工贴读数。
- **认领门槛未设**：是否限「非本仓协作者」、并发上限取几，均待裁定（现缺省 2）。
- **声誉与跨端协作信任（认知图 trust 面）的联动**未接线（先落公开账本）。
- **结算动作是维护者手工触发**（`/settle`），未做自动结算。
- **`bounty:expired` 不驻留**、`disputed` 之后的状态复位（回 `delivered` / `claimed`）
  仍由维护者手改标签——两处口径待裁定后收口。
- **争议败诉的负分**未实现（记录在案、不扣本金）。
