# -*- coding: utf-8 -*-
"""兄弟写入口密级继承守卫（issue #439）。

【守什么】
#439 报：#297 的「未声明 ⇒ 继承既有节点密级」只接在 \`add\`/\`propose\` 两个
入口；三个兄弟写入口 \`add_goal\`/\`add_rejected\`/\`add_unresolved\` 仍用
\`sensitivity or DEFAULT_SENSITIVITY\` 把「未声明」折叠成 internal，改写既有
restricted/private 节点（不重传密级）时**静默降级**，与 #297 修复要防的场景
同形。\`add_rejected\` 尤其隐蔽：基类对同 hypothesis 幂等短路不重写正文，
安全层却无条件按缺省档 \`_index_sensitivity\`——正文幂等不变、密级被降，
最易被「幂等=没动」的直觉漏过。

复核**成立**（本机实测，与报告读数一致）：
  goal/rejected/unresolved 既有 restricted 节点、未声明密级改写后
  索引密级全部降为 internal；直接 \`add\`（#297 已修入口）正常继承。

修法（与 #297 同款接线 + 幂等键单点）：
  · 三入口先按**基类幂等键**算出 nid（\`_rejected_nid\`/\`_unresolved_nid\`/
    \`_goal_nid\`，基类去重与安全层继承判定共用同一键——键漂移即继承失配，
    回落缺省档＝降级）；
  · \`sens = self._write_sensitivity(nid, sensitivity)\`：显式声明优先；
    未声明 + 无既有节点 → DEFAULT_SENSITIVITY（新写入面零变化）；
    未声明 + 有既有节点 → **继承其密级**；判不了 → fail-closed 抛
    AccessDenied；
  · 末尾 \`_index_sensitivity(nid, sens)\` 此时已是继承值：幂等分支重申
    同值，不再是降档。

判据：
  S1  结构：三入口都走 _write_sensitivity、不再用旧式；幂等键单点在位
      （mdcg 助手 + 双侧接线）。
  S2  ★ add_goal 同 gid 改写不带 sensitivity ⇒ 盘面 fm 仍 private +
      正文密文 + 低权读不到（add_goal 是全量重建，fm 本体被降＝盘面级）。
  S3  ★ add_rejected 同 hypothesis 幂等再记（不带 sensitivity）⇒ 索引仍
      restricted（幂等分支的降档面）+ 正文幂等不变 + 低权改写被拒。
  S4  ★ add_unresolved 同题刷新（不带 sensitivity）⇒ 索引仍 restricted +
      正文已按新线索刷新（⑤ 的刷新语义不回退）。
  S5  新写入面零变化：三入口新节点不声明 → internal。
  S6  显式声明优先：显式 internal 覆盖既有 restricted（主动改密级是合法动作）。
  S7  层闸拒越权：internal clearance 身份经三入口改写既有 restricted →
      AccessDenied；新目标（internal 档）不受影响。
  S8  密级判不了 → fail-closed 抛 AccessDenied；显式声明是逃生口。
  S9  既有语义不破：#297 的 add/propose 接线仍在位；B2「声明↔落盘」闸仍在位。
  S10 反陈化：理由在源码里（#439 / 幂等面 / 全量重建 / 键漂移）。
  S11 修复前原形：git log -S 定位引入提交取父版本；未提交时回落 HEAD。
  S12 ★ 幂等键同口径（strip 面）：不同首尾空白 → 同 gid，不另建第二节点、
      不因键漂移回落缺省档。

运行：python -X utf8 -m md_cg.test_issue439_sibling_write_sensitivity
      python -X utf8 -m md_cg.test_issue439_sibling_write_sensitivity --mutate
"""
from __future__ import annotations

import glob
import io
import json
import os
import subprocess
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="i439g_")
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

#: 档位 env 的键名/取值一律取自唯一入口模块（test_autonomy_modes 的 G 组
#: 全仓扫描「带引号的档位字面量只许出现在 autonomy_modes.py」）。
_ENV_MODE = _am.AUTONOMY_ENV_KEYS["mode"]
os.environ[_ENV_MODE] = _am.MODE_FULL          # 直写面：不走 confirm 审核队列
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


def _idx(d, nid):
    return (d.index["nodes"].get(nid) or {}).get("sensitivity")


