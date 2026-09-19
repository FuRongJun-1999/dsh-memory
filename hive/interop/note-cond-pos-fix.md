# 缺陷与修正：生效条件注释的「锚点口径」不一致（装饰器之下 vs 装饰器之上）

- 提出时间：2026-09-19 01:0x（环二第 533 轮）
- 处置：编外（本侧）自检发现 → 修正检查器口径 → 重测 → 提交台账与本说明
- 状态：待编外复核（Zero-Trust）。复核对象＝本说明的可复现数字，不是本侧的自我声明。

## 1. 缺陷（一句话）

注释的**插入位置**是「紧贴 `def`/`class` 行正上方（装饰器之下）」，但多个**检查器**
用的是 `first = min([node.lineno, *装饰器行])` 并只从 `first` 往上扫 —— 对带装饰器的
符号，注释实际落在 `first` **下方**，检查器看不到它。

## 2. 三处后果

1. **缺口虚高**：`CORE` 中 28 个「已带注释」的带装饰器符号被计为缺口。
   （实测：`gap=275` 为装饰器口径；规范口径为 `gap=247`。）
2. **复核包漏项**：`unit_review` 用同一锚点收集「本次新增条件」，带装饰器符号整条
   落不进复核包 → `PKG` 虚增（把已入库条件算成新增）或 `EMPTY_PACKAGE`（真新增却不成包）。
   实测：分支 `task/iter-test-hive` 上旧口径 `PKG=14`，规范口径 `PKG=0`（14 条早已在 main）。
3. **漂移误判**：`auto_land2.func_span` 的区间从装饰器行起，注释落在区间**内**，
   候选与 main 的代码段必然不等 → 带装饰器符号一律 `DRIFTED` 而永不落地。

## 3. 修正（口径统一为规范位置，并兼容旧位置）

判据（双锚点）：先按 `node.lineno`（def/class 行）向上扫 3 行，未命中再按装饰器行向上扫 3 行；
向上扫遇非注释非空行即停。写入锚点统一为 `node.lineno`。

| 文件（`C:\Users\FuRongJun\.mdcg\_coord\`） | 修正 |
| --- | --- |
| `repo_gap.py` | `has_cond` 双锚点（缺口口径） |
| `blindspot_ledger.py` | 覆盖/不适用判定双锚点 |
| `unit_review.py` | 收集双锚点；`src_segment` 起点取 `min(注释行, 装饰器行)`，确保注释在包内 |
| `auto_land2.py` | `collect` 双锚点；`func_span` 剔除注释行；`def_line` 返回 def/class 行 |
| `stalled_gap.py` / `diag_unit.py` / `auto_close.py` / `mark_na_symbols.py` / `ring2_batch.py` | 同口径（诊断与标记） |
| `collect_files2.py` / `apply_batch.py` / `pos_check.py` | 无需改（原本即规范口径，是本次的基准） |

## 4. 实测（修正前 → 修正后，均以 `origin/main` 归档为输入）

- `CORE symbols=2522 have=2247 gap=275` → `have=2275 gap=247`
- 停滞台账 `UNCOVERED 292 {active:91, stalled-anchorless:109, stalled-other:92}`
  → `UNCOVERED 244 {active:47, stalled-anchorless:105, stalled-other:92}`
- `NA_MARKS(不适用) 28`（不变：修正未改变真实已注释的判定，只纠正误报）

## 5. 独立复核（不依赖本侧脚本）

```python
# 期望输出: decorator-rule=275  canonical-rule=247  missed=28
import ast, io, os, subprocess, tarfile, tempfile
R = r'D:/Program Files/2_ai/dsh-memory'
ar = subprocess.run(['git','-C',R,'archive','--format=tar','origin/main'], capture_output=True)
t = tempfile.mkdtemp(); tarfile.open(fileobj=io.BytesIO(ar.stdout)).extractall(t)
def cov(lines, node, dec_rule):
    first = min([node.lineno] + [d.lineno for d in getattr(node,'decorator_list',[])])
    anchors = [first] if dec_rule else [node.lineno, first]
    for a in anchors:
        for back in range(1,4):
            i = a-1-back
            if i < 0: break
            if lines[i].startswith('# 生效条件：'): return True
            if lines[i].strip() and not lines[i].startswith('#'): break
    return False
tot=a=b=0
for base,dirs,names in os.walk(t):
    dirs[:] = [d for d in dirs if d not in ('__pycache__','.git','whitebox_kb','target','node_modules')]
    for fn in names:
        if not fn.endswith('.py'): continue
        rel = os.path.relpath(os.path.join(base,fn), t).replace(os.sep,'/')
        if '/tests/' in rel or os.path.basename(rel).startswith('test_') or '/test_' in rel: continue
        try: src = io.open(os.path.join(base,fn), encoding='utf-8', errors='replace').read(); tree = ast.parse(src)
        except Exception: continue
        L = src.split(chr(10))
        for n in ast.walk(tree):
            if not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)): continue
            tot += 1; a += cov(L,n,True); b += cov(L,n,False)
print('decorator-rule=%d canonical-rule=%d missed=%d symbols=%d' % (tot-a, tot-b, b-a, tot))
```

## 6. 边界（不适用于本修正的条件）

- 若注释被插到装饰器**之上**（历史旧位置），修正后的双锚点在第二锚点仍能命中，故台账数字
  不会因旧位置而失真；但**新**写入一律用规范位置，故旧位置只会随落地逐步消失。
- 本修正只改口径与工具，不改任何被注释代码：因此不产生新的生效条件条目，
  `CORE gap` 的下降全部来自「误报纠正」，**不是**新增注释。
