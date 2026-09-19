# 缺陷与修正：lane 侧基线用「本地 main」，落后发布线 47 个提交 → 重复采集已覆盖符号

- 提出时间：2026-09-19 01:5x（环二第 536 轮）
- 处置：编外（本侧）自检 → 统一基线为 `origin/main` → 复测 → 提交本说明
- 状态：待编外复核（Zero-Trust）。

## 1. 缺陷

环二流水线的**采集/复核/插入**三处都以**本地 `main`** 为基线：

- `collect_files2.py`：`git archive ... main`（枚举「未覆盖符号」）
- `unit_review.py`：`git diff --name-only main <branch>`、`git show main:<path>`（算「本次新增条数」）
- `apply_batch.py`：`git show main:<path>`（插入前的内容）、`git rev-parse main`（候选分支父提交）

而落地环 `auto_land2.py` 一直以 `origin/main` 为准。二者不一致时：

实测（2026-09-19）：`dsh-memory` 工作树的**本地 `main` 落后 `origin/main` 47 个提交**
（`main=3e799cc` / `origin/main=eea105f`）。`compiler/name_checker.py` 本地 28 条、发布线 29 条。
于是 lane 把发布线上**早已覆盖**的符号当成缺口重新注释 → 候选分支到落地环
（按 `origin/main` 比对）必然 0 增量 → 判 `NO_INCREMENT/stale`（iter-namecheck-c1 实例）：
LLM 预算白烧一轮，且账面「无实际新增条件（已落实）」容易被误读成丢工作。

## 2. 修正

| 文件（`C:\Users\FuRongJun\.mdcg\_coord\`） | 修正 |
| --- | --- |
| `collect_files2.py` | 先 `git fetch origin main`，再以 `origin/main` 归档枚举 |
| `unit_review.py` | `diff` 与基线 `show` 全部改 `origin/main` |
| `apply_batch.py` | 插入内容与分支父提交改 `origin/main` |

未改落地环（原本即 `origin/main` 口径）——修正后两侧口径一致。

## 3. 实测

- `compiler/name_checker.py`：修正前 `COLLECT n=7`（本地基线），修正后 `COLLECT n=6`，
  与 `repo_gap.py` 的发布线口径 `gap=6` **完全一致**。
- 修复当轮 `CORE have 2319→2329`（gap 203→193）。

## 4. 复核（可复现）

```
cd D:/Program Files/2_ai/dsh-memory
git rev-list --count main..origin/main          # 期望 >0（证明本地 main 落后）
python -X utf8 C:/Users/FuRongJun/.mdcg/_coord/collect_files2.py \
  --files compiler/name_checker.py --n 60 --max-src 12000 --out <tmp>   # 期望 COLLECT n=6
```

## 5. 边界

- 本修正不改变「落地判据」：候选仍须过独立复核 ACCEPT + 零删除 + 干净树回归绿。
- 本地 `main` 落后属于工作树状态，本侧**不**对陈旧工作树做 `reset --hard`（避免误伤在途改动），
  而是在工具侧统一到发布线。