def _low_reads(nid, mark):
    """record/internal 身份能否读到该节点正文（restricted ⇒ 读不到）。"""
    r = _cg("record", "internal", session="low")
    try:
        try:
            resp = mcp_server._dispatch(r, "cg", {"op": "read", "node_id": nid})
        except AccessDenied:
            return False
        return mark in json.dumps(resp, ensure_ascii=False, default=str)
    finally:
        r.close()


def _src(rel):
    return io.open(os.path.join(_REPO, rel), encoding="utf-8",
                   errors="replace").read()


def _body(rel, name):
    # 取**最后一个**同名方法：mdcos.py 里 MdCGOS 与 MdCGSecure 都可能有
    # 同名方法（本件改的是子类 MdCGSecure 的三入口）。
    src = _src(rel) if isinstance(rel, str) and rel.endswith(".py") else rel
    i0 = src.rindex("    def %s(" % name)
    nxt = src.find("\n    def ", i0 + 10)
    return src[i0:nxt if nxt > 0 else len(src)]


_MDCOS = os.path.join("md_cg", "mdcos.py")
_MDCG = os.path.join("md_cg", "mdcg.py")


def s1():
    print("== S1 结构：三入口接线 + 幂等键单点 ==")
    r = _body(_MDCOS, "add_rejected")
    u = _body(_MDCOS, "add_unresolved")
    g = _body(_MDCOS, "add_goal")
    _check("S1a add_rejected 走 _write_sensitivity",
           "self._write_sensitivity(nid, sensitivity)" in r)
    _check("S1b add_rejected **不再**用 sensitivity or DEFAULT_SENSITIVITY",
           "sens = sensitivity or DEFAULT_SENSITIVITY" not in r)
    _check("S1c add_unresolved 走 _write_sensitivity",
           "self._write_sensitivity(nid, sensitivity)" in u)
    _check("S1d add_unresolved **不再**用 sensitivity or DEFAULT_SENSITIVITY",
           "sens = sensitivity or DEFAULT_SENSITIVITY" not in u)
    _check("S1e add_goal 走 _write_sensitivity",
           "self._write_sensitivity(gid, sensitivity)" in g)
    _check("S1f add_goal **不再**用 sensitivity or DEFAULT_SENSITIVITY",
           "sens = sensitivity or DEFAULT_SENSITIVITY" not in g)
    # 幂等键单点：基类助手 + 双侧接线（安全层另算一份哈希＝键漂移＝继承失配）
    b_r = _body(_MDCG, "add_rejected")
    b_u = _body(_MDCG, "add_unresolved")
    b_g = _body(_MDCG, "add_goal")
    src_b = _src(_MDCG)
    _check("S1g 基类幂等键助手在位（_rejected_nid/_unresolved_nid/_goal_nid）",
           all("def _%s_nid(" % w in src_b
               for w in ("rejected", "unresolved", "goal")))
    _check("S1h 基类三方法用同一助手（单点，不是各算各的）",
           "self._rejected_nid(hypothesis)" in b_r
           and "self._unresolved_nid(question, topic)" in b_u
           and "self._goal_nid(goal)" in b_g)
    _check("S1i 安全层三入口先按同键算 nid 再继承",
           "self._rejected_nid(hypothesis)" in r
           and 'self._unresolved_nid(question, kw.get("topic"))' in u
           and "self._goal_nid(goal)" in g)


def s2():
    print("== S2 ★ add_goal：同 gid 全量重建不带 sensitivity ==")
    d = _cg("designer", "secret", session="s2")
    gid = d.add_goal("S2 目标：把检索延迟降到 100ms 以内", sensitivity="private")
    _check("S2-pre 首写落盘 private",
           'sensitivity: "private"' in _fm(gid), _fm(gid)[:160])
    gid2 = d.add_goal("S2 目标：把检索延迟降到 100ms 以内")
    _check("S2-pre2 同 gid（幂等键一致）", gid2 == gid)
    f = _fm(gid)
    _check("S2a ★ 改写后盘面仍为 private（改前=internal）",
           'sensitivity: "private"' in f, f[:200])
    _check("S2b ★ 索引密级仍 private（改前=internal）",
           _idx(d, gid) == "private", repr(_idx(d, gid)))
    _check("S2c ★ 低权（internal clearance）读不到该目标正文",
           not _low_reads(gid, "检索延迟"))
    d.close()


