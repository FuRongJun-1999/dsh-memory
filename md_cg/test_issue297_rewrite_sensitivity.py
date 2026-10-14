# -*- coding: utf-8 -*-
"""写面密级继承守卫（issue #297）。

【守什么】
#297 报：同 id 改写既有 private 节点时不重传 sensitivity，节点被**重建为
internal 明文**落盘，无令牌访客 \`cg(op=read)\` 即可读到新正文。

复核**成立**（本机实测，与报告逐字一致）：
  首写 sensitivity=private → 改写（不带 sensitivity）后 frontmatter 变成
  \`sensitivity: "internal"\`、正文明文命中、访客可读新正文 = True；
  缺省 confirm 档下变更单记录里的 sensitivity 也已是 internal。

病灶：\`MdCG.add\` 是**全量重建 fm**——层位（N221）、生命周期状态、检验强度、
验证态、依赖、双时间轴都逐列显式继承了，密级是唯一没接继承的那一列：
\`MdCGSecure.add\`/\`propose\` 一律 \`sensitivity or DEFAULT_SENSITIVITY\`。

修法（单点 \`MdCGSecure._write_sensitivity\`，add/propose 同时接线）：
  显式声明优先；未声明 + 无既有节点 → DEFAULT_SENSITIVITY（新写入面零变化）；
  未声明 + 有既有节点 → **继承其密级**；密级判不了（非法/读不出/被判为坏节点
  隔离）→ fail-closed 抛 AccessDenied，不静默回落明文档。
  缺省 confirm 档的继承必须发生在 **propose 入队时**——提案记录若在入队时就已
  降成 internal，accept 只会照抄该值，故只补落盘面不够。

判据：
  S1  结构：add/propose 都走 _write_sensitivity；_write_sensitivity 四分支在位。
  S2  ★ 直写档同 id 改写不带 sensitivity ⇒ 仍 private + 正文密文 + 访客读不到。
  S3  ★ 缺省 confirm 档：**变更单记录**的 sensitivity 已是 private；accept 后仍 private。
  S4  新写入面零变化：新节点不声明 → internal。
  S5  显式声明优先：显式 internal 覆盖既有 private（主动改密级是合法动作）。
  S6  密级判不了 → fail-closed 抛 AccessDenied；**显式声明是逃生口**（可照常修复写入）。
  S7  反陈化：理由在源码里（#297 / 全量重建 fm / 继承 / fail-closed）。
  S8  修复前原形：git log -S 定位引入提交取父版本；**未提交时回落 HEAD**
      （不假设 HEAD 处于某历史状态——项目方在 #277 踩过该坑）。
  S9  既有语义不破：B2「声明↔落盘」一致性闸仍在位；层闸仍拒越权。

运行：python -X utf8 -m md_cg.test_issue297_rewrite_sensitivity
      python -X utf8 -m md_cg.test_issue297_rewrite_sensitivity --mutate
"""
from __future__ import annotations

import glob
import io
import json
import os
import subprocess
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="i297g_")
# ★ 目录名不可用 "aux"——AUX 是 Windows 保留设备名（#245 实测踩到）。
for _k in ("HOME", "MDCG_ROOT", "MDCG_AUX_ROOT", "MDCG_STATE_ROOT",
           "MDCG_DATA_ROOT", "MDCG_EXPORT_ROOT"):
    os.environ[_k] = os.path.join(_TMP, _k.lower())
    os.makedirs(os.environ[_k], exist_ok=True)
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
os.environ["MDCG_SUSTAIN"] = "0"

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import autonomy_modes as _am        # noqa: E402

#: 档位 env 的键名一律取自唯一入口模块（仓内惯例，见 test_autonomy_modes）——
#: test_autonomy_modes 的 G 组全仓扫描「带引号的档位 env 名只许出现在
#: autonomy_modes.py」，在测试里写死该字面量会打红那条反漂移判据。
_ENV_MODE = _am.AUTONOMY_ENV_KEYS["mode"]
from md_cg import mcp_server                   # noqa: E402
from md_cg import mdcg as _mdcg                # noqa: E402
from md_cg.mdcos import MdCGSecure             # noqa: E402
from md_cg.security import AccessDenied, Principal   # noqa: E402
from md_cg.tokens import role_spec             # noqa: E402

_ROOT = os.environ["MDCG_ROOT"]
_OK = 0
_BAD = []


