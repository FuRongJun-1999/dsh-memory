# -*- coding: utf-8 -*-
# 功能名：identity 写侧 sensitivity 透传（issue #467）——anchor/trait 两入口不再静默降 internal
# 生效条件：python -X utf8 -m md_cg.test_issue467_identity_sensitivity [--mutate]；
#           被测面＝md_cg/identity.py::set_anchor/add_trait、md_cg/mcp_server.py::_identity_call、
#           mdcg_identity 工具 schema、md_cg/op_table.py identity params
# 子功能：A 组＝库层与工具面声明 private 落盘且 guest 读不到；K 组＝非恒真对照（缺省零变更、
#         既有直写/observe 通路、override 语义）；E 组＝AST/源码钉子
# 执行：--mutate 时就地短路一条判据（撤两个库入口透传 / 撤工具面透传 / 缺省强推 private），
#       指定断言须**恰好**转红
# 不适用条件：不判 identity_contract 面（走另一条 admin 闸）；不判 secret 档（designer 能力上限内同构）；
#       不判多租户/多进程
"""issue #467 守卫：identity 两入口实参表漏传 sensitivity。

病象（修前）：designer（clearance_cap=secret，唯一能写 private 的入口）经
identity_anchor / identity_add_trait 写含私钥口令的身份锚点/特征时，两入口没有
sensitivity 形参，字段无从透传 ⇒ 库层按缺省落 internal 明文，无令牌 guest 可读。
同模块 observe 有该形参（#258 所修），属同族不对称。

修复语义：set_anchor / add_trait 增 sensitivity=None 形参，非 None 时随 extra 透传
cg.add；工具面 mdcg_identity 的 anchor/trait 分支透传 a.get('sensitivity')；
schema 与 op_table 同步登记。缺省 None 行为逐位不变（与 #258 同口径）。
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

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SELF = os.path.abspath(__file__)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

SECRET = "sk-SECRET-ANCHOR-467"
SECRET2 = "sk-SECRET-TRAIT-467"
_CHECKS = []
FAILS = []


def _check(name, cond, detail=""):
    if name not in _CHECKS:
        _CHECKS.append(name)
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


def _try(fn):
    try:
        return fn(), None
    except Exception as exc:                            # noqa: BLE001
        return None, exc


class _Env:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="iss467_")
        self.saved = {}

    def __enter__(self):
        from md_cg import crypto
        env = {"MDCG_ROOT": self.dir + "/brain",
               "MDCG_STATE_ROOT": self.dir + "/state",
               "MDCG_AUX_ROOT": self.dir + "/auxstore",
               "MDCG_DATA_ROOT": self.dir + "/data",
               "MDCG_EXPORT_ROOT": self.dir,
               "MDCG_TOKEN_FILE": self.dir + "/auxstore/tokens.json",
               "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
               crypto.MASTER_ENV: "ab" * 32}
        for k, v in env.items():
            self.saved[k] = os.environ.get(k)
            os.environ[k] = v
        from md_cg.mdcos import MdCGSecure
        from md_cg.security import Principal
        self.cg = MdCGSecure(os.environ["MDCG_ROOT"],
                             principal=Principal(clearance="secret",
                                                 can_admin=True), autoflush=1)
        return self

    def __exit__(self, *exc):
        try:
            self.cg.close()
        except Exception:                               # noqa: BLE001
            pass
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.dir, ignore_errors=True)
        return False

    def fm(self, nid):
        return ((self.cg.get(nid) or {}).get("frontmatter") or {})

    def guest_text(self, nid):
        from md_cg.mdcos import MdCGSecure
        from md_cg.security import Principal
        cg2 = MdCGSecure(os.environ["MDCG_ROOT"],
                         principal=Principal(clearance="internal"), autoflush=0)
        try:
            return ((cg2.get(nid) or {}).get("content")) or ""
        finally:
            cg2.close()


def _dispatch(cg, name, args):
    from md_cg import mcp_server
    return mcp_server._dispatch(cg, name, args)


def _assertions():
    from md_cg import identity
    print("== A 组：声明 private 落盘 + guest 读不到（库层与工具面） ==")
    with _Env() as e:
        _check("A01 前提：缺省 anchor 落 internal（零变更基线）",
               (e.cg.identity_anchor("role:base467", "基线锚点") or {}).get("ok") is True
               and e.fm(identity.subject_node_id("role:base467")).get("sensitivity") == "internal")
        r_a, exc_a = _try(lambda: e.cg.identity_anchor(
            "role:anchor467", "锚点：" + SECRET, sensitivity="private"))
        nid_a = identity.subject_node_id("role:anchor467")
        _check("A02 ★行：identity_anchor(sensitivity=private) 保持 private",
               exc_a is None and isinstance(r_a, dict) and r_a.get("ok") is True
               and e.fm(nid_a).get("sensitivity") == "private",
               exc_a or e.fm(nid_a).get("sensitivity"))
        _check("A03 ★行：该锚点 internal 档 guest 读不到正文",
               SECRET not in e.guest_text(nid_a), e.guest_text(nid_a)[:60])
        r_t, exc_t = _try(lambda: e.cg.identity_trait(
            "role:trait467", "特征：" + SECRET2, sensitivity="private"))
        _check("A04 ★行：identity_trait(sensitivity=private) 保持 private",
               exc_t is None and isinstance(r_t, dict) and r_t.get("ok") is True
               and e.fm(r_t.get("node_id") or "").get("sensitivity") == "private",
               exc_t or e.fm((r_t or {}).get("node_id") or "").get("sensitivity"))
        _check("A05 ★行：该特征节点 internal 档 guest 读不到正文",
               SECRET2 not in e.guest_text((r_t or {}).get("node_id") or ""),
               e.guest_text((r_t or {}).get("node_id") or "")[:60])
        r_ta, exc_ta = _try(lambda: _dispatch(e.cg, "mdcg_identity", {
            "action": "anchor", "subject_id": "role:tool467",
            "content": "工具面锚点：" + SECRET, "sensitivity": "private"}))
        nid_ta = identity.subject_node_id("role:tool467")
        _check("A06 ★行：工具面 action=anchor 透传 sensitivity=private",
               exc_ta is None and e.fm(nid_ta).get("sensitivity") == "private",
               exc_ta or e.fm(nid_ta).get("sensitivity"))
        r_tt, exc_tt = _try(lambda: _dispatch(e.cg, "mdcg_identity", {
            "action": "trait", "subject_id": "role:toolt467",
            "trait": "工具面特征：" + SECRET2, "sensitivity": "private"}))
        nid_tt = (r_tt or {}).get("node_id") or ""
        _check("A07 ★行：工具面 action=trait 透传 sensitivity=private",
               exc_tt is None and e.fm(nid_tt).get("sensitivity") == "private",
               exc_tt or e.fm(nid_tt).get("sensitivity"))

    print("== K 组：非恒真对照 ==")
    with _Env() as e:
        r1, ex1 = _try(lambda: e.cg.identity_trait("role:k1", "缺省特征"))
        _check("K01 缺省不声明 trait ⇒ internal（行为逐位不变）",
               ex1 is None and e.fm((r1 or {}).get("node_id") or "").get("sensitivity") == "internal",
               ex1 or e.fm((r1 or {}).get("node_id") or "").get("sensitivity"))
        r2, ex2 = _try(lambda: e.cg.add("direct467", "直写：" + SECRET,
                                        layer="knowledge", sensitivity="private"))
        _check("K02 既有直写通路：cg.add(sensitivity=private) 保持 private 且 guest 读不到",
               ex2 is None and e.fm("direct467").get("sensitivity") == "private"
               and SECRET not in e.guest_text("direct467"),
               ex2 or e.fm("direct467").get("sensitivity"))
        r3, ex3 = _try(lambda: e.cg.identity_observe("role:k3", "观察：" + SECRET2,
                                                     sensitivity="private"))
        _check("K03 observe 通路（#258）显式 private 保持 private",
               ex3 is None and e.fm((r3 or {}).get("node_id") or "").get("sensitivity") == "private",
               ex3 or e.fm((r3 or {}).get("node_id") or "").get("sensitivity"))

    print("== E 组：AST / 源码钉子 ==")

    def _fn(path, name):
        with io.open(os.path.join(_REPO, path), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for n in ast.walk(tree):
            if isinstance(n, ast.FunctionDef) and n.name == name:
                return n
        return None

    sa = _fn("md_cg/identity.py", "set_anchor")
    ad = _fn("md_cg/identity.py", "add_trait")
    _check("E01 ★钉子：set_anchor/add_trait 签名均含 sensitivity",
           bool(sa) and "sensitivity" in [a.arg for a in sa.args.kwonlyargs]
           and bool(ad) and "sensitivity" in [a.arg for a in ad.args.kwonlyargs],
           [a.arg for a in sa.args.kwonlyargs] if sa else None)
    _sa_src = ast.unparse(sa).replace('"', "'") if sa else ""
    _ad_src = ast.unparse(ad).replace('"', "'") if ad else ""
    _check("E02 ★钉子：两函数体均为「非 None 才透传 extra.sensitivity」",
           "extra['sensitivity'] = sensitivity" in _sa_src
           and "extra['sensitivity'] = sensitivity" in _ad_src,
           (_sa_src[-160:], _ad_src[-160:]))
    ic = _fn("md_cg/mcp_server.py", "_identity_call")
    ic_src = (ast.unparse(ic).replace('"', "'")) if ic else ""
    _check("E03 ★钉子：工具面 trait/anchor 两分支均透传 a.get(sensitivity)",
           ic_src.count("sensitivity=a.get('sensitivity')") >= 2,
           ic_src.count("sensitivity=a.get('sensitivity')"))
    with io.open(os.path.join(_REPO, "md_cg/mcp_server.py"), encoding="utf-8") as fh:
        srv_src = fh.read()
    _check("E04 ★钉子：mdcg_identity schema 登记 sensitivity 字段",
           'sensitivity=_p("string", "写面密级' in srv_src)
    with io.open(os.path.join(_REPO, "md_cg/op_table.py"), encoding="utf-8") as fh:
        opt_src = fh.read()
    _m5 = re.search(r'"identity":\s*\{(.*?)\n    \},', opt_src, re.S)
    _id_seg = _m5.group(1) if _m5 else ""
    _check("E05 ★钉子：op_table identity 段 params 含 sensitivity",
           '"sensitivity",' in _id_seg, _id_seg[:120])


def _run_assertions():
    global FAILS
    FAILS = []
    del _CHECKS[:]
    _assertions()
    print("通过 %d / 失败 %d" % (len(_CHECKS) - len(FAILS), len(FAILS)))
    return len(FAILS)


def _subprocess_fail_names():
    r = subprocess.run([sys.executable, "-X", "utf8", _SELF, "--assert-only"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=_REPO, timeout=600)
    names = set(re.findall(r"(?m)^\s*FAIL\s+([A-Z]\d+)", r.stdout or ""))
    return names, (r.stdout or "") + (r.stderr or "")


_SA_OK = chr(10).join([
    '    # issue #467：sensitivity 透传（缺省 None ⇒ 行为逐位不变，与 #258 同口径）。',
    '    # 此前该形参不存在 ⇒ designer 声明 private 的身份锚点被静默降 internal 明文落盘。',
    '    extra = {}',
    '    if sensitivity is not None:',
    '        extra["sensitivity"] = sensitivity',
    '    cg.add(nid, text, layer=layer, tags=tg, condition_space=cs,',
])
_AT_OK = chr(10).join([
    '    # issue #467：sensitivity 透传（缺省 None ⇒ 行为逐位不变，与 #258 同口径）。',
    '    extra = {}',
    '    if sensitivity is not None:',
    '        extra["sensitivity"] = sensitivity',
    '    cg.add(nid, trait, layer="structural", tags=tg, condition_space=cs,',
])
_ARMS = {
    "M1": (
        "md_cg/identity.py",
        _SA_OK,
        "    extra = {}" + chr(10) + "    cg.add(nid, text, layer=layer, tags=tg, condition_space=cs,",
        {"A02", "A03", "A06", "E02"},
    ),
    "M2": (
        "md_cg/identity.py",
        _AT_OK,
        "    extra = {}" + chr(10) + '    cg.add(nid, trait, layer="structural", tags=tg, condition_space=cs,',
        {"A04", "A05", "A07", "E02"},
    ),
    "M3": (
        "md_cg/mcp_server.py",
        "            position=a.get(\"position\"), kind=a.get(\"subject_kind\"),\n"
        "            verification_basis=a.get(\"verification_basis\") or \"data\",\n"
        "            sensitivity=a.get(\"sensitivity\"),\n"
        "            override=bool(a.get(\"override\")))",
        "            position=a.get(\"position\"), kind=a.get(\"subject_kind\"),\n"
        "            verification_basis=a.get(\"verification_basis\") or \"data\",\n"
        "            override=bool(a.get(\"override\")))",
        {"A07", "E03"},
    ),
    "M5": (
        "md_cg/mcp_server.py",
        "            importance=float(a.get(\"importance\", 0.9)),\n"
        "            sensitivity=a.get(\"sensitivity\"),\n"
        "            override=bool(a.get(\"override\")),\n"
        "            requested_layer=a.get(\"requested_layer\"))",
        "            importance=float(a.get(\"importance\", 0.9)),\n"
        "            override=bool(a.get(\"override\")),\n"
        "            requested_layer=a.get(\"requested_layer\"))",
        {"A06", "E03"},
    ),
    "M4": (
        "md_cg/identity.py",
        "    extra = {}\n    if sensitivity is not None:\n        extra[\"sensitivity\"] = sensitivity\n    cg.add(nid, text, layer=layer, tags=tg, condition_space=cs,",
        "    extra = {\"sensitivity\": sensitivity or \"private\"}\n    cg.add(nid, text, layer=layer, tags=tg, condition_space=cs,",
        {"A01", "E02"},
    ),
    "M6": (
        "md_cg/op_table.py",
        "            \"requested_layer\",\n            \"sensitivity\",\n            \"contract_id\",",
        "            \"requested_layer\",\n            \"contract_id\",",
        {"E05"},
    ),
}


def _mutate(argv):
    want = ""
    for a in argv:
        if a == "--mutate":
            want = want or "ALL"
        elif a.startswith("--mutate="):
            want = a.split("=", 1)[1]
    if not want:
        return 0
    ids = sorted(_ARMS) if want == "ALL" else [want]
    red = 0
    for mid in ids:
        if mid not in _ARMS:
            print("[ANCHOR-MISS] %s：未登记该变异臂" % mid)
            return 2
        rel, old, new, expect = _ARMS[mid]
        target = os.path.join(_REPO, *rel.split("/"))
        with open(target, "rb") as fh:
            orig = fh.read()
        try:
            text = orig.decode("utf-8")
            nl = "\r\n" if "\r\n" in text else "\n"
            norm = text.replace("\r\n", "\n")
            _cnt = norm.count(old)
            if _cnt not in (1, 2):
                print("[ANCHOR-MISS] %s：锚点命中 %d 次（期望 1 或 2）⇒ 无法变异，判据失效"
                      % (mid, _cnt))
                return 2
            with open(target, "wb") as fh:
                fh.write(norm.replace(old, new).replace("\n", nl).encode("utf-8"))
            actual, out = _subprocess_fail_names()
            if actual == expect:
                print("[MUTATE-OK]   %s：指定断言转红 %s" % (mid, sorted(actual)))
            else:
                print("[MUTATE-FAIL] %s：期望红 %s，实际红 %s"
                      % (mid, sorted(expect), sorted(actual)))
                for line in out.splitlines():
                    if line.strip().startswith("FAIL"):
                        print("    " + line)
                red += 1
        finally:
            with open(target, "wb") as fh:
                fh.write(orig)
    print("反证结果：%d 条变异，%s" % (len(ids), "全部恰好命中" if red == 0 else "%d 条未命中" % red))
    return 1 if red else 0


if __name__ == "__main__":
    _f = _run_assertions()
    if "--assert-only" in sys.argv:
        sys.exit(1 if _f else 0)
    _m = _mutate(sys.argv[1:])
    sys.exit(1 if (_f or _m) else 0)
