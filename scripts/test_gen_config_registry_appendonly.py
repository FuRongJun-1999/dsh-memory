# -*- coding: utf-8 -*-
# 功能名：配置登记生成器的「只增不改」守护（F26-17 前置）
# 生效条件：python -X utf8 scripts/test_gen_config_registry_appendonly.py；被测面＝scripts/gen_config_registry.py 的 _entry_names_from_file / _lost_entries 与 main() 的写盘前检测
# 子功能：①能从已生成模块里 AST 读出条目名 ②旧文件不存在/语法错时放行（首次生成不误伤）③真实场景不丢条目 ④造丢一条能精确抓到（判别力）⑤main 里有 --force 逃逸口且写盘前有检测锚点
# 执行：import 生成器模块（不执行 main）→ 直测两个纯函数 → 静态锚点断言 main 的接线
# 验证方式：全部 PASS exit 0，否则 exit 1
# 不适用条件：不验证「生成器此刻能否成功跑完」（依赖 .tmp/param_inventory.json 盘点件）；不判条目语义是否正确（那是 config_registry_guard 的面）
"""配置登记生成器的「只增不改」守护。

背景（实测事故）：`gen_config_registry.py` 是**整文件重写**，为登记 3 个新 env 整体重跑后，
`MDCG_WARM_SEARCH` / `MDCG_VISION_ROOT` 两行被抹掉（已回滚）。文件头本就写着
「不要为加一个 env 而整体重跑本脚本」，但没有机制兜住。本守护把那条口径变成可执行判据。
"""
import importlib.util
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN = os.path.join(ROOT, "scripts", "gen_config_registry.py")
BULK = os.path.join(ROOT, "md_cg", "config_registry_bulk.py")

_PASS, _FAIL = [], []


def ok(cond, msg, detail=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg + (("  <- " + str(detail)) if detail and not cond else ""))


def _load():
    spec = importlib.util.spec_from_file_location("_gen_reg", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    m = _load()

    print("== A 读条目名（AST，不 import 目标模块）")
    names = m._entry_names_from_file(BULK)
    ok(len(names) >= 300, "A1 能读出已生成模块的条目名（>=300）", len(names))
    ok("MDCG_RETRIEVAL_PIPELINE" in names, "A2 抽检 ENV_ROWS 首条在位")
    ok("R1_MAX_SHARE" in names, "A3 抽检 CONST_ROWS 首条在位")

    print("== B 放行面（不可误伤首次生成）")
    ok(m._entry_names_from_file(os.path.join(ROOT, "_no_such_file_.py")) == set(),
       "B1 文件不存在 ⇒ 空集（首次生成放行）")
    tmpdir = tempfile.mkdtemp(prefix="genreg_")
    bad = os.path.join(tmpdir, "bad.py")
    # 夹具必须**真的**语法错：首版写 `CONST_ROWS = [ ("x",)]  # 语法坏`——那其实是合法 Python，
# AST 能解析出 {'x'}，于是 B2/B3 假失败（又一次「夹具不自洽」）。下面这个缺右括号+引号，必然 SyntaxError。
    open(bad, "w", encoding="utf-8").write("CONST_ROWS = [ (  # 真语法错\n")
    ok(m._entry_names_from_file(bad) == set(), "B2 语法错 ⇒ 空集（不误报会丢行）")
    ok(m._lost_entries(bad, ["A"]) == [], "B3 旧文件坏 ⇒ lost 为空")

    print("== C 真实场景：不丢")
    ok(m._lost_entries(BULK, names) == [],
       "C1 以当前文件全量条目为「新内容」⇒ 一条都不丢")

    print("== D 判别力：造丢一条要抓得住")
    victim = sorted(names)[0]
    left = set(names) - {victim}
    lost = m._lost_entries(BULK, left)
    ok(lost == [victim], "D1 少传一条 ⇒ 精确报出该条（判别力自证）", lost)
    lost2 = m._lost_entries(BULK, list(left)[:5])
    ok(len(lost2) == len(names) - 5, "D2 少传多条 ⇒ 数量对得上", (len(lost2), len(names)))

    print("== E main() 的接线（静态锚点）")
    src = open(GEN, encoding="utf-8").read()
    ok("_lost_entries(OUT_MODULE" in src, "E1 写盘前调用 _lost_entries")
    ok("只增不改" in src, "E2 判据名写进注释（可检索）")
    ok("--force" in src, "E3 有显式逃逸口 --force")
    i_lost = src.find("_lost = _lost_entries(")
    i_write = src.find("with open(OUT_MODULE,")
    ok(0 < i_lost < i_write, "E4 检测发生在**写盘之前**（顺序不可颠倒）", (i_lost, i_write))
    ok("return 3" in src, "E5 拒绝时返回非零退出码（不静默）")

    print()
    print("生成器只增不改守护：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("  -", f)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())