# experiments/handoff · persona_v1

> 人格化验证实验（2026-11-19）的完整材料：预注册、60 份样本、盲评包、交接文档、更正记录。
> **本目录下的样本已做本机路径清洗**（`<目标仓>` / `<本仓>` / `<评审区>` / `<用户目录>`），
> 其余内容逐字保留；S 文件与 `artifacts/persona_v1/*.json` 的 `text` 仍一一对应（已核 60/60）。

## 文件

| 文件 | 说明 |
|---|---|
| `../specs/persona_v1.json` | **预注册**：判据、阈值、决策规则（跑之前写死） |
| `persona_v1_handoff.md` | 交接文档（给复测方；含操作方法与已知坑） |
| `persona_v1_correction.md` | **更正记录**：我给出的两条结论被复测方推翻，此处如实留存 |
| `blind/S001–S060.md` | 去标识输出（每题面 + 输出） |
| `blind/_MAP_DO_NOT_SHARE.csv` | SID → 臂/任务/重复（**评分者不得打开**） |
| `blind/_SCORE_SHEET.csv` | 独立评分者填写的 J2/J4（60 行全填） |

原始样本在 `artifacts/persona_v1/`（可用 `scripts/exp_runner.py` 重跑生成）。

## 复现

```cmd
set PYTHONUTF8=1
python -X utf8 scripts\exp_runner.py --spec experiments\specs\persona_v1.json ^
  --repo-root <目标仓根> --out artifacts\persona_v1 ^
  --hive-bin <hive.exe> --hive-jobs <hive/jobs>
python -X utf8 scripts\exp_score.py --dir artifacts\persona_v1
python -X utf8 scripts\exp_blind.py --dir artifacts\persona_v1 --out experiments\handoff\blind
```

## 结果摘要（**以更正后的为准**）

机判（60/60 done）：

| 臂 | n | J1 | J3 | 催稿段 | 条款引用 | 平均字数 |
|---|---|---|---|---|---|---|
| instr_ctx | 15 | 14/15 | 7/15 | 0/15 | 5 | 3863 |
| instr_noctx | 15 | 15/15 | 7/15 | 0/15 | 0 | 1959 |
| plain_ctx | 15 | 12/15 | 4/15 | 0/15 | 1 | 2431 |
| plain_noctx | 15 | 1/15 | 5/15 | 0/15 | 0 | 822 |

独立盲评（J2 取舍说明 / J4 可用度，满分各 2）：

| 臂 | J2 满分 | J4 满分 |
|---|---|---|
| instr_ctx | 15/15 | 15/15 |
| instr_noctx | 15/15 | 12/15 |
| plain_ctx | 12/15 | 15/15 |
| plain_noctx | 0/15 | 6/15 |

## 结论（已按复测修正）

```
可支撑  J1 由「附加指示 × 上下文可得性」共同驱动（两者都缺才塌到 1/15）
可支撑  J2 由「指示」或「上下文」任一触发即可（两者都无 = 0/15）
可支撑  J4 主要受材料可得性驱动（材料依赖任务无上下文即 0/3）
可支撑  J6 无编造：30 份无上下文样本，目标仓关键词平均 0.0 个/份
不支撑  「催稿段 0/60 = 不会催稿」——本批全是单轮短任务，未进发病环境
不支撑  「人格化 vs 教条化」总判断——无隔离单因素条件，每因素仅 n=30
```

## 一句提醒

**不要把这里的任何一条当结论引用前，先读 `persona_v1_correction.md`。**
我在这批数据上错了两次（判据当答案、结论与自己的表格矛盾），
错的那一版保留在交接文档第 4 节，没有删。
