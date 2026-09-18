# 缺陷与修正：多端协调账本写路径崩溃 + 终态被并发覆盖

- 提出时间：2026-09-19 01:2x（环二第 534 轮）
- 处置：编外（本侧）自检 → 修正 `_coord/multiport.py` 写账 → 恢复 26 行被覆盖的 landed 记录 → 提交台账与本说明
- 状态：待编外复核（Zero-Trust）。

## 1. 缺陷 A：写账直接崩溃（KeyError: 1）

`multiport.load()` 用 `csv.DictReader` 返回 **dict** 行，而 `save()` 按 **list** 行处理
（`p[1]` 取 iter）。因此任何写账命令都抛 `KeyError: 1`：`sweep` / `offer` / `dispatch` /
`supersede`。实测证据（sweep 循环 stderr 反复出现）：

```
KeyError: 1
KeyError: 1
```

后果：契约 §2–§5 的**认领 / 升级 / 投放 / 取代**状态从未落账（sweep 每次要写就崩，
`changed>0` 时才调用 `save`，所以表面上只看到「SWEEP offered=0 …」）。

## 2. 缺陷 B：终态被并发陈旧快照覆盖

`sweep`（每 60s）与落地环 `auto_land2`（每 120s）并发读-改-写同一份账本，二者都是
「读全表 → 改本进程关心的行 → 合并写」。sweep 在 T0 读到的 `offered` 会在 T2 覆盖落地环
T1 写入的 `landed` → 落地环下一轮重读该行（非终态）→ 重放候选 → `NO_INCREMENT` → 写成
`stale`。

实测：**26 行**「校验和落地」提交在 `origin/main` 中存在，账面却是 `stale/无实际新增条件`
（例：`iter-genspecs-c1-fix` ↔ 提交 `95bac64`；`iter-mdcos-c1` 落地后 6 秒被写成 stale）。

## 3. 修正（`C:\Users\FuRongJun\.mdcg\_coord\multiport.py`）

1. `_as_dict(r)`：dict / list 两种行格式归一化（根因消除，写路径不再崩）。
2. `save()` 终态保护：磁盘行为 `landed` / `checksum-failed` / `stale` / `superseded` 时，
   本进程的陈旧快照不得把它改回 `claimed` / `offered` / `escalated`；`landed` 另加反降级。
3. `_orig_save()` 统一走 `_as_dict`，并设 `lineterminator="\n"`（原默认 CRLF，会把全表
   行尾改掉 → 非幂等）。

同轮在 `auto_land2.save()` 加同一道终态保护（落地环侧）。

## 4. 实测（修正后）

- `multiport.py sweep`：不再抛 `KeyError`，`SWEEP offered=0 escalated=0 claimed=0`，账本不变。
- 写路径幂等：`save(load())` 前后**字节相同**（`sha256[:12]=4d905a0e803b`，42591 字节）。
- 终态保护用例：伪造「磁盘 landed + 本进程 stale」→ 落盘仍为 `landed`（PASS）。
- 账本对账：恢复 26 行 `landed`；当前 `landed=96 / stale=192 / superseded=8 / internal-verified=1`（共 297 行）。

## 5. 边界

- 终态保护只阻止**降级**，不阻止合法的终态推进（`offered → claimed → landed`）。
- `landed` 的判定依据是 `origin/main` 中「校验和落地 <iter>（+N 条）」提交：**有提交才算落地**，
  本侧不据自我声明改账。