def _check(name, cond, detail=""):
    global _OK
    if cond:
        _OK += 1
        print("  ok   %s" % name)
    else:
        _BAD.append(name)
        print("  FAIL %s  %s" % (name, detail))


def _cg(role, clearance, **kw):
    sp = role_spec(role)
    return MdCGSecure(_ROOT, principal=Principal(
        actor=role, clearance=clearance, can_write=role != "guest",
        can_admin=role == "designer", role=role,
        layers_allow=sp["layers_allow"], ops_allow=sp["ops_allow"], **kw))


def _fm(nid):
    fs = glob.glob(_ROOT + "/**/%s.md" % nid, recursive=True)
    return io.open(fs[0], encoding="utf-8").read() if fs else ""


def _guest_reads(nid, mark):
    g = _cg("guest", "internal", auth_mode="anonymous")
    try:
        r = mcp_server._dispatch(g, "cg", {"op": "read", "node_id": nid})
    finally:
        g.close()
    return mark in json.dumps(r, ensure_ascii=False, default=str)


def _src(rel):
    return io.open(os.path.join(_REPO, rel), encoding="utf-8",
                   errors="replace").read()


def _body(name):
    # 取**最后一个**同名方法：mdcos.py 里 MdCGOS 与 MdCGSecure 都有 add/propose，
    # index() 会取到父类那个（本件改的是子类 MdCGSecure）。
    src = _src(os.path.join("md_cg", "mdcos.py"))
    i0 = src.rindex("    def %s(" % name)
    nxt = src.find("\n    def ", i0 + 10)
    return src[i0:nxt if nxt > 0 else len(src)]


def s1():
    print("== S1 结构：单点 + 两处接线 ==")
    a = _body("add")
    p = _body("propose")
    w = _body("_write_sensitivity")
    _check("S1a add 走 _write_sensitivity", "_write_sensitivity(node_id" in a)
    # 判据钉**赋值式**而非短语：切片会带上后一个方法的「生效条件」注释行，
    # 而那句话本身就含该短语（按短语判会误红）。
    _check("S1b add **不再**用 sensitivity or DEFAULT_SENSITIVITY",
           "sens = sensitivity or DEFAULT_SENSITIVITY" not in a)
    _check("S1c propose 走 _write_sensitivity", "_write_sensitivity(node_id" in p)
    _check("S1d propose **不再**用 sensitivity or DEFAULT_SENSITIVITY",
           "sens = sensitivity or DEFAULT_SENSITIVITY" not in p)
    _check("S1e 显式声明短路在位", "if declared:" in w)
    _check("S1f 继承既有密级（索引优先、回读兜底）",
           "subgraph.node_sensitivity" in w)
    _check("S1g 判不了 fail-closed（抛 AccessDenied）",
           "AccessDenied" in w)
    _check("S1h 坏节点隔离面也在判据内（#146）",
           "_quarantined" in w)
    _check("S1i 无既有节点回落 DEFAULT_SENSITIVITY",
           "return DEFAULT_SENSITIVITY" in w)


def s2():
    print("== S2 ★ 直写档：同 id 改写不带 sensitivity ==")
    # 档位字面量一律取自唯一入口模块 autonomy_modes——test_autonomy_modes 的
    # G 组全仓扫描「带引号的档位 env 字面量只许出现在 autonomy_modes.py」，
    # 在测试里硬编码档位串会打红那条反漂移判据（本件首轮实测即此）。
    os.environ[_ENV_MODE] = _am.MODE_FULL
    d = _cg("designer", "secret", session="s2")
    mcp_server._dispatch(d, "mdcg_remember", {"node_id": "p1",
        "content": "PRIV-A1 原文 银行卡密码是生日", "layer": "knowledge",
        "sensitivity": "private"})
    _check("S2-pre 首写落盘 private",
           'sensitivity: "private"' in _fm("p1"), _fm("p1")[:160])
    mcp_server._dispatch(d, "mdcg_remember", {"node_id": "p1",
        "content": "PRIV-B2 改写后的新正文 备用金藏在书架",
        "layer": "knowledge"})
    f = _fm("p1")
    _check("S2a ★ 改写后仍为 private（改前=internal）",
           'sensitivity: "private"' in f, f[:200])
    _check("S2b 新正文以密文落盘（盘面无明文）", "PRIV-B2" not in f)
    _check("S2c ★ 无令牌访客读不到新正文（改前=True）",
           not _guest_reads("p1", "PRIV-B2"))
    d.close()


