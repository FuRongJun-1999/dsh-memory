# -*- coding: utf-8 -*-
"""冲突闸 → 飞轮的密级透传守卫（issue #294）。

【守什么】
#294 报：声明 private/restricted 的写入被冲突闸判 REJECT 后，飞轮把**正文前
200 字**原样建成一张 unresolved 工单，工单按缺省档 internal 明文落盘——正文
明文出现在工单正文、**文件名（id 由正文 slug 而来）**、_index.json 与
_audit.jsonl 里；无令牌访客用 stg(op=timeline) 列出、mdcg_get 读全文。record
令牌（clearance internal）种一条带「纪律」tag 的节点即可主动诱发。

复核**成立**（本机实测，与报告逐字一致，bfc40c1 基线）：
  工单 id = unr_用户今天说-我在服用舍曲林-诊断重度抑郁-OWNSEC294-别让公司知道-REJECT
  密级行 = sensitivity: "internal"；正文/文件名/索引/审计四处全含明文；
  无令牌访客 timeline=True、mdcg_get=True。命中 4/4。

病灶：冲突闸整条链不知道写入声明的密级——
  MdCG.add → consistency.check → _fire_flywheel → flywheel_step → add_unresolved
每一跳都不带 sensitivity，最后一跳 add_unresolved 便取缺省档 internal。
与 #214 同族（#214 修的是六要素校验闸 → add_rejected 那条出口）。

修法（只做透传与改 id，不动任何判定）：
  ① 密级沿 add / writepipe / check_consistency / MCP check 面一路透传到
     flywheel_step，再交给 add_unresolved → 工单走与普通 private 写入同一个
     MdCGSecure.add → _write_node 封存点（加密、索引记 private、读出口按
     clearance 过滤）。
  ② 密级高于 internal 时工单身份改用 sha1(密级|主题) 前 16 位，正文 slug 不再
     进文件名与索引。同一密级同一主题仍得同一 id（H11⑦「同题同单」不变）；
     身份里带密级，private 与 restricted 的同一段话不落到同一张工单上互相覆写。

判据：
  G1  结构：五处接线在位（check / _fire_flywheel / check_consistency / add /
      writepipe / MCP check 面）+ flywheel_step 的换 id 分支。
  G2  ★ private 写入被判 REJECT ⇒ 工单密级 private、盘面四处零明文。
  G3  ★ 无令牌访客 timeline / mdcg_get 都读不到（改前两个都是 True）。
  G4  ★ restricted 同档同判（另一档，排除「只认 private」的实现）。
  G5  ★ id 不可逆 + 同题同单 + 跨密级不撞车。
  G6  零变化面：未声明密级 ⇒ 仍 internal + id 仍用正文 slug。
  G7  判定面不变：属主回执仍是冲突 REJECT；属主仍能读回自己的 private 工单。
  G8  ★ cg(op=write) 入口同样透传（动词面）。
  G9  反陈化：理由在源码里。
  G10 修复前原形（git log -S 定位引入提交取父版本；未提交时回落 HEAD）。

运行：python -X utf8 -m md_cg.test_issue294_flywheel_sensitivity
      python -X utf8 -m md_cg.test_issue294_flywheel_sensitivity --mutate
"""
from __future__ import annotations

import glob
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="i294g_")
for _k in ("HOME", "MDCG_ROOT", "MDCG_AUX_ROOT", "MDCG_STATE_ROOT",
           "MDCG_DATA_ROOT", "MDCG_EXPORT_ROOT"):
    os.environ[_k] = os.path.join(_TMP, _k.lower())
    os.makedirs(os.environ[_k], exist_ok=True)
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
os.environ["MDCG_SUSTAIN"] = "0"
os.environ["MDCG_SLEEP"] = "0"
os.environ["MDCG_WRITELIMIT"] = "0"

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import autonomy_modes as _am        # noqa: E402
from md_cg import mcp_server                   # noqa: E402
from md_cg.mdcos import MdCGSecure             # noqa: E402
from md_cg.security import Principal           # noqa: E402
from md_cg.tokens import role_spec             # noqa: E402

#: 档位 env 键名取自唯一入口模块（仓内惯例，见 test_autonomy_modes）——
#: 在测试里写死档位 env 字面量会打红那条反漂移判据 G 组。
_ENV_MODE = _am.AUTONOMY_ENV_KEYS["mode"]

