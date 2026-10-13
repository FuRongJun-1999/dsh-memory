# -*- coding: utf-8 -*-
"""issue #279 守卫：signers_file 路径穿越拦截。

`signer.signers_file()` 曾对 path 参数零校验直接返回，
MCP link 透传 signers_file 即可读任意 JSON 文件。
本测试锁定 fail-closed 口径：含 `..` 路径段 / 空字节 / 非 str 即拒。
"""
import sys

sys.path.insert(0, "/home/hatch/workspace/fix-work/dsh-memory")

from md_cg import signer

PASS = 0
FAIL = 0


def check(name, fn):
    global PASS, FAIL
    try:
        fn()
    except AssertionError as e:
        FAIL += 1
        print(f"  FAIL {name}: {e}")
    except Exception as e:
        FAIL += 1
        print(f"  FAIL {name}: unexpected {type(e).__name__}: {e}")
    else:
        PASS += 1
        print(f"  PASS {name}")


def expect_reject(path):
    try:
        signer.signers_file(path)
    except signer.SignerError:
        return
    raise AssertionError(f"{path!r} 未被拦截")


def expect_allow(path, expected=None):
    r = signer.signers_file(path)
    if expected is not None and r != expected:
        raise AssertionError(f"{path!r} -> {r!r}，期望 {expected!r}")


# --- 恶意矩阵：必须拦截 ---
check("相对穿越 ../../../etc/passwd", lambda: expect_reject("../../../etc/passwd"))
check("相对穿越 ../secret.json", lambda: expect_reject("../secret.json"))
check("绝对形态穿越 /tmp/e/../../etc/x.json", lambda: expect_reject("/tmp/e/../../etc/x.json"))
check("反斜杠形态 ..\\..\\win", lambda: expect_reject("..\\..\\win"))
check("空字节 /etc/passwd\\x00.json", lambda: expect_reject("/etc/passwd\x00.json"))
check("空白字符串", lambda: expect_reject("   "))
check("非 str 类型", lambda: expect_reject(123))

# --- 合法值：必须放行 ---
check("None 回落默认", lambda: expect_allow(None, signer.DEFAULT_SIGNERS_FILE))
check("空串回落默认", lambda: expect_allow("", signer.DEFAULT_SIGNERS_FILE))
check("绝对路径", lambda: expect_allow("/tmp/signers.json", "/tmp/signers.json"))
check("相对文件名", lambda: expect_allow("signers.json", "signers.json"))
check("默认常量自身", lambda: expect_allow(signer.DEFAULT_SIGNERS_FILE))

# --- 汇点覆盖：load_policies / save_policies 走同一校验 ---
def _load_reject():
    try:
        signer.load_policies("../../../evil.json")
    except signer.SignerError:
        return
    raise AssertionError("load_policies 未拦截穿越路径")

def _save_reject():
    try:
        signer.save_policies({}, "../../../evil.json")
    except signer.SignerError:
        return
    raise AssertionError("save_policies 未拦截穿越路径")

check("load_policies 穿越被拒", _load_reject)
check("save_policies 穿越被拒", _save_reject)

print(f"\nissue #279 守卫：{PASS} 通过，{FAIL} 失败")
sys.exit(1 if FAIL else 0)