def s3():
    print("== S3 ★ add_rejected：同 hypothesis 幂等再记 ==")
    d = _cg("designer", "secret", session="s3")
    nid = d.add_rejected("S3 假设：索引重建可省略代际检查",
                         "S3 理由甲", sensitivity="restricted")
    f0 = _fm(nid)
    _check("S3-pre 首写落盘 restricted",
           'sensitivity: "restricted"' in f0, f0[:160])
    nid2 = d.add_rejected("S3 假设：索引重建可省略代际检查", "S3 理由乙")
    _check("S3-pre2 同 nid（幂等键一致）", nid2 == nid)
    _check("S3a ★ 幂等分支索引密级仍 restricted（改前=internal：正文没动、"
           "密级被降——最易被「幂等=没动」的直觉漏过）",
           _idx(d, nid) == "restricted", repr(_idx(d, nid)))
    _check("S3b 盘面 fm 仍 restricted（幂等短路不动文件）",
           'sensitivity: "restricted"' in _fm(nid))
    _check("S3c 正文幂等不变（首记理由在、再记理由不在）",
           "S3 理由甲" in _fm(nid) and "S3 理由乙" not in _fm(nid))
    d.close()


def s4():
    print("== S4 ★ add_unresolved：同题刷新现场 ==")
    d = _cg("designer", "secret", session="s4")
    nid = d.add_unresolved("S4 问题：两批对照取值不一致", "S4 线索旧", "S4 目标",
                           sensitivity="restricted")
    _check("S4-pre 首写落盘 restricted",
           'sensitivity: "restricted"' in _fm(nid), _fm(nid)[:160])
    nid2 = d.add_unresolved("S4 问题：两批对照取值不一致", "S4 线索新", "S4 目标")
    _check("S4-pre2 同 nid（工单 slug 一致）", nid2 == nid)
    _check("S4a ★ 刷新分支索引密级仍 restricted（改前=internal）",
           _idx(d, nid) == "restricted", repr(_idx(d, nid)))
    _check("S4b 正文已按新线索刷新（⑤ 的刷新语义不回退）",
           "S4 线索新" in _fm(nid) and "S4 线索旧" not in _fm(nid))
    _check("S4c 盘面 fm 仍 restricted（_refresh_unresolved 只覆写正文保 fm）",
           'sensitivity: "restricted"' in _fm(nid))
    d.close()


def s5():
    print("== S5 新写入面零变化 ==")
    d = _cg("designer", "secret", session="s5")
    gid = d.add_goal("S5 全新目标")
    nid = d.add_rejected("S5 全新假设", "S5 理由")
    uid = d.add_unresolved("S5 全新问题", "S5 线索", "S5 目标")
    _check("S5a 新 goal 不声明 → internal", _idx(d, gid) == "internal",
           repr(_idx(d, gid)))
    _check("S5b 新 rejected 不声明 → internal", _idx(d, nid) == "internal",
           repr(_idx(d, nid)))
    _check("S5c 新 unresolved 不声明 → internal", _idx(d, uid) == "internal",
           repr(_idx(d, uid)))
    _check("S5d 新 goal 盘面 fm 亦 internal（新写面与修复前逐字同形）",
           'sensitivity: "internal"' in _fm(gid), _fm(gid)[:160])
    d.close()


def s6():
    print("== S6 显式声明优先 ==")
    # ★ 本组自建夹具，不依赖 S2 的副作用（组间夹具依赖会让「上游组先红了就
    #   顺带打红本组」与「本组真的判错」不可分）。
    d = _cg("designer", "secret", session="s6")
    gid = d.add_goal("S6 目标：显式改密级", sensitivity="restricted")
    _check("S6-pre 夹具已建成 restricted",
           'sensitivity: "restricted"' in _fm(gid), _fm(gid)[:160])
    d.add_goal("S6 目标：显式改密级", sensitivity="internal")
    _check("S6a 显式 internal 覆盖既有 restricted（主动改密级是合法动作）",
           'sensitivity: "internal"' in _fm(gid), _fm(gid)[:160])
    _check("S6b 索引同步为 internal", _idx(d, gid) == "internal",
           repr(_idx(d, gid)))
    d.close()


