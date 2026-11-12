# -*- coding: utf-8 -*-
# 功能名：wisdom 两代码生成单元的产物必须与参考实现逐例相符（issue #401）
# 生效条件：python -X utf8 -m md_cg.test_issue401_wisdom_codegen [--mutate]；被测面＝net_units.NET_UNITS[网络-校验和] 的 pattern/cases 与 mini_python 的比较链求值
# 子功能：A 组＝两站点复现（校验和按 RFC1071 参考实现逐例对照；链式比较与 CPython 逐例对照）+ **判据升级**（自带样例必须由参考实现核对、且旧误解实现必被这批向量抓住）；K 组＝非恒真对照（含过度收紧方向：单比较/成员运算/边界不受扰）；E 组＝全枚举（该单元 cases 与自测向量表的判别力）
# 执行：--mutate 时在镜像树里把实现改回按字节累加 / 左结合，以及做成恒真恒假（过度收紧），守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期**逐项相符**
# 不适用条件：不判 verifier 受控执行器（本机沙箱禁 piped stdio）——本守卫改用**进程内执行产物 + 与参考实现逐例对照**（比「verifier 报过」更强）；不穷尽全部比较运算符组合与嵌套链式；不判 code_compose 的域路由精度（#401 §五 另登记）
"""issue #401 守卫：两个代码生成单元「自带样例全过但产物算错」。

根因（比报告更准）：**自带样例的期望值由同一处误解推出**（net_units 的
`(~10) & 0xFFFF`、`(~510) & 0xFFFF` 就是按字节累加的口径写的）⇒ 样例与实现**耦合**，
判别力为零；mini_python 的自测只用 `1 < 2 < 3`，在错误的**左结合**语义下恰好也通过。

故本守卫的**主产出是判据升级**：期望值一律来自**独立参考实现**（RFC1071 / CPython），
并额外断言「旧误解实现会被同一批向量抓住」（判别力自证），而不是「有 def 就算过」。
"""
from __future__ import annotations

import ast
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


from md_cg.whitebox_kb.wisdom import mini_python as _mp      # noqa: E402
from md_cg.whitebox_kb.wisdom import net_units as _nu        # noqa: E402


#: **独立参考实现**（RFC1071 一补数和）：偶数长度按 16 位字累加 + 进位折叠 → 取反。
def _rfc1071(data: bytes) -> int:
    if len(data) % 2:
        data = data + bytes([0])
    total = 0
    for i in range(0, len(data), 2):
        total += (data[i] << 8) + data[i + 1]
        while total > 0xFFFF:
            total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


#: 旧误解实现（按**字节**累加）——只用于「判别力自证」，不参与被测面。
def _bytewise_bug(data: bytes) -> int:
    total = 0
    for b in data:
        total += b
        if total > 0xFFFF:
            total = (total & 0xFFFF) + 1
    return (~total) & 0xFFFF


_UNIT = _nu.NET_UNITS["网络-校验和"]
_NS: dict = {}
exec(compile(_UNIT["pattern"], "<unit-pattern>", "exec"), _NS)   # 进程内执行产物
_sum_fn = _NS.get("checksum")

#: 标准向量（含 report 实测四组 + 边界）
_VECTORS = [bytes([1, 2, 3, 4]), bytes([]), bytes([0xFF, 0xFF]), b"AB",
            bytes(range(20)), bytes([0x00]), bytes([0x12, 0x34, 0x56])]

print("== A 组 站点 1：网络-校验和 必须与 RFC1071 参考实现逐例相符 ==")
_check("A00 产物可执行且定义了 checksum（判据有效的前提）", callable(_sum_fn), type(_sum_fn))
for _v in _VECTORS:
    _exp = _rfc1071(_v)
    _got = _sum_fn(_v) if callable(_sum_fn) else None
    _check("A01 参考实现对照：checksum(%r) == 0x%04X" % (_v, _exp),
           _got == _exp, (_got, _exp))

print("== A 组：★判据升级（自带样例必须与实现**解耦**） ==")
_cases = list(_UNIT.get("cases") or [])
_check("A02 单元自带样例非空（≥3 例）", len(_cases) >= 3, len(_cases))
_bad = [(c[0][0], c[1], _rfc1071(c[0][0])) for c in _cases if _rfc1071(c[0][0]) != c[1]]
_check("A03 ★自带样例的期望值**逐例等于 RFC1071 参考实现**（修前它们由同一处误解推出）",
       not _bad, _bad)