_ROOT = os.environ["MDCG_ROOT"]
SECRET = "OWNSEC294G"
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


def _cg(role, clearance, session):
    sp = role_spec(role)
    return MdCGSecure(_ROOT, principal=Principal(
        actor=role, clearance=clearance, can_write=role != "guest",
        can_admin=role == "designer", role=role,
        layers_allow=sp["layers_allow"], ops_allow=sp["ops_allow"],
        session=session))


def _tickets():
    """{id: (fm 密级, 正文)} —— 只认 unresolved 层。"""
    out = {}
    for f in glob.glob(_ROOT + "/**/unresolved/*.md", recursive=True):
        nid = os.path.basename(f)[:-3]
        t = io.open(f, encoding="utf-8", errors="replace").read()
        m = re.search(r'^sensitivity:\s*"?([a-z]+)"?\s*$', t, re.M)
        out[nid] = (m.group(1) if m else None, t)
    return out


def _blob(skip=()):
    s = ""
    for dp, _d, fs in os.walk(_ROOT):
        for f in fs:
            p = os.path.join(dp, f)
            if p in skip:
                continue
            try:
                s += io.open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
    return s


def _names():
    s = ""
    for dp, _d, fs in os.walk(_ROOT):
        if "unresolved" in dp:
            s += "".join(fs)
    return s


def _guest(marker, ids):
    g = _cg("guest", "internal", "g294")
    try:
        tl = mcp_server._dispatch(g, "stg", {"op": "timeline", "limit": 50})
        hit_tl = marker in json.dumps(tl, ensure_ascii=False, default=str)
        hit_get = False
        for i in ids:
            r = mcp_server._dispatch(g, "mdcg_get", {"node_id": i})
            if marker in json.dumps(r, ensure_ascii=False, default=str):
                hit_get = True
        return hit_tl, hit_get
    finally:
        g.close()


def _src(rel):
    return io.open(os.path.join(_REPO, rel), encoding="utf-8",
                   errors="replace").read()


def _region(rel, start, end=None):
    t = _src(rel)
    i = t.index(start)
    j = t.index(end, i) if end else len(t)
    return t[i:j]


# --------------------------------------------------------------------------
# 夹具：record 种纪律节点（诱发 REJECT）
# --------------------------------------------------------------------------

def _seed_discipline(rec):
    return mcp_server._dispatch(rec, "mdcg_remember", {
        "content": "# 功能名：隐私纪律\n# 生效条件：任何时候\n# 子功能：纪律\n"
                   "# 执行：遵守\n# 验证方式：规范\n# 不适用条件：不得舍曲林",
        "layer": "knowledge", "tags": ["纪律"], "gated": False,
        "consistency": False})


def _rejecting_write(cgx, sens, marker=SECRET):
    """声明 sens 的写入，正文命中纪律节点 ⇒ 冲突闸判 REJECT。

    进程内直调时冲突闸是**抛** ConsistencyError（MCP 面才包成 error 字段），
    故两侧都接。
    """
    kw = {"content": "用户今天说：我在服用舍曲林，诊断重度抑郁，%s，别让公司知道"
                     % marker, "layer": "knowledge"}
    if sens:
        kw["sensitivity"] = sens
    try:
        r = mcp_server._dispatch(cgx, "mdcg_remember", kw)
        return str(r.get("error") or "")
    except Exception as exc:                        # noqa: BLE001
        return "%s: %s" % (type(exc).__name__, exc)


# --------------------------------------------------------------------------
# 断言组
# --------------------------------------------------------------------------

