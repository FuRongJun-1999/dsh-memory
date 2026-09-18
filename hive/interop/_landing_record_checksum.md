# 环二落地记录 · 代码版 TCP 校验和（机生成）

落地提交：85e478a（整体可 revert 作回滚点）
时间：2026-09-18T17:51:37

## 校验和判据（用户 2026-09-18 裁定：代码版 TCP 校验方式）

1. **内部独立复核 verdict=ACCEPT**（自足式内联复核，双向独立，非自证）
2. **零冲突**：close_generic dry-run 得 inter=[]（与当前 main 无同文件交叉改动）
3. **零删除 + 测试绿**：候选 diff 无删除；受影响测试组回归通过

语义边界（如同 TCP 校验和只管传输完整性、不管语义）：校验和通过 ≠ 不再复核；落地后保留可 revert 点，外部回执到达后仍按 §3 并账；若外部判 REJECT，回滚对应落地提交并重开候选。

## 本轮结果

- 30/30 候选通过校验和（失败 0）
- 18 个文件、**+137 行**（纯新增注释行，无删除）
- 回归：compiler 8/8、hive 5/5、md_cg 88/88（3 跳过）、scripts 2/2全绿
- 同函数多候选冲突 86 处，按「后批次胜」归并（后批次基于更新文件状态生成且经独立复核）
- 口径：清洁 checkout（origin/main）下 count_marks.py = 1341 marks / 89 文件（本次 +137）

## 已落地候选（30）

- iter-027-batch-c11
- iter-104-batch-c104-fix-d1
- iter-167-batch-c167-fix
- iter-168-batch-c168-fix
- iter-209-batch-c209
- iter-210-batch-c210-fix
- iter-211-batch-c211
- iter-212-batch-c212
- iter-213-batch-c213
- iter-214-batch-c214
- iter-215-batch-c215-fix
- iter-216-batch-c216-fix-d1
- iter-217-batch-c217
- iter-218-batch-c218
- iter-219-batch-c219-fix
- iter-220-batch-c220
- iter-221-batch-c221-fix
- iter-222-batch-c222-fix
- iter-223-batch-c223
- iter-224-batch-c224
- iter-225-batch-c225-fix
- iter-226-batch-c226-fix
- iter-227-batch-c227
- iter-228-batch-c228
- iter-230-batch-c230
- iter-231-batch-c231-fix
- iter-232-batch-c232
- iter-115-batch-c115-fix-d1-dual
- iter-142-batch-c142-fix-d1-d2-dual
- iter-172-batch-c172-fix-d1-dual