def s3():
    print("== S3 ★ 缺省 confirm 档：变更单 → accept ==")
    os.environ.pop(_ENV_MODE, None)                # 缺省档 = confirm
    d = _cg("designer", "secret", session="s3")
    mcp_server._dispatch(d, "mdcg_remember", {"node_id": "p2",
        "content": "PRIV-C3 原文 护照号", "layer": "knowledge",
        "sensitivity": "private"})
    r = mcp_server._dispatch(d, "mdcg_remember", {"node_id": "p2",
        "content": "PRIV-D4 审核后新正文 签证材料", "layer": "knowledge"})
    pid = r.get("pid")
    _check("S3a 出变更单", bool(pid) and r.get("moved_to") == "review_queue",
           json.dumps(r, ensure_ascii=False, default=str)[:200])
    rec = []
    for c in glob.glob(_ROOT + "/**/*inbox*.jsonl", recursive=True):
        for x in io.open(c, encoding="utf-8"):
            if x.strip():
                try:
                    o = json.loads(x)
                except Exception:                  # noqa: BLE001
                    continue
                if o.get("pid") == pid:
                    rec.append(o)
    _check("S3b ★ 变更单记录密级已是 private（改前=internal）",
           bool(rec) and rec[0].get("sensitivity") == "private",
           rec[0].get("sensitivity") if rec else "无记录")
    mcp_server._dispatch(d, "cg", {"op": "review", "pid": pid,
                                   "decision": "accept", "reason": "守卫"})
    f = _fm("p2")
    _check("S3c accept 后仍为 private", 'sensitivity: "private"' in f, f[:200])
    _check("S3d accept 后新正文无明文", "PRIV-D4" not in f)
    _check("S3e 访客读不到", not _guest_reads("p2", "PRIV-D4"))
    d.close()


def s4():
    print("== S4 新写入面零变化 ==")
    os.environ[_ENV_MODE] = _am.MODE_FULL
    d = _cg("designer", "secret", session="s4")
    mcp_server._dispatch(d, "mdcg_remember", {"node_id": "n1",
        "content": "普通新节点正文", "layer": "knowledge"})
    _check("S4a 新节点不声明 → internal",
           'sensitivity: "internal"' in _fm("n1"), _fm("n1")[:160])
    mcp_server._dispatch(d, "mdcg_remember", {"node_id": "n1",
        "content": "普通节点改写", "layer": "knowledge"})
    _check("S4b internal 节点改写仍 internal",
           'sensitivity: "internal"' in _fm("n1"))
    d.close()


def s5():
    print("== S5 显式声明优先 ==")
    d = _cg("designer", "secret", session="s5")
    # ★ 本组自建夹具，**不依赖 S2 的副作用**：组间夹具依赖会让「上游组先红了
    #   就顺带打红本组」与「本组真的判错」不可分（V2 变异实测踩到——S2 抛异常
    #   后 p1 根本没建出来，S5 便在空夹具上假绿）。
    mcp_server._dispatch(d, "mdcg_remember", {"node_id": "p5",
        "content": "PRIV-E5 原文", "layer": "knowledge",
        "sensitivity": "private"})
    _check("S5-pre 夹具已建成 private",
           'sensitivity: "private"' in _fm("p5"), _fm("p5")[:160])
    mcp_server._dispatch(d, "mdcg_remember", {"node_id": "p5",
        "content": "PRIV-F7 显式改密级后的正文", "layer": "knowledge",
        "sensitivity": "internal"})
    _check("S5a 显式 internal 覆盖既有 private（主动改密级是合法动作）",
           'sensitivity: "internal"' in _fm("p5"), _fm("p5")[:160])
    _check("S5b 显式声明不因继承而被改写（正文按新密级落盘）",
           "PRIV-F7" in _fm("p5"))
    d.close()