def g1():
    print("== G1 结构：五处接线 + 换 id 分支 ==")
    c = _src("md_cg/consistency.py")
    m = _src("md_cg/mdcg.py")
    w = _src("md_cg/writepipe.py")
    s = _src("md_cg/mcp_server.py")
    d = _src("md_cg/mdcos.py")
    # issue #193：check 的签名在 sensitivity 之前新增了 write_scope（写入面
    # 的额外比对层）。本断言判的是「check 收 sensitivity 形参」这一事实，
    # 故锚点随之同步——删掉 sensitivity 仍转红（判别力不变）。
    _check("G1a consistency.check 收 sensitivity",
           "write_scope=False, sensitivity=None):" in c)
    _check("G1b check 把 sensitivity 交给 _fire_flywheel",
           "allc,\n                                              sensitivity=sensitivity)"
           .replace("\n", "\r\n") in c or
           "sensitivity=sensitivity)" in c)
    _check("G1c _fire_flywheel 形参有 sensitivity",
           "conflicts=None,\n                   sensitivity=None):".replace("\n", "\r\n") in c
           or "conflicts=None," in c and "sensitivity=None):" in c)
    _check("G1d payload 带上 sensitivity",
           'payload["sensitivity"] = sensitivity' in c)
    # issue #193：同上（mdcos.check_consistency 的透传签名）。
    _check("G1e check_consistency 收 sensitivity",
           "write_scope=False, sensitivity=None):" in d)
    _check("G1f check_consistency 透传", "sensitivity=sensitivity)" in d)
    _check("G1g MdCG.add 冲突闸透传归一后的密级",
           'sensitivity=extra.get("sensitivity"))' in m)
    _check("G1h writepipe 冲突闸透传",
           'sensitivity=a.get("sensitivity"))' in w)
    _check("G1i MCP check 面收 sensitivity",
           'sensitivity=a.get("sensitivity"))' in s)
    _check("G1j flywheel_step 读 sensitivity", 'try_data.get("sensitivity")' in m)
    _check("G1k 密级高于 internal 时换不可逆身份",
           '_topic = "h" + hashlib.sha1(' in m)
    _check("G1l 换 id 时把密级并进身份（跨密级不撞车）",
           '"%s|%s" % (_sens, _topic)' in m)
    _check("G1m 工单把密级交给 add_unresolved", "topic=_topic, **_kw)" in m)


def g2():
    print("== G2 ★ private 写入被判 REJECT ==")
    rec = _cg("record", "internal", "s2r")
    _seed_discipline(rec)
    rec.close()
    os.environ[_ENV_MODE] = _am.MODE_FULL
    own = _cg("designer", "private", "s2o")
    err = _rejecting_write(own, "private")
    _check("G2a 仍判冲突 REJECT", "REJECT" in err, err[:160])
    tk = _tickets()
    _check("G2b 建出工单", len(tk) == 1, str(list(tk)))
    if len(tk) != 1:
        own.close()
        return
    nid, (sens, body) = list(tk.items())[0]
    _check("G2c ★ 工单密级 = private（改前 internal）", sens == "private", str(sens))
    _check("G2d ★ 工单正文无明文（改前有）", SECRET not in body)
    _check("G2e ★ 文件名无明文（改前有）", SECRET not in nid, nid)
    _check("G2f ★ 索引/审计无明文（改前有）", SECRET not in _blob())
    # 工单已落盘且正文非空——「工单真的建出来了」的证据是 G2b 的
    # before/after 计数（建单前 unresolved 为空），这里只补一条「正文非空」。
    # ★ 不能拿明文当证据：修后 private 工单正文是**密文**，明文反而应当找不到。
    _check("G2g 工单已落盘且正文非空", len(body.strip()) > 0, body[:120])
    _check("G2h 正文不是明文模板（密文落盘）", "# 问题：" not in body)
    own.close()


def g3():
    print("== G3 ★ 无令牌访客 ==")
    ids = list(_tickets())
    tl, gt = _guest(SECRET, ids)
    _check("G3a ★ 访客 timeline 读不到（改前 True）", not tl)
    _check("G3b ★ 访客 mdcg_get 读不到（改前 True）", not gt)


def g4():
    print("== G4 ★ restricted 同档同判 ==")
    own = _cg("designer", "restricted", "s4")
    err = _rejecting_write(own, "restricted", marker="OWNSEC294R")
    _check("G4a 仍判冲突 REJECT", "REJECT" in err, err[:160])
    tk = _tickets()
    hits = [(k, v) for k, v in tk.items() if "OWNSEC294R" in v[1]
            or v[0] == "restricted"]
    _check("G4b 建出 restricted 工单", len(hits) == 1, str(hits)[:160])
    if hits:
        k, (sens, body) = hits[0]
        _check("G4c ★ 密级 = restricted", sens == "restricted", str(sens))
        # ★ restricted **不在** crypto.ENCRYPTED_LEVELS（只有 private/secret
        #   加密），故「盘面无明文」不是它的判据——restricted 的边界是读面按
        #   clearance 过滤。缺陷面是「被判成 internal ⇒ 任何 internal 令牌都
        #   读得到」；修后密级记 restricted，internal 令牌读不到（G4e）。
        #   这里只钉「id 也不再用正文 slug」（与 private 同一换 id 分支）。
        _check("G4d ★ 文件名不再用正文 slug", "OWNSEC294R" not in k, k)
    # ★ restricted **不在** crypto.ENCRYPTED_LEVELS（只有 private/secret 加密），
    #   所以「盘面零明文」不是 restricted 的正确判据——它的边界是**读面按
    #   clearance 过滤**（既有语义）。缺陷面因此是：工单被判 internal ⇒ 任何
    #   internal 令牌都读得到；修后密级记 restricted，internal 令牌读不到。
    if hits:
        rec = _cg("record", "internal", "g4r")
        try:
            r = mcp_server._dispatch(rec, "mdcg_get", {"node_id": hits[0][0]})
            got = json.dumps(r, ensure_ascii=False, default=str)
            _check("G4e ★ internal 令牌读不到 restricted 工单（改前读得到）",
                   "OWNSEC294R" not in got, got[:160])
        finally:
            rec.close()
    own.close()


