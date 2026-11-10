# AGENTS.md — lingshu-src（灵枢地基分册）

> 这个块的读数与结构见 项目现状.md（scripts/项目现状.mjs 生成）。

灵枢真源码树、唯一地基：认知图的节点存储 / 语义时空图 / 一致性 / 元认知 / 出处链 / 加密。入口 `md_cg\mdcg.py`。

## 不许

- 本树是 clone 的上游只读存档：非编排任务明确授权不得改 md_cg 等源码；要改先用 `intake.mjs` note 记假设，再写进本次 run。
- **服务器上不许就地改 `md_cg`** —— 上线只有一条路：改本树 → `git commit` → `cd D:\wook && node scripts\deploy-mdcg.mjs`。判据见下节「权威侧」。根 `AGENTS.md` 硬规则 12。
- `_md_cg_p*`、`_md_cg_membench` 是库数据分片，不是源码，不得当源码改。
- 仓内既有 `codex/AGENTS.md`、`zcode/AGENTS.md` 一律不动。

## 权威侧（R-101 裁定，2026-11-10）

背景：2026-11-09 的 `dbc1aaa4`「服务器活体代码回流」一次改 1,034 个文件（943 改 + 91 新增，`.py` 538 → 626），把生产侧就地修改一次带入本树。此后「哪一侧为准」成为每次改动的第一问题。

**不整体裁定，按类别裁**：

| 类别 | 规则 | 依据 |
|---|---|---|
| 回流**新增**、本树历史从未有 | 以服务器为准 | 本树删了就丢功能（实测 37 个非测试文件，含 `bm25.py` / `op_table.py` / `idf.py`） |
| 回流**删除**、但本树有测试锚定 | 以本树为准恢复；恢复前先问「这接口还有用吗」 | 有测试 = 有可判定的契约 |
| 回流**覆盖**、两侧都有 | **设计意图优先于任一侧代码**；守卫只证「不一致」，不证「谁对」 | 见下两条实例 |
| 数据面（`_keys.json` / `_md_cg_p*`） | 以服务器为准 | 生产数据是唯一真源 |

两条已裁实例：

- **`crypto.load_master_key` → 以本树 E192 三态为准**（`1d9ed589`）。虽然回流把它改回 `create=True`，但那条修复是安全属性；而当时「有测试」并不站在回流那边 —— `test_p13_encryption` 的 B3 断言恰好是「文件不存在时自动生成」，即**测试在保护旧行为**。「有测试」不等于「测试对」。
- **`auto_scrub` / `auto_evolve` 缺省 → 以服务器侧 `True` 为准**。理由：工具面 schema（`mcp_server.py:929`）与模块自述（`sustain.py:31`「默认已改为 True」）两处都承认新值，陈旧的是两处内部注释与生成件。**有意的变更**优先于**陈旧的登记表**。

**部署判据（R-107b 修正）**：

```bash
# 旧判据（永久失效）：filemode=true 时 34 个 mode 位让 status 恒非空
ssh aliyun 'cd /home/ubuntu/mdcg && git status --porcelain'   # 曾经恒 38 行

# 已修：服务器 core.filemode=false，status 只剩未跟踪件；新判据看内容差异
ssh aliyun 'cd /home/ubuntu/mdcg && git diff --numstat | awk "{s+=\$1+\$2} END {print s+0}"'
# 期望 0 —— 这才是「无就地代码改动」的准判据（不受未跟踪件干扰）
```

**2026-11-10 全量核对读数**：626 个 `.py` 逐件 LF 归一 sha256 比对，两侧**仅 14 个不同**，且全部是当日修理改过的文件；其余 612 个逐位一致 ⇒ 当时服务器与本树在代码面**等集**。

### 回流删除的 5 个接口：逐个归属裁定

| 接口 | 本树历史 | 服务器现状 | 裁定 | 落地 |
|---|---|---|---|---|
| `crypto.tenant_actors` | `bdd44232` 引入 | **无** | 以本树为准恢复 | `crypto.py:501` |
| `signer.policy_source` | `d293921f` 引入 | **无** | 以本树为准恢复 | `signer.py:408` |
| `MdCGOS.fold_access_records` | `d293921f` 引入（原在 `mdcg.py` 的 `MdCG`） | **无** | 以本树为准恢复，落子类 | `mdcos.py:973` |
| `MdCGOS.list_nodes` | `d293921f` 引入 | **无** | 以本树为准恢复，落子类 | `mdcos.py:935` |
| `sleep.wired_steps` | **两侧历史均无** | **无**（仍是「未接线」占位，`grep -c` = 0） | **不是恢复，是按测试规格新实现** | `sleep.py::wired_steps` |

前 4 个是「回流删了、本树历史有 ⇒ 恢复」。第 5 个不同：`test_t91a_sleep_wiring`（64 条断言）先于任何实现落地，两侧都没有 `def wired_steps` ⇒ 本树按测试规格反向构造了一份，**它修掉的是审计 P2「⑤⑥ 显式 no-op 占位」**，docstring 已写明来源、裁决依据与「若服务器真实现回流则以它为准」。