def s6():
    print("== S6 密级判不了 → fail-closed（含逃生口）==")
    d = _cg("designer", "secret", session="s6")
    mcp_server._dispatch(d, "mdcg_remember", {"node_id": "bad1",
        "content": "先建一个正常节点", "layer": "knowledge",
        "sensitivity": "restricted"})
    fs = glob.glob(_ROOT + "/**/bad1.md", recursive=True)
    if not fs:
        _check("S6 夹具节点未落盘", False, "bad1.md 未找到")
        d.close()
        return
    txt = io.open(fs[0], encoding="utf-8").read()
    with io.open(fs[0], "w", encoding="utf-8", newline="") as fh:
        fh.write(txt.replace('sensitivity: "restricted"', 'sensitivity: "机密"'))
    d2 = _cg("designer", "secret", session="s6b")   # 新实例：不吃旧索引
    try:
        mcp_server._dispatch(d2, "mdcg_remember", {"node_id": "bad1",
            "content": "改写损坏密级的节点", "layer": "knowledge"})
        _check("S6a 密级损坏时 fail-closed 拒写", False, "未拒（静默回落）")
    except AccessDenied as exc:
        _check("S6a 密级损坏时 fail-closed 拒写", True)
        print("       %s" % str(exc)[:110])
    except Exception as exc:                        # noqa: BLE001
        _check("S6a 密级损坏时 fail-closed 拒写", False,
               "%s: %s" % (type(exc).__name__, str(exc)[:110]))
    try:
        mcp_server._dispatch(d2, "mdcg_remember", {"node_id": "bad1",
            "content": "显式声明后写入", "layer": "knowledge",
            "sensitivity": "restricted"})
        _check("S6b 显式声明 sensitivity 是逃生口（可照常修复写入）", True)
    except Exception as exc:                        # noqa: BLE001
        _check("S6b 显式声明 sensitivity 是逃生口（可照常修复写入）", False,
               "%s: %s" % (type(exc).__name__, str(exc)[:110]))
    d.close()
    d2.close()


def s7():
    print("== S7 反陈化：理由在源码里 ==")
    src = _src(os.path.join("md_cg", "mdcos.py"))
    _check("S7a 标注 issue #297", "issue #297" in src)
    _check("S7b 写明「全量重建 fm」是根因面", "全量重建 fm" in src)
    _check("S7c 写明密级是唯一没接继承的那一列",
           "唯一没接继承的那一列" in src)
    _check("S7d 写明 fail-closed 不静默回落明文档", "静默回落明文档" in src)
    _check("S7e 写明 confirm 档必须在 propose 入队时继承",
           "入队时就已降成 internal" in src or "accept 只会照抄" in src)


def _prepatch_src():
    def _g(*a):
        return subprocess.run(list(a), cwd=_REPO, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=60)
    lg = _g("git", "log", "-S_write_sensitivity", "--format=%H", "--",
            "md_cg/mdcos.py")
    if lg.returncode == 0:
        shas = [x.strip() for x in (lg.stdout or "").splitlines() if x.strip()]
        if shas:
            s = _g("git", "show", shas[-1] + "^:md_cg/mdcos.py")
            if s.returncode == 0:
                return s.stdout, "引入提交 %s 的父版本" % shas[-1][:8]
    s = _g("git", "show", "HEAD:md_cg/mdcos.py")
    if s.returncode != 0:
        return None, "git show HEAD rc=%s" % s.returncode
    return s.stdout, "HEAD（本改动尚未提交）"


def s8():
    print("== S8 修复前原形（提交前/后都稳定）==")
    t, how = _prepatch_src()
    if t is None:
        _check("S8 取修复前源失败：%s" % how, False)
        return
    print("       （修复前源取自 %s）" % how)
    _check("S8a 修复前无 _write_sensitivity", "_write_sensitivity" not in t)
    _check("S8b ★ 修复前的 add 确是「sensitivity or DEFAULT_SENSITIVITY」原形",
           "sens = sensitivity or DEFAULT_SENSITIVITY" in t)