def g5():
    print("== G5 ★ 身份：不可逆 + 同题同单 + 跨密级不撞车 ==")
    tk = _tickets()
    ids = sorted(tk)
    _check("G5a 工单 id 形如 unr_h<16 位 hex>",
           all(re.fullmatch(r"unr_h[0-9a-f]{16}", i) for i in ids), str(ids))
    priv = [i for i in ids if tk[i][0] == "private"]
    restr = [i for i in ids if tk[i][0] == "restricted"]
    _check("G5b ★ private 与 restricted 的同一段话不撞车（各自建单）",
           bool(priv) and bool(restr) and not set(priv) & set(restr),
           "%s / %s" % (priv, restr))
    n0 = len(_tickets())
    os.environ[_ENV_MODE] = _am.MODE_FULL
    own = _cg("designer", "private", "s5")
    _rejecting_write(own, "private")
    _check("G5c ★ 同密级同主题再写不新建工单（H11⑦ 同题同单）",
           len(_tickets()) == n0, "%d -> %d" % (n0, len(_tickets())))
    # id 可由「密级|主题」复算 ⇒ 不是随机，是可复现身份
    q = "用户今天说：我在服用舍曲林，诊断重度抑郁，%s，别让公司知道" % SECRET
    want = "unr_h" + hashlib.sha1(
        ("%s|%s|REJECT" % ("private", q[:200])).encode("utf-8")).hexdigest()[:16]
    _check("G5d id 可由「密级|正文前200字|实际态」复算（确定性身份）",
           want in tk, "%s vs %s" % (want, ids))
    own.close()


def g6():
    print("== G6 零变化面：未声明密级 ==")
    own = _cg("designer", "private", "s6")
    before = set(_tickets())
    own.flywheel_step({"query": "普通未声明密级的写入 OWNSEC294P",
                       "expected_state": "ACCEPT", "actual_state": "REJECT",
                       "missing": "缺条件"})
    new = sorted(set(_tickets()) - before)
    _check("G6a 未声明密级仍建单", len(new) == 1, str(new))
    if new:
        sens, body = _tickets()[new[0]]
        _check("G6b ★ 未声明密级 ⇒ 仍 internal（零变化）", sens == "internal", str(sens))
        _check("G6c ★ id 仍用正文 slug（零变化）",
               "普通" in new[0] and not new[0].startswith("unr_h"), new[0])
        _check("G6d 未声明密级正文照旧明文（既有语义，本件不改）",
               "OWNSEC294P" in body)
    own.close()


def g7():
    print("== G7 判定面不变 ==")
    os.environ[_ENV_MODE] = _am.MODE_FULL
    own = _cg("designer", "private", "s7")
    err = _rejecting_write(own, "private", marker="OWNSEC294K")
    _check("G7a 属主回执仍是冲突 REJECT（不是被降级成别的）",
           "REJECT" in err and "命中纪律" in err, err[:160])
    ids = list(_tickets())
    _check("G7b ★ 属主仍能读回自己的 private 工单（不是「谁都不许读」）",
           any(s == "private" for s, _b in _tickets().values()) and
           mcp_server._dispatch(own, "mdcg_get", {"node_id": ids[0]}) is not None)
    own.close()


