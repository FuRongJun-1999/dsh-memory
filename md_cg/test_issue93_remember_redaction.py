# -*- coding: utf-8 -*-
r"""守卫 · #93 mdcg_remember 通路须过 policy 打码（2026-10-09 DSH 端实施）。

缺陷（GitHub #93）：mdcg_remember（hooks 自动记忆走的通路）**不过** policy.json
的 forbidden 规则 ⇒ AKIA / ghp_ / URL 内嵌凭据 / PEM 私钥块**明文入库**且 guest
可检索；而同样内容走 cg(op=write) 会被判 REJECT。

本笔处置：在该分支落盘前，用 **audit.redact_forbidden 按片段打码**（与 REJECT 分支
同口径，非整条拒绝——自动记忆是 hooks 通路，整条拒绝会静默丢记忆）。

判据：
  G1 四种形态都能被 redact_forbidden 命中并改变文本（AKIA/ghp/URL 凭据/PEM）
  G2 静态：mdcg_remember 分支体内**确实调用**了 redact_forbidden（防被回退）
  G3 不误伤：普通内容经 redact_forbidden **逐字不变**
  G4 与 policy.json 同源：命中的正是 policy 里那条（防「另起一套模式」）
  G5 **行为面（#429 补，端到端）**：隔离根下经 `call_tool(g, "mdcg_remember", …)`
     写入含 AKIA 的正文后扫盘面，**明文不得落盘**；同时要求 committed=True 且节点
     文件确实存在——否则「写失败 ⇒ 扫不到明文」会让本判据恒真。
  G6 **防回退锚点（#429 补）**：分支体里「打码结果写回 content」那一行在场。
     G2 只判「调了 redact_forbidden」——调用而**不写回**时 G2 仍绿（#429 的病灶），
     故必须另钉写回那一行。

定点变异（`--mutate`，#429 的元判据）：
  在镜像树里把写回行 `if _red93 and _red93 != a.get("content", ""):` 撤回成
  `if False:`（缺陷态：打码结果不再写回）⇒ **G5、G6 必须转红**。红项集合打印，
  且必须与预期逐项相符（不接受「有红就行」）。

判别力边界（如实）：
  · 本守卫只钉 **mdcg_remember 这一条工具通路**；cg(op=write) 的打码面由 writepipe
    侧守卫覆盖，不在本件红绿面内。
  · 变异腿只撤回**写回**这一行。它**不覆盖**：policy.json 的 AKIA 规则被删（G4 静态
    兜）、redact_forbidden 自身被弱化（G1 兜）、工具面被换成别的写入口（G2 兜）。
    这三条都是静态/单元判据，不是本变异腿的行为面。
  · G6 是源码锚点（fail-closed）：改量名 `_red93` 或重写该行会让它红——这是有意的。
  · 不判打码占位符的具体文案（`[已过滤:…]` 是 redact_forbidden 的实现细节）；只判
    「明文不落盘」+「确实写进去了」。
  · 行为判据在**隔离根**（tempfile）内跑，不碰在役库；不判 guest 读面（另案）。

运行：python -X utf8 -m md_cg.test_issue93_remember_redaction [--mutate]
退出码：0 全绿 ｜ 1 断言失败（含变异腿不符预期）
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

# 沙箱必须在**任何** md_cg 子模块 import 之前设好（crypto 的密钥等在导入时求值）。
# 本守卫不碰在役库：全部读写落在 _SANDBOX 下。
_SANDBOX = tempfile.mkdtemp(prefix="i93_sandbox_")
os.environ["MDCG_ROOT"] = os.path.join(_SANDBOX, "libroot")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_SANDBOX, "auxstore")
os.environ["MDCG_STATE_ROOT"] = os.path.join(_SANDBOX, "state")
os.environ["MDCG_DATA_ROOT"] = os.path.join(_SANDBOX, "data")
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
os.environ["MDCG_SUSTAIN"] = "0"
os.environ["MDCG_SLEEP"] = "0"
os.environ.pop("MDCG_TOKEN", None)
os.environ.pop("MDCG_VERIFY_KEY", None)
for _d in ("libroot", "auxstore", "state", "data"):
    os.makedirs(os.path.join(_SANDBOX, _d), exist_ok=True)

PASS = 0
FAIL = 0
FAILS = []
CASES = (
    ("AWS AKIA", "AKIAIOSFODNN7EXAMPLE"),
    ("GitHub ghp_", "ghp_dummy0123456789abcdefghijklmnop"),
    ("URL 内嵌凭据", "postgres://admin:Hunter2Secret@db.example.com:5432/app"),
    ("PEM 私钥块", "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA PRIVATE KEY-----"),
)

#: 缺陷态变异的锚点（与 mcp_server.py 的当前行尾无关，_apply 时按实际行尾折算）。
_REVERT_OLD = '            if _red93 and _red93 != a.get("content", ""):'
_REVERT_NEW = '            if False:'
#: G6 锚点：写回那一行（去缩进后比较，避免行尾/缩进差异造成假红）。
_WRITEBACK = 'if _red93 and _red93 != a.get("content", ""):'

#: 行为面正文：六要素齐（不被 required 规则拒），末尾带真形态 AKIA 样例。
_SECRET = "AKIAIOSFODNN7EXAMPLE"


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


def _branch_segment():
    with open(os.path.join(HERE, "mcp_server.py"), encoding="utf-8") as fh:
        src = fh.read()
    i = src.find('if name == "mdcg_remember":')
    return src, (src[i:i + 4000] if i >= 0 else "")


def _behavior():
    """隔离根下真调一次 mdcg_remember，返回 (committed, 明文命中文件, 节点文件)。"""
    from md_cg.mdcos import MdCGSecure
    from md_cg import mcp_server as ms
    cg = MdCGSecure(os.path.join(_SANDBOX, "graph"), autoflush=1)
    text = ("# 功能名：u93 打码行为探针\n"
            "# 生效条件：隔离根下的工具面写入\n"
            "# 子功能：验证明文凭据不落盘\n"
            "# 执行：call_tool mdcg_remember 写一条正文\n"
            "# 验证方式：扫盘面查明文\n"
            "# 不适用条件：不涉及 guest 读面\n"
            "key=" + _SECRET + "\n")
    try:
        r = ms.call_tool(cg, "mdcg_remember", {
            "content": text, "content_kind": "text", "layer": "knowledge",
            "node_id": "u93_probe_redaction"})
    finally:
        try:
            cg.close()
        except Exception:                     # noqa: BLE001
            pass
    committed = bool(isinstance(r, dict) and r.get("committed"))
    plain_hits, node_files = [], []
    for root, _dd, ff in os.walk(_SANDBOX):
        for f in ff:
            p = os.path.join(root, f)
            if "u93_probe_redaction" in f:
                node_files.append(os.path.relpath(p, _SANDBOX))
            try:
                with open(p, "rb") as fh:
                    b = fh.read()
            except OSError:
                continue
            if _SECRET.encode() in b:
                plain_hits.append(os.path.relpath(p, _SANDBOX))
    return committed, plain_hits, node_files


def main():
    from md_cg import audit
    rules = audit.load_rulebook()
    if isinstance(rules, tuple):
        rules = rules[0]

    for label, text in CASES:
        red = audit.redact_forbidden(text, rules)
        check("G1 %s ⇒ 被脱敏（原文不再出现）" % label,
              red != text and text not in red, str(red)[:60])

    # G2 静态：分支体内真的调了 redact_forbidden
    src, seg = _branch_segment()
    check("G2 静态：mdcg_remember 分支体内调用 redact_forbidden",
          "redact_forbidden" in seg, "分支体长度=%d" % len(seg))

    # G3 不误伤
    plain = "# 功能名：t\n# 执行：端口是 5432\n"
    check("G3 普通内容经 redact_forbidden 逐字不变",
          audit.redact_forbidden(plain, rules) == plain, "")

    # G4 同源：命中的规则确在 policy.json 的 forbidden 里
    pol = open(os.path.join(REPO, "data", "policy.json"), encoding="utf-8").read()
    check("G4 与 policy.json 同源（AKIA 规则在其中）",
          "AKIA" in pol, "")

    # G5 行为面（#429 补）：真写一次，明文不得落盘；同时钉住「确实写进去了」
    try:
        committed, plain_hits, node_files = _behavior()
        ok5 = committed and (not plain_hits) and bool(node_files)
        detail = "committed=%r 明文命中=%r 节点文件=%r" % (
            committed, plain_hits[:3], node_files[:2])
    except Exception as exc:                   # noqa: BLE001
        ok5, detail = False, "EXC:%s: %s" % (type(exc).__name__, exc)
    check("G5 行为：mdcg_remember 写入后明文凭据不落盘（且 committed 且节点文件在）",
          ok5, detail)

    # G6 防回退锚点（#429 补）：G2 只判「调了」，调用而不写回时 G2 仍绿。
    lines = [ln.strip() for ln in seg.splitlines()]
    check("G6 防回退锚点：分支体内存在「打码结果写回 content」那一行",
          _WRITEBACK in lines, "锚点=%s" % _WRITEBACK)

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


# ---------------------------------------------------------------- 定点变异腿
def _mirror_build():
    dst = tempfile.mkdtemp(prefix="i93_mut_")
    for name in ("md_cg", "data", "scripts"):
        src = os.path.join(REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(REPO)):
        p = os.path.join(REPO, name)
        if os.path.isfile(p) and name.endswith(".py"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for k in ("MDCG_ROOT", "MDCG_AUX_ROOT", "MDCG_STATE_ROOT", "MDCG_DATA_ROOT",
              "MDCG_MASTER_KEY", "MDCG_TOKEN", "MDCG_VERIFY_KEY",
              "MDCG_TOKEN_FILE", "MDCG_EXPORT_ROOT"):
        env.pop(k, None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue93_remember_redaction"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=900)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln[len("[FAIL] "):].strip().split(" ")[0]
            for ln in out.splitlines() if ln.startswith("[FAIL] ")]
    return pr.returncode, reds, out


_EXPECT = ("G5", "G6")


def _mutate():
    print("!! 定点变异自证：撤回「打码结果写回 content」一行，G5/G6 必须转红")
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%r（必须 rc=0 且 0 红）" % (rc, reds))
        if rc != 0 or reds:
            bad.append("未变异镜像基线即红")
            print("\n".join(out.splitlines()[-20:]))
        p = os.path.join(tree, "md_cg", "mcp_server.py")
        with open(p, encoding="utf-8", newline="") as f:
            bak = f.read()
        eol = "\r\n" if "\r\n" in bak else "\n"
        old = _REVERT_OLD.replace("\n", eol)
        if bak.count(old) != 1:
            bad.append("回退锚点命中 %d 次" % bak.count(old))
            print("  ANCHOR-MISS 回退锚点命中 %d 次" % bak.count(old))
        else:
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(bak.replace(old, _REVERT_NEW.replace("\n", eol), 1))
            for root, _dd, _ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            hit = sorted(set(reds2))
            print("  变异后：rc=%d 红项=%r" % (rc2, hit))
            if rc2 != 0 and hit == sorted(_EXPECT):
                print("  OK   回退即红：指定红项 %r 全部命中" % (hit,))
            else:
                bad.append("回退后红项不符预期")
                print("  MISMATCH 实际=%r 期望=%r" % (hit, sorted(_EXPECT)))
                for ln in out2.splitlines():
                    if ln.startswith("[FAIL] "):
                        print("        " + ln)
        print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


if __name__ == "__main__":
    try:
        _rc = main()
        if "--mutate" in sys.argv and _rc == 0:
            _rc = 1 if _mutate() else 0
    finally:
        shutil.rmtree(_SANDBOX, ignore_errors=True)
    sys.exit(_rc)
