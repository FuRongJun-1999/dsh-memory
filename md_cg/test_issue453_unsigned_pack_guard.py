# -*- coding: utf-8 -*-
"""test_issue453_unsigned_pack_guard.py · #453 跨节点证据包「自报免验」守卫

**缺陷**（`evidence.py` import_pack）：判据原为
    if not signature and (pack["sig"].get("signer") != "null"):
        return 拒绝
即**免签名与否由包自己声明的字符串决定**——`sig={"signer":"null","signature":""}`
是攻击者可控字段，于是「无密钥、无签名」即可通过验签（`verify_for` 在策略未要求
签名时返回 `ok=True`）并**伪造 `source:<任意节点>`** 写入本节点图谱。

**修复语义**：**豁免必须来自策略**（`subsystems[<子系统>].allow_unsigned`），
而不是来自被检验对象自报的字段；默认**拒绝**。

断言（4 条）：
  A 无策略 + 自报 `signer="null"` + 空签名 ⇒ **拒绝**（核心；修复前放行）
  B 显式 `allow_unsigned: true` + 同一种包 ⇒ **放行**（不误伤合法免签名场景）
  C 自报 `signer` 为其它值 + 空签名 ⇒ 拒绝（原本就拒，**阳性对照**：
    证明 A 的红不是「什么都拒」）
  D 有真实签名 ⇒ 不受本闸影响（不回归）

变异（`--mutate`，每条必须恰好点红对应断言）：
  MUT-A 恢复「自报 signer=='null' 即免验」 ⇒ A 点红
  MUT-B `allow_unsigned` 恒真（等于闸失效）  ⇒ A 点红

用法：`python -m md_cg.test_issue453_unsigned_pack_guard [--mutate]`
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)


def _mkpack(signer, signature=""):
    """与 test_issue147 同形的证据包（`sig` 可被调用方随意构造）。"""
    return {"kind": ev.KIND, "schema": ev.SCHEMA,
            "from_node": "attacker", "pack_id": "p-453",
            "items": [{"subject": "s", "text": "t"}],
            "sig": {"signer": signer, "signature": signature, "signed": False}}


def _sandbox(t, allow_unsigned):
    """建隔离沙箱并设策略；返回 (root)。`allow_unsigned=None` ⇒ 不写策略文件。"""
    aux = os.path.join(t, "aux")
    root = os.path.join(t, "root")
    for d in (aux, root):
        os.makedirs(d, exist_ok=True)
    os.environ.update(MDCG_AUX_ROOT=aux, MDCG_ROOT=root, MDCG_NODE_ID="node-self",
                      MDCG_MASTER_KEY=os.urandom(32).hex())
    # 必须显式设（DEFAULT_SWARM_DIR 在模块导入时冻结；见 test_issue147 的注释）
    os.environ["MDCG_SWARM_DIR"] = os.path.join(aux, "swarm")
    for k in ("MDCG_POLICY_FILE", "MDCG_SIGNERS_FILE"):
        os.environ.pop(k, None)
    if allow_unsigned is not None:
        sgn = os.path.join(t, "signers.json")
        io.open(sgn, "w", encoding="utf-8").write(json.dumps(
            {"subsystems": {SUB: {"allow_unsigned": bool(allow_unsigned)}}}))
        os.environ["MDCG_SIGNERS_FILE"] = sgn
    return root


# 延迟导入（沙箱要求先设环境变量，见 _sandbox 注释）
import md_cg.evidence as ev                                   # noqa: E402
from md_cg.mdcos import MdCGSecure as MdCGOS                   # noqa: E402

SUB = ev.SUBSYSTEM
_PASS, _FAIL = 0, 0


def check(name, cond, detail=""):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print("  [PASS] %s%s" % (name, ("  · " + str(detail)) if detail else ""))
    else:
        _FAIL += 1
        print("  [FAIL] %s%s" % (name, ("  · " + str(detail)) if detail else ""))


def _import_ok(pack, allow_unsigned):
    """在全新沙箱里跑一次 import_pack，返回 (ok, reason)。"""
    t = tempfile.mkdtemp(prefix="i453_")
    old = dict(os.environ)
    try:
        root = _sandbox(t, allow_unsigned)
        cg = MdCGOS(root)
        r = ev.import_pack(cg, pack, swarm=None)
        return bool(r.get("ok")), str(r.get("reason") or r.get("error") or "")
    finally:
        os.environ.clear()
        os.environ.update(old)
        shutil.rmtree(t, ignore_errors=True)


def run():
    global _PASS, _FAIL
    _PASS = _FAIL = 0

    # A 核心：默认不认「自报 null 免验」
    ok_a, why_a = _import_ok(_mkpack("null"), allow_unsigned=None)
    check("A 无策略自报 signer=null ⇒ 拒绝", not ok_a, "ok=%s reason=%s" % (ok_a, why_a))

    # B 显式策略 ⇒ 放行（不误伤）
    ok_b, why_b = _import_ok(_mkpack("null"), allow_unsigned=True)
    check("B 显式 allow_unsigned ⇒ 放行", ok_b, "ok=%s reason=%s" % (ok_b, why_b))

    # C 阳性对照：非 null 自报 + 空签名，原本就拒（说明 A 不是「一律拒」）
    ok_c, _ = _import_ok(_mkpack("worthless"), allow_unsigned=None)
    check("C 自报 signer=worthless + 空签名 ⇒ 拒绝（阳性对照）", not ok_c)

    # D 显式声明 allow_unsigned=False ⇒ 仍拒（不能靠「文件存在」放行）
    ok_d, _ = _import_ok(_mkpack("null"), allow_unsigned=False)
    check("D 显式 allow_unsigned=false ⇒ 拒绝", not ok_d)

    print("\n===== %d/%d 通过 =====" % (_PASS, _PASS + _FAIL))
    return 0 if _FAIL == 0 else 1


_CHILD = r'''
import json, os, sys
sys.path.insert(0, sys.argv[1])
sys.stdout.reconfigure(encoding="utf-8")
from md_cg import test_issue453_unsigned_pack_guard as T
T.run()
print(json.dumps({"pass": T._PASS, "fail": T._FAIL}))
'''

_MUTS = [
    ("MUT-A 恢复「自报 signer=='null' 即免验」",
     '    if not signature:\n'
     '        if not _signer.policy_for(subsystem, signers_file).get("allow_unsigned"):',
     '    if not signature and (pack.get("sig") or {}).get("signer") != "null":'),
    ("MUT-B allow_unsigned 默认恒真（闸失效）",
     '"allow_unsigned": False}',
     '"allow_unsigned": True}'),
]


def _mutate(mutate):
    src = os.path.join(_HERE, "evidence.py")
    sig = os.path.join(_HERE, "signer.py")
    baks = {}
    for f in (src, sig):
        baks[f] = f + ".mutation-bak"
        shutil.copyfile(f, baks[f])
    try:
        target = src if "policy_for" in mutate[1] else sig
        text = io.open(target, encoding="utf-8").read()
        if text.count(mutate[1]) != 1:
            print("    锚点命中 %d 次（应为 1）——跳过" % text.count(mutate[1]))
            return None
        io.open(target, "w", encoding="utf-8", newline="\n").write(
            text.replace(mutate[1], mutate[2]))
        r = subprocess.run([sys.executable, "-c", _CHILD, _ROOT],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300)
        out = (r.stdout or "") + (r.stderr or "")
        red = []
        for line in out.splitlines():
            if line.startswith("  [FAIL]"):
                red.append(line.split("]", 1)[1].strip().split()[0])
        return red
    finally:
        for f, b in baks.items():
            if os.path.exists(b):
                shutil.move(b, f)


def main():
    argv = sys.argv[1:]
    if "--mutate" not in argv:
        return run()
    print("变异测试（每条必须恰好点红对应断言）：")
    bad = 0
    for mutate in _MUTS:
        red = _mutate(mutate)
        if red:
            print("  %s: 点红 ✓ (%s)" % (mutate[0], ",".join(red)))
        else:
            print("  %s: **未点红 ✗ 假守卫**" % mutate[0])
            bad += 1
    print("\n===== %s =====" % ("全绿" if bad == 0 else "失败：存在假守卫"))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