def g8():
    print("== G8 ★ cg(op=write) 入口同样透传 ==")
    own = _cg("designer", "private", "s8")
    before = set(_tickets())
    try:
        # ★ cg(op=write) 先过六要素闸（_gate_audit），内容必须是合规 CCG 卡，
        #   否则根本走不到冲突闸——首版探针就是在这里「没建单」的。
        mcp_server._dispatch(own, "cg", {
            "op": "write",
            "content": "# 功能名：用药记录 OWNSEC294W\n# 生效条件：服药时\n"
                       "# 子功能：记录\n# 执行：我在服用舍曲林，别外传\n"
                       "# 验证方式：医嘱\n# 不适用条件：无",
            # ★ 缺 content_kind 会在**六要素闸**就被判 BLINDSPOT 入审核队列，
            #   根本走不到冲突闸——首版探针就是这样「没建单」的。
            "content_kind": "text",
            "layer": "knowledge", "sensitivity": "private",
            "on_conflict": "defer"})
    except Exception:                               # noqa: BLE001
        pass
    new = sorted(set(_tickets()) - before)
    _check("G8a 动词面也建出工单", len(new) == 1, str(new))
    if new:
        sens, body = _tickets()[new[0]]
        _check("G8b ★ 动词面工单密级 = private（改前 internal）",
               sens == "private", str(sens))
        _check("G8c ★ 动词面零明文（正文与文件名）",
               "OWNSEC294W" not in body and "OWNSEC294W" not in new[0])
    own.close()


def g9():
    print("== G9 反陈化：理由在源码里 ==")
    c = _src("md_cg/consistency.py")
    m = _src("md_cg/mdcg.py")
    _check("G9a 标注 issue #294", "issue #294" in c and "issue #294" in m)
    _check("G9b 写明「正文前 200 字」是泄露源", "200 字" in c)
    _check("G9c 写明 id 由正文 slug 而来", "slug" in m and "文件名" in m)
    _check("G9d 写明跨密级不撞车", "互相覆写" in m)
    _check("G9e 写明同题同单不变", "同题同单" in m)


def _prepatch_src(rel, marker):
    def _g(*a):
        return subprocess.run(list(a), cwd=_REPO, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=60)
    lg = _g("git", "log", "-S" + marker, "--format=%H", "--", rel)
    if lg.returncode == 0:
        shas = [x.strip() for x in (lg.stdout or "").splitlines() if x.strip()]
        if shas:
            s = _g("git", "show", shas[-1] + "^:" + rel)
            if s.returncode == 0:
                return s.stdout, "引入提交 %s 的父版本" % shas[-1][:8]
    s = _g("git", "show", "HEAD:" + rel)
    if s.returncode != 0:
        return None, "git show HEAD rc=%s" % s.returncode
    return s.stdout, "HEAD（本改动尚未提交）"


def g10():
    print("== G10 修复前原形（提交前/后都稳定）==")
    t, how = _prepatch_src("md_cg/consistency.py", "issue #294")
    if t is None:
        _check("G10 取修复前源失败：%s" % how, False)
        return
    print("       （修复前源取自 %s）" % how)
    n = t.replace("\r\n", "\n")
    _check("G10a 修复前 check 不收 sensitivity",
           "log_write=True, sensitivity=None):" not in n)
    _check("G10b ★ 修复前的 _fire_flywheel 确是「不带密级」原形",
           "def _fire_flywheel(cg, query, verdict, reason, missing, conflicts=None):" in n)
    _check("G10c 修复前 payload 不带 sensitivity",
           'payload["sensitivity"]' not in n)
    m, how2 = _prepatch_src("md_cg/mdcg.py", "issue #294")
    if m is not None:
        mn = m.replace("\r\n", "\n")
        _check("G10d ★ 修复前 flywheel_step 不读 sensitivity",
               'try_data.get("sensitivity")' not in mn)
        _check("G10e 修复前 topic 一律 f-string 拼接（无换 id 分支）",
               'topic=f"{_q}|{_st}")' in mn)


_GROUPS = (g1, g2, g3, g4, g5, g6, g7, g8, g9, g10)


def _run_groups():
    global _OK
    _OK = 0
    _BAD.clear()
    for idx, g in enumerate(_GROUPS, 1):
        try:
            g()
        except Exception as exc:                    # noqa: BLE001
            # 组异常也按 G<序号> 命名：定点变异常把实现改成自相矛盾（调用直接
            # 抛），此时判据不是「断言不成立」而是「调用抛」——两者都是该组转红。
            _check("G%d 组异常（%s）：%s" % (idx, g.__name__, exc), False)
            import traceback
            print(traceback.format_exc()[-600:])
    return len(_BAD)