def s7():
    print("== S7 层闸拒越权（internal clearance 改写 restricted）==")
    d = _cg("designer", "secret", session="s7")
    gid = d.add_goal("S7 目标：越权面", sensitivity="restricted")
    nid = d.add_rejected("S7 假设：越权面", "S7 理由", sensitivity="restricted")
    uid = d.add_unresolved("S7 问题：越权面", "S7 线索", "S7 目标",
                           sensitivity="restricted")
    d.close()
    r = _cg("record", "internal", session="s7low")
    for name, fn in (
            ("S7a ★ goal 面", lambda: r.add_goal("S7 目标：越权面")),
            ("S7b ★ rejected 面", lambda: r.add_rejected("S7 假设：越权面",
                                                          "x")),
            ("S7c ★ unresolved 面", lambda: r.add_unresolved("S7 问题：越权面",
                                                              "c", "g"))):
        try:
            fn()
            _check("%s 继承 restricted 后层闸拒 internal 身份覆写" % name,
                   False, "未拒（改前=按缺省档放行＝越权改写他人密级）")
        except AccessDenied:
            _check("%s 继承 restricted 后层闸拒 internal 身份覆写" % name, True)
        except Exception as exc:                    # noqa: BLE001
            _check("%s 继承 restricted 后层闸拒 internal 身份覆写" % name,
                   False, "%s: %s" % (type(exc).__name__, str(exc)[:110]))
    gid_new = r.add_goal("S7 新目标：低权自建（internal 档）")
    _check("S7d 低权建新目标不受影响（新写面未被过度收紧）",
           bool(gid_new) and _idx(r, gid_new) == "internal",
           repr(_idx(r, gid_new)))
    r.close()


def s8():
    print("== S8 密级判不了 → fail-closed（含逃生口）==")
    d = _cg("designer", "secret", session="s8")
    gid = d.add_goal("S8 目标：密级坏掉", sensitivity="restricted")
    d.close()
    fs = glob.glob(_ROOT + "/**/%s.md" % gid, recursive=True)
    if not fs:
        _check("S8 夹具节点未落盘", False, "%s.md 未找到" % gid)
        return
    txt = io.open(fs[0], encoding="utf-8").read()
    with io.open(fs[0], "w", encoding="utf-8", newline="") as fh:
        fh.write(txt.replace('sensitivity: "restricted"', 'sensitivity: "机密"'))
    d2 = _cg("designer", "secret", session="s8b")   # 新实例：不吃旧索引
    # 盘面在快照之后被改坏——_write_sensitivity 取「索引快照优先」，须重扫
    # 让判据面看到坏密级（与 #146 坏节点隔离同一入口；重扫后既可能成
    # 「密级判不了」也可能进隔离，两者都应 fail-closed）。
    d2.rebuild_index()
    try:
        d2.add_goal("S8 目标：密级坏掉")
        _check("S8a 密级损坏时 fail-closed 拒写", False, "未拒（静默回落）")
    except AccessDenied as exc:
        _check("S8a 密级损坏时 fail-closed 拒写", True)
        print("       %s" % str(exc)[:110])
    except Exception as exc:                        # noqa: BLE001
        _check("S8a 密级损坏时 fail-closed 拒写", False,
               "%s: %s" % (type(exc).__name__, str(exc)[:110]))
    try:
        d2.add_goal("S8 目标：密级坏掉", sensitivity="restricted")
        _check("S8b 显式声明 sensitivity 是逃生口（可照常修复写入）", True)
    except Exception as exc:                        # noqa: BLE001
        _check("S8b 显式声明 sensitivity 是逃生口（可照常修复写入）", False,
               "%s: %s" % (type(exc).__name__, str(exc)[:110]))
    d2.close()


def s9():
    print("== S9 既有语义不破（#297 接线 / B2 闸）==")
    a = _body(_MDCOS, "add")
    p = _body(_MDCOS, "propose")
    _check("S9a #297：add 仍走 _write_sensitivity",
           "_write_sensitivity(node_id" in a)
    _check("S9b #297：propose 仍走 _write_sensitivity",
           "_write_sensitivity(node_id" in p)
    try:
        _mdcg._check_sensitivity_landing("n", "internal", "private", "明文")
        _check("S9c B2「声明↔落盘」一致性闸仍在位", False, "未抛")
    except ValueError:
        _check("S9c B2「声明↔落盘」一致性闸仍在位", True)
    _mdcg._check_sensitivity_landing("n", "internal", None, "明文")
    _check("S9d 未声明（declared=None）不触发一致性闸", True)


