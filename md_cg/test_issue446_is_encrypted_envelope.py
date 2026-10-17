# -*- coding: utf-8 -*-
"""#446 `crypto.is_encrypted` 判据守卫：必须是**完整信封**，不是只看前缀。

原判据 `content.lstrip().startswith(ENC_PREFIX)` 只查前缀，**弱于消费方的前置**——
消费方（backfill / ccgc / consolidate 十余处）拿到 True 即当「已加密、不可读」而跳过，
而取正文要按 `[len(ENC_PREFIX):-len(ENC_SUFFIX)]` 切掉**后缀**。⇒ 任何以 ENC_PREFIX
起头的明文都被误判为密文：低权写者一条伪前缀节点即可令其被全线静默排除。

断言（**判据一致性不变量**是本件的核心）：
  A  伪前缀（有前缀无后缀）⇒ 不得判为密文（改前为 True）
  A2 前缀+后缀但中间为空 ⇒ 不得判为密文（信封不可能为空载荷）
  B  真信封（前缀 + 载荷 + 后缀）⇒ 必须判为密文（阳性对照，防「一律 False」式过修）
  B2 真信封前后带空白/换行 ⇒ 仍必须判为密文（strip 语义保持）
  C  反向：正文中段含 ENC_PREFIX 标记、空串、None ⇒ 不得判为密文
  D  **不变量**：∀ 样本，is_encrypted(x) 为真 ⇒ 必须能安全切出 [len(PREFIX):-len(SUFFIX)] 且非空
     —— 把「判据不得弱于消费前置」直接钉成可执行断言（改前 A 样例会在此点红）

变异（--mutate，每条必须恰好点红其对应断言）：
  MUT-A 判据退回「只看前缀」（=修复前语义）        → A / D 点红
  MUT-B 判据恒 True（过度宽松）                    → A / C 点红
  MUT-C 判据恒 False（过度收紧）                    → B / B2 点红
"""
import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from md_cg import crypto as C  # noqa: E402

P, S = C.ENC_PREFIX, C.ENC_SUFFIX
_TRUE_ENV = P + "QUJDREVG" + S                      # 前缀 + 载荷 + 后缀
_FAKE_PREFIX_ONLY = P + "not-a-real-envelope"        # 只有前缀（明文伪装）
_EMPTY_PAYLOAD = P + S                               # 前缀紧接后缀
_PADDED = "\n  " + _TRUE_ENV + "  \n"                # 真信封带空白
_MID_MARKER = "# 说明：密文标记形如 " + P + "xxx" + S  # 标记在正文中段
_BLANK = ""
_NONE = None

_FAIL = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  · {detail}" if detail else ""))
    if not cond:
        _FAIL.append(name)


def _sliceable(x):
    """消费方的前置：能否安全切掉后缀并得到非空载荷。"""
    if not isinstance(x, str):
        return False
    t = x.strip()
    if not (t.startswith(P) and t.endswith(S)):
        return False
    return len(t[len(P):-len(S)]) > 0


def run():
    del _FAIL[:]
    print("is_encrypted：完整信封判据（#446）")

    check("A 伪前缀（无后缀）不得判为密文", C.is_encrypted(_FAKE_PREFIX_ONLY) is False,
          f"实得 {C.is_encrypted(_FAKE_PREFIX_ONLY)}")
    check("A2 前缀+后缀但空载荷不得判为密文", C.is_encrypted(_EMPTY_PAYLOAD) is False,
          f"实得 {C.is_encrypted(_EMPTY_PAYLOAD)}")
    check("B 真信封必须判为密文", C.is_encrypted(_TRUE_ENV) is True)
    check("B2 真信封带空白仍判为密文", C.is_encrypted(_PADDED) is True)
    check("C 正文中段的标记不得判为密文", C.is_encrypted(_MID_MARKER) is False)
    check("C 空串/None 不得判为密文",
          C.is_encrypted(_BLANK) is False and C.is_encrypted(_NONE) is False)

    # D 不变量：判据 ⟹ 可切（改前 A 样本在此点红）
    bad = [n for n, x in (("伪前缀", _FAKE_PREFIX_ONLY), ("空载荷", _EMPTY_PAYLOAD),
                          ("真信封", _TRUE_ENV), ("带空白", _PADDED),
                          ("中段标记", _MID_MARKER), ("空串", _BLANK), ("None", _NONE))
           if C.is_encrypted(x) and not _sliceable(x)]
    check("D 不变量：is_encrypted ⟹ 可安全切出非空载荷", not bad,
          f"违约样本={bad}")

    print(f"\n===== {len(_FAIL) == 0 and '全绿' or '失败'} =====")
    if _FAIL:
        print("失败项：" + "; ".join(_FAIL))
    return 0 if not _FAIL else 1