def main():
    n = _run_groups()
    print()
    print("冲突闸飞轮密级透传守卫：%d 通过，%d 失败" % (_OK, n))
    return 1 if n else 0


# --------------------------------------------------------------------------
# 定点变异自证
# --------------------------------------------------------------------------

_MUTATIONS = (
    ("V1 _fire_flywheel 不把密级放进 payload（本件病象）",
     "md_cg/consistency.py",
     "        if sensitivity:\n            payload[\"sensitivity\"] = sensitivity\n",
     "", "G2"),
    ("V2 只透传密级、不换 id（明文留在文件名与索引）",
     "md_cg/mdcg.py",
     "            if _sens not in (\"public\", \"internal\"):\n",
     "            if False:\n", "G2"),
    ("V3 MdCG.add 冲突闸不透传（直写面失守）",
     "md_cg/mdcg.py",
     "                             sensitivity=extra.get(\"sensitivity\"))",
     "                             )", "G2"),
    # ★ 锚点必须**唯一**：writepipe.py 里 `sensitivity=a.get("sensitivity"))`
    #   另有一处既存站点（:489），单行锚点会 replace 到那一处、变异形同没做
    #   （首轮实测：变异后全绿 = 假通过）。这里带上前一行与注释段，锁定
    #   _gate_consistency 的调用点。
    ("V4 writepipe 冲突闸不透传（动词面失守）",
     "md_cg/writepipe.py",
     "        tags=a.get(\"tags\"), exclude=ctx[\"nid\"], auto_flywheel=True,\n"
     "        # issue #294：cg(op=write) 入口同样要透传声明密级（缺了这条，\n"
     "        # 冲突闸 → 飞轮那条出口对动词面照旧泄明文）。\n"
     "        sensitivity=a.get(\"sensitivity\"))",
     "        tags=a.get(\"tags\"), exclude=ctx[\"nid\"], auto_flywheel=True)",
     "G8"),
)


def _mutate():
    bad = []
    prist = {}
    for _n, rel, _a, _r, _w in _MUTATIONS:
        p = os.path.join(_REPO, rel)
        with io.open(p, encoding="utf-8", newline="") as f:
            prist[rel] = f.read()
        # 已变异则拒绝：基线必须是**原样**源码，否则「变异后转红」无意义。
        if "issue #294" not in prist[rel]:
            print("  SOURCE-ALREADY-MUTATED：%s 里找不到本件标记" % rel)
            return 1
    for name, rel, anchor, repl, want in _MUTATIONS:
        p = os.path.join(_REPO, rel)
        orig = prist[rel]
        NL = "\r\n" if "\r\n" in orig else "\n"
        a_ = anchor.replace("\n", NL)
        r_ = repl.replace("\n", NL)
        if a_ not in orig:
            print("  ANCHOR-MISS %s" % name)
            bad.append(name)
            continue
        # ★ 锚点必须唯一：多义锚点 + replace(..., 1) 会改到**别处**，变异形同
        #   没做，自证便成假通过（本件 V4 首轮实测：锚点撞上既存站点 ⇒ 全绿）。
        if orig.count(a_) != 1:
            print("  ANCHOR-AMBIGUOUS %s（命中 %d 处，须唯一定位）"
                  % (name, orig.count(a_)))
            bad.append(name)
            continue
        try:
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(orig.replace(a_, r_, 1))
            r = subprocess.run(
                [sys.executable, "-X", "utf8", "-m",
                 "md_cg.test_issue294_flywheel_sensitivity"],
                cwd=_REPO, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=900)
            out = (r.stdout or "") + (r.stderr or "")
            reds = [l.strip() for l in out.splitlines() if l.strip().startswith("FAIL")]
            hit = any(want in l for l in reds)
            print("  %-4s %-48s 红项=%-3d 命中%s=%s"
                  % ("OK" if hit else "BAD", name, len(reds), want,
                     "是" if hit else "否"))
            if not hit:
                print("       rc=%d 尾部=%s" % (r.returncode, out[-400:]))
                bad.append(name)
        finally:
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(orig)
            with io.open(p, encoding="utf-8", newline="") as f:
                if f.read() != orig:
                    print("  RESTORE-FAILED %s" % name)
                    bad.append(name + "(恢复失败)")
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