def s10():
    print("== S10 反陈化：理由在源码里 ==")
    o = _src(_MDCOS)
    b = _src(_MDCG)
    _check("S10a mdcos 标注 issue #439", "issue #439" in o)
    _check("S10b 写明「正文没动、密级被降」是 add_rejected 幂等面病象",
           "正文没动、密级被降" in o)
    _check("S10c 写明 add_goal 是全量重建（与 #297 的 add 同形）",
           "全量重建" in o)
    _check("S10d 写明 _refresh_unresolved 只覆写正文保 fm",
           "_refresh_unresolved 只覆写正文保 fm" in o)
    _check("S10e mdcg 助手写明键漂移即继承失配（回落缺省档＝静默降级）",
           "继承失配" in b and "静默降级" in b)


def _prepatch(relpath, marker):
    def _g(*a):
        return subprocess.run(list(a), cwd=_REPO, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=60)
    # ★ git 的 pathspec/show 语法只认正斜杠（Windows 下 os.path.join 是反斜杠）。
    rel_git = relpath.replace(os.sep, "/")
    lg = _g("git", "log", "-S" + marker, "--format=%H", "--", rel_git)
    if lg.returncode == 0:
        shas = [x.strip() for x in (lg.stdout or "").splitlines() if x.strip()]
        if shas:
            s = _g("git", "show", shas[-1] + "^:" + rel_git)
            if s.returncode == 0:
                return s.stdout, "引入提交 %s 的父版本" % shas[-1][:8]
    s = _g("git", "show", "HEAD:" + rel_git)
    if s.returncode != 0:
        return None, "git show HEAD rc=%s" % s.returncode
    return s.stdout, "HEAD（本改动尚未提交）"


def s11():
    print("== S11 修复前原形（提交前/后都稳定）==")
    t, how = _prepatch(_MDCOS, "_rejected_nid(hypothesis)")
    if t is None:
        _check("S11 取修复前 mdcos 失败：%s" % how, False)
        return
    print("       （修复前源取自 %s）" % how)
    for w in ("add_rejected", "add_unresolved", "add_goal"):
        _check("S11%s 修复前的 %s 确是「sensitivity or DEFAULT_SENSITIVITY」原形"
               % ("a" if w == "add_rejected" else
                  "b" if w == "add_unresolved" else "c", w),
               "sens = sensitivity or DEFAULT_SENSITIVITY" in _body(t, w))
    tb, howb = _prepatch(_MDCG, "def _rejected_nid")
    if tb is None:
        _check("S11 取修复前 mdcg 失败：%s" % howb, False)
        return
    _check("S11d 修复前 mdcg 无幂等键助手（三处各算各的）",
           "def _rejected_nid(" not in tb and "def _goal_nid(" not in tb
           and "def _unresolved_nid(" not in tb)
    _check("S11e 修复前 mdcg 是内联哈希原形（rej_/goal_ 各自拼）",
           "rej_{hashlib" in tb and "goal_{hashlib" in tb)


def s12():
    print("== S12 ★ 幂等键同口径（strip 面）==")
    d = _cg("designer", "secret", session="s12")
    gid = d.add_goal("  S12 目标：首尾空白键  ", sensitivity="restricted")
    _check("S12-pre 夹具已建成 restricted",
           'sensitivity: "restricted"' in _fm(gid), _fm(gid)[:160])
    # 各组共用同一 root：判据取**本组前后差分**，不数别组的目标节点。
    before = {nid for nid, e in d.index["nodes"].items()
              if e.get("layer") == "goals"}
    d.add_goal("\tS12 目标：首尾空白键 \t")        # 不同首尾空白、不声明密级
    after = {nid for nid, e in d.index["nodes"].items()
             if e.get("layer") == "goals"}
    _check("S12a ★ 同一目标（strip 后同键）不另建第二节点", after == before,
           "新增=%s" % sorted(after - before))
    _check("S12b ★ 键不漂移：继承 restricted 而非回落缺省档",
           _idx(d, gid) == "restricted", repr(_idx(d, gid)))
    d.close()


_GROUPS = (s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11, s12)


