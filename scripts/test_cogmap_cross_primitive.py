# -*- coding: utf-8 -*-
"""test_cogmap_cross_primitive —— N262 守卫：cogmap_sync._check_doc 的 op 引用校验
「按基元各用各集合」（cg 引用只认 cg_ops；stg 引用只认 stg_ops）。

背景（判据名不副实）：check 门禁的文案写着「引用了不存在的 cg/stg op」，但实现曾把
`valid_ops = set(cg_ops) | set(stg_ops)` 一个并集同时喂给两个循环 ⇒
`cg(op=<仅 stg 面的 op>)` 与 `stg(op=<仅 cg 面的 op>)` 这类**跨基元误引**零报错通过。
N262 修复：两循环各用各自集合；本守卫把三态行为钉死。

断言面（函数级直调 _check_doc；合成 e：cg_ops 与 stg_ops 各含对方没有的 op；
不读真源 mcp_server.py、不写任何工作区文件）：
  前提   被测实现可加载、_check_doc 可调用（合成夹具下不抛异常）
  L1     cg 引 stg-only（cg(op=relation)）→ 报错恰 1 条且点名「不存在的 cg op」
  L2     stg 引 cg-only（stg(op=route)）→ 报错恰 1 条且点名「不存在的 stg op」
  L3     合法引用（cg(op=route) + stg(op=relation)，各在自己基元集合内）→ 零错误
         （集合接反 / 过紧回退——把合法引用也判错——会在本腿现形）

红机制（本守卫对缺陷实现必红；两条通道互相独立）：
  ① --impl head：物化 HEAD 版 cogmap_sync.py 到临时副本喂同一套断言——HEAD 仍含
     缺陷时 L1/L2 必 FAIL（红基线可复现）；HEAD 已含修复时 L1/L2 转绿（提示
     「修复已入库」）。
  ② --mutate：把工作树实现的修复点逐处做**定点文本变异**（并集回退：cg 面 / stg 面 /
     双面原缺陷形态），对每个变异副本跑同一套断言——「该判据空转」即失败；
     锚点找不到 = ANCHOR-MISS 退出码 2（fail-closed，实现改了却没同步变异表即硬失败）。
     变异副本一律写入守卫的临时目录，绝不覆盖工作区文件。

用法（任意 cwd；实现/仓库由本文件位置定位）：
  python -X utf8 scripts/test_cogmap_cross_primitive.py               # 测工作树版
  python -X utf8 scripts/test_cogmap_cross_primitive.py --impl head   # 红基线：HEAD 版
  python -X utf8 scripts/test_cogmap_cross_primitive.py --impl <path> # 指定实现副本
  python -X utf8 scripts/test_cogmap_cross_primitive.py --mutate      # 定点变异自证
退出码：0 = 全绿 / 变异自证 PASS；1 = 有失败（含「变异仍全绿」）；2 = ANCHOR-MISS。
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEFAULT_IMPL = os.path.join(HERE, "cogmap_sync.py")

# 合成夹具：cg_ops 与 stg_ops 各含对方没有的 op（判据只看集合归属，不看数量）。
CG_ONLY = "route"      # 仅 cg 面
STG_ONLY = "relation"  # 仅 stg 面


# 生效条件：path 是可加载的 .py 实现时经 importlib 直载并返回模块对象（不注册 sys.modules、不触发 __main__ 分支）；不可加载时抛 RuntimeError；
def _load(path, name):
    """importlib 直载实现副本（不注册 sys.modules，不触发 main）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载实现：%s" % path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 生效条件：无入参；返回合成真源口径 e——cg_ops 含 CG_ONLY、stg_ops 含 STG_ONLY、其余面给最小空面；该 e 下 _check_doc 只应产出 op 引用面错误；
def _fixture_e():
    """合成真源口径 e：cg_ops 与 stg_ops 各含对方没有的 op；其余面给最小空面。"""
    return {"cg_ops": [CG_ONLY], "stg_ops": [STG_ONLY], "mdcg_tools": [], "op_modules": {}}