def s9():
    print("== S9 既有语义不破 ==")
    try:
        _mdcg._check_sensitivity_landing("n1", "internal", "private", "明文")
        _check("S9a B2「声明↔落盘」一致性闸仍在位", False, "未抛")
    except ValueError:
        _check("S9a B2「声明↔落盘」一致性闸仍在位", True)
    _mdcg._check_sensitivity_landing("n1", "internal", None, "明文")
    _check("S9b 未声明（declared=None）不触发一致性闸", True)
    # 层闸仍拒越权：internal clearance 的身份写不进 private
    d = _cg("designer", "secret", session="s9")
    mcp_server._dispatch(d, "mdcg_remember", {"node_id": "p9",
        "content": "PRIV-F6 原文", "layer": "knowledge",
        "sensitivity": "private"})
    g = _cg("record", "internal", session="s9b")
    try:
        g.add("p9", "越权改写", layer="knowledge")
        _check("S9c 继承 private 后层闸仍拒 internal 身份覆写", False, "未拒")
    except AccessDenied:
        _check("S9c 继承 private 后层闸仍拒 internal 身份覆写", True)
    except Exception as exc:                        # noqa: BLE001
        _check("S9c 继承 private 后层闸仍拒 internal 身份覆写", False,
               "%s: %s" % (type(exc).__name__, str(exc)[:110]))
    d.close()
    g.close()


_GROUPS = (s1, s2, s3, s4, s5, s6, s7, s8, s9)


def _run_groups():
    global _OK
    _OK = 0
    _BAD.clear()
    for idx, g in enumerate(_GROUPS, 1):
        try:
            g()
        except Exception as exc:                    # noqa: BLE001
            # 组异常也按 **S<序号>** 命名：定点变异常把实现改成自相矛盾，
            # 此时判据不是「断言不成立」而是「调用直接抛」——两者都是该组转红，
            # 变异表按 S 前缀核对才不漏（V2 实测即此形态：B2 一致性闸拦下）。
            _check("S%d 组异常（%s）：%s" % (idx, g.__name__, exc), False)
            import traceback
            print(traceback.format_exc()[-600:])
    return len(_BAD)


def main():
    n = _run_groups()
    print()
    print("写面密级继承守卫：%d 通过，%d 失败" % (_OK, n))
    return 1 if n else 0


_MUTATIONS = (
    ("V1 add 回到 sensitivity or DEFAULT_SENSITIVITY（本件病象）",
     "        sens = self._write_sensitivity(node_id, sensitivity)\n",
     "        sens = sensitivity or DEFAULT_SENSITIVITY\n", "S2"),
    ("V2 去掉显式声明短路（显式声明被继承值覆盖）",
     "        if declared:\n            return declared\n",
     "", "S5"),
    ("V3 判不了时静默回落缺省档（去掉隔离 fail-closed）",
     "            raise AccessDenied(\n"
     "                \"写入 %r 未声明 sensitivity，而该 id 已被判为坏节点隔离\"\n",
     "            return DEFAULT_SENSITIVITY\n"
     "            raise AccessDenied(\n"
     "                \"写入 %r 未声明 sensitivity，而该 id 已被判为坏节点隔离\"\n",
     "S6"),
)


def _reload():
    import importlib
    from md_cg import mdcos as _m
    importlib.reload(_m)
    globals()["MdCGSecure"] = _m.MdCGSecure


def _mutate():
    bad = []
    p = os.path.join(_REPO, "md_cg", "mdcos.py")
    with io.open(p, encoding="utf-8", newline="") as f:
        pristine = f.read()
    if "_write_sensitivity" not in pristine:
        print("  SOURCE-ALREADY-MUTATED：mdcos.py 缺 _write_sensitivity")
        return 1
    for name, anchor, repl, want in _MUTATIONS:
        with io.open(p, encoding="utf-8", newline="") as f:
            orig = f.read()
        NL = "\r\n" if "\r\n" in orig else "\n"
        a_ = anchor.replace("\n", NL)
        r_ = repl.replace("\n", NL)
        try:
            if a_ not in orig:
                print("  ANCHOR-MISS %s" % name)
                bad.append(name)
                continue
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(orig.replace(a_, r_, 1))
            _reload()
            _run_groups()
            reds = list(_BAD)
            hit = any(x.startswith(want) for x in reds)
            print("  %-4s %-52s 红项=%-3d 命中%s=%s"
                  % ("OK" if hit else "BAD", name, len(reds), want,
                     "是" if hit else "否"))
            if not hit:
                bad.append(name)
        finally:
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(pristine)
            with io.open(p, encoding="utf-8", newline="") as f:
                if f.read() != pristine:
                    print("  RESTORE-FAILED %s" % name)
                    bad.append(name + "(恢复失败)")
            _reload()
    if bad:
        print()
        print("定点变异自证：FAIL -- %s" % "、".join(bad))
        return 1
    print()
    print("定点变异自证：PASS（每处判据都被打红）")
    return 0


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(_mutate())
    sys.exit(main())