def _run_groups():
    global _OK
    _OK = 0
    _BAD.clear()
    for idx, g in enumerate(_GROUPS, 1):
        try:
            g()
        except Exception as exc:                    # noqa: BLE001
            # 组异常也按 **S<序号>** 命名：定点变异常把实现改成自相矛盾，
            # 此时判据不是「断言不成立」而是「调用直接抛」——两者都是该组转红。
            _check("S%d 组异常（%s）：%s" % (idx, g.__name__, exc), False)
            import traceback
            print(traceback.format_exc()[-600:])
    return len(_BAD)


def main():
    n = _run_groups()
    print()
    print("兄弟写入口密级继承守卫：%d 通过，%d 失败" % (_OK, n))
    return 1 if n else 0


#: (文件, 名称, 锚, 替换, 期望红组)——锚含前导行，确保替换命中唯一方法。
_MUTATIONS = (
    (_MDCOS, "V1 add_goal 回到 sensitivity or DEFAULT_SENSITIVITY（本件病象）",
     "        sens = self._write_sensitivity(gid, sensitivity)\n",
     "        sens = sensitivity or DEFAULT_SENSITIVITY\n", "S2"),
    (_MDCOS, "V2 add_rejected 回到 sensitivity or DEFAULT_SENSITIVITY",
     "        nid = self._rejected_nid(hypothesis)\n"
     "        sens = self._write_sensitivity(nid, sensitivity)\n",
     "        nid = self._rejected_nid(hypothesis)\n"
     "        sens = sensitivity or DEFAULT_SENSITIVITY\n", "S3"),
    (_MDCOS, "V3 add_unresolved 回到 sensitivity or DEFAULT_SENSITIVITY",
     '        nid = self._unresolved_nid(question, kw.get("topic"))\n'
     "        sens = self._write_sensitivity(nid, sensitivity)\n",
     '        nid = self._unresolved_nid(question, kw.get("topic"))\n'
     "        sens = sensitivity or DEFAULT_SENSITIVITY\n", "S4"),
    (_MDCG, "V4 _goal_nid 去掉 strip（基类/安全层幂等键漂移）",
     "        return f\"goal_{hashlib.sha1((goal or '').strip()"
     ".encode('utf-8')).hexdigest()[:10]}\"\n",
     "        return f\"goal_{hashlib.sha1((goal or '')"
     ".encode('utf-8')).hexdigest()[:10]}\"\n", "S12"),
)


def _reload():
    import importlib
    from md_cg import mdcg as _m
    importlib.reload(_m)
    globals()["_mdcg"] = _m
    from md_cg import mdcos as _o
    importlib.reload(_o)          # mdcos 必须后重载：其类基指向新 MdCG
    globals()["MdCGSecure"] = _o.MdCGSecure


def _mutate():
    bad = []
    pristine = {}
    for rel, _n, _a, _r, _w in _MUTATIONS:
        p = os.path.join(_REPO, rel)
        with io.open(p, encoding="utf-8", newline="") as f:
            pristine[rel] = f.read()
    if "_rejected_nid(hypothesis)" not in pristine[_MDCOS]:
        print("  SOURCE-ALREADY-MUTATED：mdcos.py 缺 _rejected_nid 接线")
        return 1
    try:
        for rel, name, anchor, repl, want in _MUTATIONS:
            p = os.path.join(_REPO, rel)
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
                print("  %-4s %-56s 红项=%-3d 命中%s=%s"
                      % ("OK" if hit else "BAD", name, len(reds), want,
                         "是" if hit else "否"))
                if not hit:
                    bad.append(name)
            finally:
                for rel2, txt in pristine.items():
                    p2 = os.path.join(_REPO, rel2)
                    with io.open(p2, "w", encoding="utf-8", newline="") as f:
                        f.write(txt)
                for rel2 in pristine:
                    p2 = os.path.join(_REPO, rel2)
                    with io.open(p2, encoding="utf-8", newline="") as f:
                        if f.read() != pristine[rel2]:
                            print("  RESTORE-FAILED %s" % name)
                            bad.append(name + "(恢复失败)")
                _reload()
    finally:
        for rel2, txt in pristine.items():
            p2 = os.path.join(_REPO, rel2)
            with io.open(p2, "w", encoding="utf-8", newline="") as f:
                f.write(txt)
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