# 生效条件：mod 含 _check_doc 时对其直调三态（L1/L2 跨基元误引、L3 合法引用），返回 [(名称, ok, detail)] 列表；mod 缺 _check_doc 或任一态调用抛异常时对应项记 ok=False（不逃逸异常）；
def _suite(mod):
    """对被测实现跑三态，返回 [(名称, ok, detail)]。"""
    out = []
    if not hasattr(mod, "_check_doc"):
        out.append(("P0 _check_doc 可调用", False, "实现缺 _check_doc"))
        return out

    def _errs(text):
        return mod._check_doc(_fixture_e(), "夹具", text, [], "")

    try:
        errs = _errs("样例：cg(op=%s) 为跨基元误引" % STG_ONLY)
        ok = (len(errs) == 1
              and ("不存在的 cg op" in errs[0])
              and ("cg(op=%s)" % STG_ONLY) in errs[0])
        out.append(("L1 cg 引 stg-only → 报错点名 cg(op=%s)" % STG_ONLY, ok,
                    "errors=%d %r" % (len(errs), errs[:2])))
    except Exception as exc:                                    # noqa: BLE001
        out.append(("L1 cg 引 stg-only → 报错点名", False, "异常：%r" % (exc,)))

    try:
        errs = _errs("样例：stg(op=%s) 为跨基元误引" % CG_ONLY)
        ok = (len(errs) == 1
              and ("不存在的 stg op" in errs[0])
              and ("stg(op=%s)" % CG_ONLY) in errs[0])
        out.append(("L2 stg 引 cg-only → 报错点名 stg(op=%s)" % CG_ONLY, ok,
                    "errors=%d %r" % (len(errs), errs[:2])))
    except Exception as exc:                                    # noqa: BLE001
        out.append(("L2 stg 引 cg-only → 报错点名", False, "异常：%r" % (exc,)))

    try:
        errs = _errs("样例：cg(op=%s) 与 stg(op=%s) 均合法" % (CG_ONLY, STG_ONLY))
        out.append(("L3 合法引用（各在自己基元集合内）→ 零错误", errs == [],
                    "errors=%d %r" % (len(errs), errs[:2])))
    except Exception as exc:                                    # noqa: BLE001
        out.append(("L3 合法引用 → 零错误", False, "异常：%r" % (exc,)))
    return out


# 生效条件：逐条打印 results 的 PASS/FAIL（失败附 detail，截断 300 字符），返回失败项名称列表；
def _print_results(results):
    fails = []
    for name, ok, detail in results:
        print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                               "" if ok else "  " + str(detail).replace("\n", " | ")[:300]))
        if not ok:
            fails.append(name)
    return fails


# 生效条件：加载 impl_path 跑三态断言并打印（impl_label 注明实现来源）；有失败打印红项说明并返回 1，全过返回 0；
def _run_mode(impl_path, impl_label):
    print("被测实现：%s（%s）" % (impl_path, impl_label))
    fails = _print_results(_suite(_load(impl_path, "cogmap_guard_impl")))
    if fails:
        print("\nN262 守卫：%d 项断言失败（L1/L2 红 = 跨基元误引未被抓住——缺陷实现）"
              % len(fails))
        return 1
    print("\nN262 守卫：全部通过（cg/stg 引用各按各自集合校验）")
    return 0