# ── 变异 ──────────────────────────────────────────────────────────────────────
_CRYPTO = os.path.join(REPO, "md_cg", "crypto.py")
_MUTS = [
    ("MUT-A 判据退回「只看前缀」（=修复前）",
     '    t = content.strip()\n'
     '    return (len(t) > len(ENC_PREFIX) + len(ENC_SUFFIX)\n'
     '            and t.startswith(ENC_PREFIX) and t.endswith(ENC_SUFFIX))',
     '    return bool(content) and content.lstrip().startswith(ENC_PREFIX)',
     ["A 伪前缀（无后缀）不得判为密文",
      "A2 前缀+后缀但空载荷不得判为密文",
      "D 不变量：is_encrypted ⟹ 可安全切出非空载荷"]),
    ("MUT-B 判据恒 True（过度宽松）",
     '    if not content:\n        return False',
     '    if content is None:\n        return False\n    return True',
     ["A 伪前缀（无后缀）不得判为密文",
      "A2 前缀+后缀但空载荷不得判为密文",
      "C 正文中段的标记不得判为密文",
      "C 空串/None 不得判为密文",
      "D 不变量：is_encrypted ⟹ 可安全切出非空载荷"]),
    ("MUT-C 判据恒 False（过度收紧）",
     '    if not content:\n        return False',
     '    if not content:\n        return False\n    return False',
     ["B 真信封必须判为密文", "B2 真信封带空白仍判为密文"]),
]


def _once():
    """子进程内跑一次断言，返回点红的断言名列表。

    注意：**不要**在 import 前把 stdout 换成 StringIO——本模块 import 时会
    `sys.stdout.reconfigure(...)`，StringIO 没有该方法，子进程会直接崩掉、
    变异读数全空（表现为「未达预期」的假象）。父进程本就捕获 stdout，无需重定向。
    """
    code = ("import sys\n"
            "sys.path.insert(0, %r)\n"
            "import md_cg.test_issue446_is_encrypted_envelope as M\n"
            "M.run()\n"
            "print('RED ' + '||'.join(M._FAIL))\n" % REPO)
    r = subprocess.run([sys.executable, "-X", "utf8", "-c", code], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=120, cwd=REPO)
    red = ""
    for line in (r.stdout or "").splitlines():
        if line.startswith("RED "):
            red = line[4:].strip()
    return [x for x in red.split("||") if x]


def main():
    if "--once" in sys.argv:
        return run()
    if "--mutate" not in sys.argv:
        return run()

    orig = io.open(_CRYPTO, encoding="utf-8").read()
    bad = 0
    try:
        print("变异测试（每条必须恰好点红对应断言）：")
        for name, old, new, expect in _MUTS:
            if orig.count(old) != 1:
                print(f"  {name}: 锚点命中 {orig.count(old)} 次（应为 1）——跳过")
                bad += 1
                continue
            io.open(_CRYPTO, "w", encoding="utf-8", newline="\n").write(orig.replace(old, new))
            red = _once()
            ok = set(red) == set(expect)
            print(f"  {name}: {'点红 ✓' if ok else '未达预期 ✗'}  (red={red})")
            if not ok:
                bad += 1
        io.open(_CRYPTO, "w", encoding="utf-8", newline="").write(orig)
    finally:
        io.open(_CRYPTO, "w", encoding="utf-8", newline="").write(orig)
    print("\n===== " + ("全绿" if not bad else "失败：存在未达预期变异") + " =====")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
