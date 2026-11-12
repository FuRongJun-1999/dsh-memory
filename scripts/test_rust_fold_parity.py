# -*- coding: utf-8 -*-
# 功能名：Rust 重音折叠表与 Python `fold_accents` 的跨实现一致性守卫（F26-25）
# 生效条件：python -X utf8 scripts/test_rust_fold_parity.py；被测面＝rust/src/text_fold.rs 的 LATIN_FOLD 表 vs md_cg.mdcg.fold_accents
# 子功能：①逐条核对表项与 Python 折叠结果一致 ②表必须严格有序（Rust binary_search 依赖）③无规范分解字符（ß/ø）不得入表 ④日文浊点（が）不得入表且 Python 也不折 ⑤覆盖抽样（café/señor/Über/Ångström）⑥边界声明：希腊/西里尔未收（两侧行为差异已知）
# 执行：正则解析 Rust 表 → 对每个 (char, base) 断言 Python fold_accents(char) == base → 再反向抽查典型词
# 验证方式：全部 PASS exit 0，否则 exit 1
# 不适用条件：不验 Rust 侧运行时（那由 cargo test 的 6 条单测承担）；不要求全 Unicode 等价（希腊/西里尔/数学字母未收，属已声明的边界）
"""F26-25 跨实现一致性守卫。

背景：`normalize_en`（Rust）原先把非 ASCII 非中文一律变空格 ⇒ `café` → `caf`，
而 Python `fold_accents` 给 `cafe`，两侧互不可命中。

修法受 `rust/Cargo.toml` 的「零第三方依赖」约束（与 md_cg 的 D-005 一致），
不能用 `unicode-normalization`，改为按 Python 口径**生成** 497 条预组合字符映射表。

本守卫的职责：确保那张表与 Python 语义**逐条对齐**——这是"近似路线"能成立的唯一凭据。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RUST_TABLE = os.path.join(ROOT, "rust", "src", "text_fold.rs")

_PASS, _FAIL = [], []


def ok(cond, msg, detail=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg + (("  <- " + str(detail)) if detail and not cond else ""))


def parse_rust_table(path):
    """从 text_fold.rs 取 LATIN_FOLD 的 (char, char) 序列。"""
    src = open(path, encoding="utf-8").read()
    m = re.search(r"pub const LATIN_FOLD: \[\(char, char\); (\d+)\] = \[(.*?)\n\];",
                  src, re.S)
    if not m:
        return None, None
    declared = int(m.group(1))
    body = m.group(2)
    pairs = []
    for line in body.splitlines():
        mm = re.search(r"\('\\u\{([0-9A-Fa-f]+)\}', '\\u\{([0-9A-Fa-f]+)\}'\)", line)
        if mm:
            pairs.append((chr(int(mm.group(1), 16)), chr(int(mm.group(2), 16))))
    return declared, pairs


def main():
    from md_cg.mdcg import fold_accents

    print("== A 表可解析且条目数自洽")
    declared, pairs = parse_rust_table(RUST_TABLE)
    ok(declared is not None, "A1 能解析 LATIN_FOLD 声明与表体")
    if declared is None:
        print("\n跨实现一致性守卫：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
        return 1
    ok(len(pairs) == declared, "A2 声明条目数 == 实际条目数", (declared, len(pairs)))
    ok(len(pairs) > 400, "A3 条目数达到预期量级（>400）", len(pairs))

    print("== B 逐条对齐：表项 == Python fold_accents")
    bad = []
    for ch, base in pairs:
        got = fold_accents(ch)
        if got != base:
            bad.append((ch, base, got))
    ok(not bad, "B1 全部 %d 条与 Python 一致" % len(pairs), bad[:5])

    print("== C 表必须严格有序（Rust binary_search 依赖）")
    cps = [ord(ch) for ch, _ in pairs]
    ok(cps == sorted(cps), "C1 字符码位严格升序")
    ok(len(set(cps)) == len(cps), "C2 无重复字符")

    print("== D 不该入表的字符（无规范分解）")
    table_chars = {ch for ch, _ in pairs}
    for ch in ("ß", "ø", "Ø", "Æ"):
        ok(ch not in table_chars, "D %s 不在表内（无规范分解，Python 也不变）" % ch)

    print("== E 日文浊点不得入表（F26-27 的边界）")
    for ch in ("が", "ガ", "ぱ", "ば"):
        ok(ch not in table_chars, "E %s 不在表内（组合记号 U+3099 不在三区间）" % ch)
    ok(fold_accents("が") == "が" and fold_accents("が") != "か",
       "E Python 侧也不折浊点（与 Rust 同向）")

    print("== F 典型词抽样（两侧应同向）")
    cases = [("café", "cafe"), ("CAFÉ", "CAFE"), ("señor", "senor"),
             ("Über", "Uber"), ("Ångström", "Angstrom"), ("straße", "straße")]
    for src, want in cases:
        got_rs = "".join(dict(pairs).get(c, c) for c in src)
        got_py = fold_accents(src)
        ok(got_py == want, "F Python: %-10s -> %-10s" % (src, got_py), (src, want, got_py))
        ok(got_rs == got_py, "F Rust表: %-10s -> %-10s（与 Python 一致）" % (src, got_rs),
           (src, got_rs, got_py))

    print("== G 边界（已声明，不是缺陷）")
    greek = [chr(c) for c in range(0x0370, 0x0400) if fold_accents(chr(c)) != chr(c)]
    ok(len(greek) > 0, "G1 Python 会折希腊重音（%d 个）" % len(greek))
    # 2026-10-28 修正：初版表只收拉丁四区，于是「Rust 不折、Python 折」构成新分叉。
    # 现在表按「Python 能折的全部」生成（含希腊/西里尔/兼容区），所以这里断言**覆盖**，
    # 而不是断言"都不覆盖"——后者会掩盖真实分叉。
    missing = [ch for ch in greek if ch not in table_chars]
    ok(not missing, "G2 希腊重音已全部入表（与 Python 一致，不是假装不覆盖）", missing[:5])

    print()
    print("跨实现一致性守卫：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("  -", f)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