_catch = [v for v in _VECTORS if _bytewise_bug(v) != _rfc1071(v)]
_check("A04 ★判别力自证：**旧误解实现**（按字节累加）会被同一批向量抓住（%d/%d 例不同）"
       % (len(_catch), len(_VECTORS)), len(_catch) >= 3, _catch)

print("== A 组 站点 2：链式比较必须与 CPython 逐例相符 ==")
_CHAINS = ["0 <= 15 < 10", "2 == 2 == 2", "3 > 2 > 1", "1 < 2 < 3", "0 <= 5 <= 10",
           "5 > 4 > 3 > 2 > 1", "1 < 2 > 3"]
for _s in _CHAINS:
    _mini = _mp.eval_expr(_s)
    _cp = eval(_s)                                    # noqa: S307 —— 逐例对照 CPython
    _check("A05 CPython 对照：%-18s mini=%-6s cpython=%s" % (_s, _mini, _cp),
           _mini == _cp, (_mini, _cp))
_check("A06 ★量具失效已修：`0 <= 15 < 10` 必须是 False（修前恒 True）",
       _mp.eval_expr("0 <= 15 < 10") is False, _mp.eval_expr("0 <= 15 < 10"))
_check("A07 字节码面（compile_expr + VM）同判：交错链与树遍历面一致",
       _mp.eval_expr_vm("0 <= 15 < 10") == eval("0 <= 15 < 10")
       and _mp.eval_expr_vm("2 == 2 == 2") == eval("2 == 2 == 2"),
       (_mp.eval_expr_vm("0 <= 15 < 10"), _mp.eval_expr_vm("2 == 2 == 2")))

print("== K 组：非恒真对照（含过度收紧方向） ==")
_check("K01 过度收紧方向的对照：单比较照常（3 > 2 ⇒ True）",
       _mp.eval_expr("3 > 2") is True, _mp.eval_expr("3 > 2"))
_check("K02 成员/逻辑运算不受扰（in / not / and / or 语义不变）",
       _mp.eval_expr("2 in [1,2,3]") is True
       and _mp.eval_expr("not 1 > 2") is True
       and _mp.eval_expr("0 or 5") == 5
       and _mp.eval_expr("0 and 1/0") == 0, "")
_check("K03 算术优先级不变（2+3*4 / -2**2 / 2**3**2）",
       _mp.eval_expr("2+3*4") == 14 and _mp.eval_expr("-2**2") == -4
       and _mp.eval_expr("2**3**2") == 512, "")
_check("K04 校验和边界不变：空输入 ⇒ 0xFFFF（参考实现同值）",
       _sum_fn(bytes([])) == _rfc1071(bytes([])) == 0xFFFF, _sum_fn(bytes([])))
_check("K05 奇数长度补零语义（0x12,0x34,0x56 ⇒ 按 0x1234+0x5600）",
       _sum_fn(bytes([0x12, 0x34, 0x56])) == _rfc1071(bytes([0x12, 0x34, 0x56])),
       _sum_fn(bytes([0x12, 0x34, 0x56])))

print("== E 组：全枚举（样例判别力与自测向量） ==")


def _src(rel):
    with io.open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


_MP_SRC = _src("md_cg/whitebox_kb/wisdom/mini_python.py")
_check("E01 mini_python 自测表已含**错值会红**的向量（`0 <= 15 < 10` 与 `2 == 2 == 2`）",
       '"0 <= 15 < 10", False' in _MP_SRC and '"2 == 2 == 2", True' in _MP_SRC,
       "")
_check("E02 链式比较不再是「已构造节点当左操作数」的左结合形态（源码面：无 `node = (t[1], node, self.arith())`）",
       "node = (t[1], node, self.arith())" not in _MP_SRC, "")
_check("E03 校验和单元的 pattern 已按 16 位字（源码面含 `<< 8`，且不再 `total += b`）",
       "<< 8" in _UNIT["pattern"] and "total += b" not in _UNIT["pattern"],
       _UNIT["pattern"][:120])