# 生效条件：在 REPO 下取 git show HEAD:scripts/cogmap_sync.py，rc=0 且输出非空时写入 tmp 下 cogmap_sync_head.py 并返回 (路径, "")；否则返回 (None, 原因串)；
def _materialize_head(tmp):
    """物化 HEAD 版 scripts/cogmap_sync.py（红基线取用）。"""
    r = subprocess.run(["git", "-c", "core.quotepath=false", "show",
                        "HEAD:scripts/cogmap_sync.py"],
                       cwd=REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0 or not (r.stdout or "").strip():
        return None, ("git show 失败 rc=%s %s"
                      % (r.returncode, (r.stderr or "").strip()[:200]))
    p = os.path.join(tmp, "cogmap_sync_head.py")
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(r.stdout)
    return p, ""


# ================================================================ 定点变异表
# 每条 = (名称, [(锚点, 替换文本), ...], 预期红项数)。
# 锚点必须逐字命中当前工作树实现（找不到 → ANCHOR-MISS → 退出码 2，fail-closed）。
# 预期红项数：单面回退（cg 或 stg）只让对应跨基元态失守 ⇒ 红 1；双面回退 = 原缺陷
# 形态（一个并集同服两循环）⇒ L1/L2 双红。
_MUTATIONS = (
    ("并集回退·cg 面（cg 校验改用 cg_ops|stg_ops）",
     [('set(_CG_OP_RE.findall(text)) - set(e["cg_ops"])',
       'set(_CG_OP_RE.findall(text)) - (set(e["cg_ops"]) | set(e["stg_ops"]))')], 1),
    ("并集回退·stg 面（stg 校验改用 cg_ops|stg_ops）",
     [('set(_STG_OP_RE.findall(text)) - set(e["stg_ops"])',
       'set(_STG_OP_RE.findall(text)) - (set(e["cg_ops"]) | set(e["stg_ops"]))')], 1),
    ("并集回退·双面（原缺陷形态：一个并集同服两循环）",
     [('set(_CG_OP_RE.findall(text)) - set(e["cg_ops"])',
       'set(_CG_OP_RE.findall(text)) - (set(e["cg_ops"]) | set(e["stg_ops"]))'),
      ('set(_STG_OP_RE.findall(text)) - set(e["stg_ops"])',
       'set(_STG_OP_RE.findall(text)) - (set(e["cg_ops"]) | set(e["stg_ops"]))')], 2),
)


# 生效条件：读工作树实现源码，逐条对变异表做定点文本替换（每步要求锚点恰命中 1 次）写入临时目录副本并就副本跑三态套件：锚点未命中记 ANCHOR-MISS、红项数不等于预期记 MISMATCH；有 ANCHOR-MISS 时返回 2，否则有 MISMATCH 或未变异基线失败返回 1，全好返回 0；
def _mutate_mode():
    print("!! 定点变异自证：逐处把修复点改回「并集回退」缺陷形态，套件必须按预期条数转红\n")
    with open(DEFAULT_IMPL, encoding="utf-8") as fh:
        src = fh.read()
    anchor_miss, bad = [], []

    n_base = len([n for n, ok, _ in _suite(_load(DEFAULT_IMPL, "cogmap_mut_base")) if not ok])
    print("  未变异基线：红项=%d（必须为 0）" % n_base)
    if n_base:
        bad.append("未变异基线即失败")

    with tempfile.TemporaryDirectory(prefix="n262_mut_") as tmp:
        for idx, (name, subs, expect) in enumerate(_MUTATIONS, 1):
            text, miss = src, []
            for old, new in subs:
                if text.count(old) != 1:
                    miss.append(old)
                    continue
                text = text.replace(old, new, 1)
            if miss:
                anchor_miss.append(name)
                print("  ANCHOR-MISS %s —— 锚点不在当前源码逐字命中（恰 1 次）：%s"
                      % (name, "；".join(miss)))
                continue
            path = os.path.join(tmp, "mut_%d.py" % idx)
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            results = _suite(_load(path, "cogmap_mut_%d" % idx))
            red = [n for n, ok, _ in results if not ok]
            print("  %s %-42s 红项=%d 预期=%d"
                  % ("OK  " if len(red) == expect else "MISMATCH", name, len(red), expect))
            for n, ok, detail in results:
                if not ok:
                    print("        FAIL %s  %s" % (n, str(detail).replace("\n", " | ")[:160]))
            if len(red) != expect:
                bad.append("%s（红=%d 预期=%d）" % (name, len(red), expect))

    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s"
          % ("PASS（并集回退的各级形态都被打红且恰好命中预期项数）" if not bad
             else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def main():
    ap = argparse.ArgumentParser(
        description="N262 守卫：cogmap_sync._check_doc 跨基元 op 引用校验（cg↔cg_ops / stg↔stg_ops）")
    ap.add_argument("--impl", default=None,
                    help="被测实现：缺省=工作树 scripts/cogmap_sync.py；"
                         "head=HEAD 版（红基线取证）；或一个 .py 路径")
    ap.add_argument("--mutate", action="store_true", help="定点变异自证（并集回退 → 必红）")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.mutate:
        return _mutate_mode()

    with tempfile.TemporaryDirectory(prefix="n262_guard_") as tmp:
        if args.impl is None:
            impl, label = DEFAULT_IMPL, "工作树版"
        elif args.impl == "head":
            impl, why = _materialize_head(tmp)
            if impl is None:
                print("取不到 HEAD 版：%s" % why)
                return 1
            label = "HEAD 版（红基线：HEAD 仍含缺陷时 L1/L2 应 FAIL；已含修复时转绿）"
        else:
            impl = os.path.abspath(args.impl)
            if not os.path.isfile(impl):
                print("--impl 指向的文件不存在：%s" % impl)
                return 1
            label = "显式指定副本"
        return _run_mode(impl, label)


if __name__ == "__main__":
    raise SystemExit(main())
