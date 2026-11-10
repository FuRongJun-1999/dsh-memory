# -*- coding: utf-8 -*-
"""R-205 / P0-6 探针：`forgetting._prune` 删长期断面快照必须留下被删名单。

缺陷本体：`_prune` 是全仓**唯一一条没有回收站兜底的不可逆删除** —— 它删的是
`_longterm/*.jsonl` 断面（那是**当时读数**，事后不可重建），而 `_maintain.jsonl`
写的那一条**不含被删名单** ⇒ 一次 prune 之后无法知道删了哪几个。

三闸（每闸都断言「读数」而不只是「不抛异常」）：
  G1 正控（判据）：造一个含 N 个超龄断面快照的库 → 跑一次 apply 的
     `longterm_assess(keep=K)` ⇒ `_maintain.jsonl` 最后一条 `action=longterm`
     记录含 `pruned` 数组，`len(pruned) == N`，且 `pruned` 里每个名字在盘上
     确实已不存在。
  G2 负控：把 `pruned` 字段删掉 ⇒ 判据必须红。两条腿：
     ① **代码路径级**：把写入器的 rec 里 `pruned` 摘掉再落盘（走真实现），
        台账因此不含名单 ⇒ 判据必红；
     ② **判据自身有牙**：`pruned` 指向盘上仍在的文件 / `len` 少一个 ⇒ 各自必红。
  G3 删失败不静默：占住一个超龄断面（Windows 独占打开 ⇒ `os.remove` 抛
     OSError）⇒ 它进 `prune_failed`、不进 `pruned`，且盘上仍在。平台允许删除
     被打开的文件（POSIX 语义）时打印 SKIP 原因，不静默跳过。

用法：`python -X utf8 -m md_cg.test_prune_ledger`（独立临时根，重跑 ≡ 首跑）
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

# 本探针审的就是 `forgetting._prune` 这个内部口本身（负控要拦它的写入器），
# 与 test_p9_forget_protect / test_p30_maintain 同款直连；生产代码仍只走公开 op。
from . import corpus, forgetting  # noqa: TID251
from .mdcos import MdCGOS
from .security import Principal

PASS = FAIL = SKIP = 0
FAILS = []

#: 造几个「超龄」断面；keep=1 ⇒ 它们应被整批删掉，len(pruned) 必须 == N。
N = 7
KEEP = 1

PROBE_DOC = ("# 功能名：断面台账探针\n# 生效条件：造库探针\n"
             "# 子功能：给断面提供非空行数\n# 执行：落两条节点\n"
             "# 不适用条件：无\n")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def skip(name, why):
    global SKIP
    SKIP += 1
    print(f"  [SKIP] {name}  · {why}")


def _new_lib(tag):
    """独立临时库（独立 root，重跑 ≡ 首跑）。"""
    tmp = tempfile.mkdtemp(prefix=f"mdcg_prune_{tag}_")
    root = os.path.join(tmp, "root")
    corpus.reset_root(root)
    cg = MdCGOS(root, actor="prune_probe")
    cg.principal = Principal(tenant="default", actor="prune_probe",
                             clearance="internal", can_write=True,
                             can_admin=True, role="designer")
    for i in range(2):
        cg.add(f"prune_probe_{i}", PROBE_DOC, layer="knowledge")
    cg.flush()
    return root, cg


def _seed_old_snapshots(root, n):
    """预置 n 个「超龄」断面（文件名时间前缀 2020…，必排在今天的断面之前）。"""
    d = os.path.join(root, forgetting.LONGTERM_DIR)
    os.makedirs(d, exist_ok=True)
    names = []
    for i in range(n):
        name = f"20200101-0000{i:02d}-dead{i:04d}.jsonl"
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            f.write(json.dumps({"t": 0, "id": f"old_{i}", "layer": "knowledge"},
                               ensure_ascii=False) + "\n")
        names.append(name)
    return names


def _last_record(root, action="longterm"):
    """读 `_maintain.jsonl` 里最后一条 action 记录（读的就是被审的那份盘上产物）。"""
    p = os.path.join(root, forgetting.MAINTAIN_LOG)
    recs = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    recs.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return None
    hits = [r for r in recs if isinstance(r, dict) and r.get("action") == action]
    return hits[-1] if hits else None


def judge(rec, root, expect_n):
    """**判据本体**（G1 与全部负控共用这一份，防止负控判的是别的代码）。

    ① 记录必须带 `pruned` 且是数组；
    ② `len(pruned)` 必须等于实际删除数；
    ③ 名单里每个名字在盘上必须确实已不存在。
    返回 (ok, detail)。
    """
    if not isinstance(rec, dict) or rec.get("action") != "longterm":
        return False, "没有 action=longterm 的台账记录"
    if "pruned" not in rec:
        return False, "台账记录缺 pruned 字段（事后无法知道删了哪几个）"
    names = rec.get("pruned")
    if not isinstance(names, list):
        return False, f"pruned 不是数组：{type(names).__name__}"
    if len(names) != expect_n:
        return False, f"len(pruned)={len(names)} != 实际删除数 {expect_n}"
    d = os.path.join(root, forgetting.LONGTERM_DIR)
    still = [x for x in names
             if os.path.exists(os.path.join(d, str(x)))]
    if still:
        return False, f"名单里的断面在盘上仍存在：{still}"
    return True, f"pruned={names}"


def _disk_snapshots(root):
    d = os.path.join(root, forgetting.LONGTERM_DIR)
    try:
        return sorted(x for x in os.listdir(d) if x.endswith(".jsonl"))
    except OSError:
        return []


def main():
    print("=" * 70)
    print("R-205 / P0-6 · forget._prune 删除必须留名单（三闸）")
    print("=" * 70)

    # ------------------------------------------------ G1 正控
    print(f"\n【G1】判据：{N} 个超龄断面 + keep={KEEP} ⇒ 台账 pruned 长度 {N}，名单上盘面已删")
    root, cg = _new_lib("pos")
    seeded = _seed_old_snapshots(root, N)
    res = forgetting.longterm_assess(cg, apply=True, keep=KEEP, actor="prune_probe")
    rec = _last_record(root)
    ok, detail = judge(rec, root, N)
    check("G1 台账含 pruned 数组，len==N，且名单上每个文件盘上确已不存在",
          ok, detail)

    left = _disk_snapshots(root)
    check(f"G1 盘面读数：只剩 keep={KEEP} 个断面（本次新写的那个）",
          len(left) == KEEP, f"盘上={left}")
    check("G1 台账名单 == 盘上真正消失的那批（逐名比对，非只比值）",
          set(rec.get("pruned") or []) == set(seeded) - set(left),
          f"台账={sorted(rec.get('pruned') or [])} 实删={sorted(set(seeded) - set(left))}")
    check("G1 返回体与台账同口径（pruned 逐项相等）",
          list(res.get("pruned") or []) == list(rec.get("pruned") or []),
          f"返回体={res.get('pruned')}")
    check("G1 无删失败时 prune_failed 为空数组（字段恒存在，不省略）",
          rec.get("prune_failed") == [] and res.get("prune_failed") == [],
          f"台账={rec.get('prune_failed')!r} 返回体={res.get('prune_failed')!r}")
    check("G1 dry-run 不写台账（对照：预演面不产生假名单）",
          len(_disk_snapshots(root)) == KEEP
          and forgetting.longterm_assess(cg, apply=False, keep=KEEP,
                                         actor="prune_probe").get("pruned") == [])

    # ------------------------------------------------ G2 负控
    print("\n【G2】负控：把 pruned 字段删掉 ⇒ 判据必须红")
    root2, cg2 = _new_lib("neg")
    _seed_old_snapshots(root2, N)
    _orig_append = forgetting.append_jsonl

    def _strip_pruned(path, record):
        # 模拟「修之前」的台账：写入时就没有 pruned 这一栏（走真实现，不改源码文件）
        if isinstance(record, dict) and record.get("action") == "longterm":
            record = {k: v for k, v in record.items() if k != "pruned"}
        return _orig_append(path, record)

    forgetting.append_jsonl = _strip_pruned
    try:
        forgetting.longterm_assess(cg2, apply=True, keep=KEEP, actor="prune_probe")
    finally:
        forgetting.append_jsonl = _orig_append
    rec2 = _last_record(root2)
    check("G2a 负控·代码路径级：写入器摘掉 pruned ⇒ 同一条判据必红",
          not judge(rec2, root2, N)[0], judge(rec2, root2, N)[1])
    check("G2a 前提自证：该次 prune 确实删了 N 个（红是因为没名单，不是因为没删）",
          len(_disk_snapshots(root2)) == KEEP
          and not rec2.get("pruned"),
          f"盘上={_disk_snapshots(root2)} 台账 pruned={rec2.get('pruned')!r}")

    fake_present = {"action": "longterm", "pruned": [left[0]] if left else ["x.jsonl"]}
    check("G2b 负控·判据有牙（第三条）：pruned 指向盘上仍在的文件 ⇒ 必红",
          not judge(fake_present, root, 1)[0], judge(fake_present, root, 1)[1])

    short = {"action": "longterm", "pruned": list(rec.get("pruned") or [])[:-1]}
    check("G2c 负控·判据有牙（第二条）：len(pruned) 少一个 ⇒ 必红",
          not judge(short, root, N)[0], judge(short, root, N)[1])

    # ------------------------------------------------ G3 删失败不静默
    print("\n【G3】删失败不静默：占住一个超龄断面 ⇒ 进 prune_failed，不进 pruned")
    root3, cg3 = _new_lib("lock")
    seeded3 = _seed_old_snapshots(root3, N)
    victim_name = seeded3[0]                      # 最旧的那一个，必在删除集里
    victim = os.path.join(root3, forgetting.LONGTERM_DIR, victim_name)
    fh = open(victim, "rb")                       # Windows：不带 FILE_SHARE_DELETE
    try:
        res3 = forgetting.longterm_assess(cg3, apply=True, keep=KEEP,
                                          actor="prune_probe")
    finally:
        fh.close()
    rec3 = _last_record(root3)
    if os.path.exists(victim):
        check("G3 删失败的文件进 prune_failed（不静默 pass）",
              victim_name in (rec3.get("prune_failed") or []),
              f"prune_failed={rec3.get('prune_failed')}")
        check("G3 删失败的不进 pruned（名单只说真删掉的）",
              victim_name not in (rec3.get("pruned") or []),
              f"pruned={rec3.get('pruned')}")
        check(f"G3 pruned 长度 == 实际删除数 {N - 1}",
              len(rec3.get("pruned") or []) == N - 1,
              f"len={len(rec3.get('pruned') or [])}")
        check("G3 返回体同样带 prune_failed（不只台账里有）",
              victim_name in (res3.get("prune_failed") or []),
              f"返回体={res3.get('prune_failed')}")
        check("G3 判据整体仍成立（成立的是删成的那批）",
              judge(rec3, root3, N - 1)[0], judge(rec3, root3, N - 1)[1])
    else:
        skip("G3 删失败路径", "本平台允许删除被打开的文件（POSIX 语义），"
                              "无法构造 os.remove 的 OSError")

    # ------------------------------------------------ 汇总
    print("\n" + "=" * 70)
    print(f"结果：{PASS} 通过 / {FAIL} 失败 / {SKIP} 跳过")
    if FAILS:
        print("失败清单：" + "；".join(FAILS))
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