_check("E04 同面另几个单元的样例也须过「参考实现可核算」——本批只登记不改（%d 单元）"
       % len(_nu.NET_UNITS), len(_nu.NET_UNITS) >= 4, sorted(_nu.NET_UNITS))

# ---------------------------------------------------------------- 定点变异表
_CS_OK = chr(10).join([
    '            "    if len(data) % 2:\\n"',
    '            "        data = data + bytes([0])\\n"',
    '            "    total = 0\\n"',
    '            "    for i in range(0, len(data), 2):\\n"',
    '            "        total += (data[i] << 8) + data[i + 1]\\n"',
])
_CS_BUG = chr(10).join([
    '            "    total = 0\\n"',
    '            "    for b in data:\\n"',
    '            "        total += b\\n"',
    '            "        if total > 0xFFFF:\\n"',
    '            "            total = (total & 0xFFFF) + 1\\n"',
])
_CS_ZERO = '            "    return 0\\n"),'
_CS_RET = '            "    return (~total) & 0xFFFF\\n"),'
_CHAIN_OK = chr(10).join([
    '        if not ops:',
    '            return first',
    '        if len(ops) == 1:',
    '            return (ops[0], operands[0], operands[1])',
    '        return ("chain", ops, operands)',
])
_CHAIN_BAD = chr(10).join([
    "        node = first",
    "        for _i, _op in enumerate(ops):",
    "            node = (_op, node, operands[_i + 1])   # 变异：左结合（回缺陷）",
    "        return node",
])
_MUTATIONS = (
    # M1 回缺陷（校验和回到按字节累加）⇒ 与参考实现逐例不符：A01 红 ×多例；E03（源码面）红。
    # A03（自带样例值 vs 参考）**仍绿**——样例值已解耦，如实。
    ("M1 回缺陷：校验和回到按字节累加", "md_cg/whitebox_kb/wisdom/net_units.py",
     ((_CS_OK, _CS_BUG),),
     ("A01", "E03", "K05")),   # K05（奇数长度语义）同红：它是对照面里的正确性共断言
    # M2 回缺陷（比较链回到左结合）⇒ CPython 对照红：A05 红（部分向量）+ A06 + A07。
    ("M2 回缺陷：比较链回到左结合", "md_cg/whitebox_kb/wisdom/mini_python.py",
     ((_CHAIN_OK, _CHAIN_BAD),),
     ("A05", "A06", "A07")),
    # M3 **过度收紧方向**：校验和恒返 0 ⇒ 参考实现对照全红 + 边界对照红。
    ("M3 过度收紧：校验和恒返 0", "md_cg/whitebox_kb/wisdom/net_units.py",
     ((_CS_RET, _CS_ZERO),),
     ("A01", "K04", "K05")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss401_mut_")
    for name in ("md_cg", "scripts", "hive"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml",
                                              "package.json")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _apply_text(text, rel, pairs):
    eol = (chr(13) + chr(10)) if (chr(13) + chr(10)) in text else chr(10)
    for old, new in pairs:
        o = old.replace(chr(10), eol)
        n = new.replace(chr(10), eol)
        if text.count(o) != 1:
            return None, "锚点在 %s 里命中 %d 次" % (rel, text.count(o))
        text = text.replace(o, n, 1)
    return text, ""


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue401_wisdom_codegen"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：两处回缺陷（按字节累加 / 左结合）＋ 恒返 0（过度收紧）")
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            bad.append("未变异镜像基线即红")
            print(chr(10).join(out.splitlines()[-25:]))
        for desc, rel, pairs, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            with open(p, encoding="utf-8", newline="") as f:
                bak = f.read()
            mut, why = _apply_text(bak, rel, pairs)
            if mut is None:
                bad.append("%s —— %s" % (desc, why))
                print("  ANCHOR-MISS " + desc + "  " + why)
                continue
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(mut)
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s  红项=%d 指定命中=%s" % (desc, len(reds2), hit))
            else:
                bad.append(desc)
                print("  MISMATCH %s  实际红项=%s  期望=%s  rc=%d"
                      % (desc, hit, sorted(exp), rc2))
                for r in reds2[:8]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
print("")
if FAILS:
    print("issue #401 结果：%d 失败" % len(FAILS))
else:
    print("issue #401 结果：全部通过")

