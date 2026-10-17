# -*- coding: utf-8 -*-
# 功能名：既有节点的覆写/入队必须按**真密级**过层闸（issue #346：低权身份经审核队列覆写属主 private 节点）
# 生效条件：python -X utf8 -m md_cg.test_issue346_overwrite_sensitivity_gate [--mutate]；被测面＝md_cg/mdcg.py 的 MdCG.add（同层覆写闸）+ md_cg/mdcos.py 的 MdCGSecure.propose（入队闸），判据单点 protect.require_layer
# 子功能：A 组＝正向腿（直写面／入队面／accept 落盘面三路越权必须 fail-closed，且节点密级与盘面加密未被降级）；K 组＝反向腿①（合法同层写/同密级写/新 id 写/无 principal 载体照常成功，防一刀切）；E 组＝源码面（两处判据存在且 add 闸在**同层**也触发）；M 组＝反向腿②（--mutate 定点变异，红项集合严格相等、两站点红项不重叠）
# 执行：--mutate 时在镜像树里逐条撤闸／改成按声明值判，守卫必须按指定项转红（多红/少红皆不合格）
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期逐项相符，锚点未命中即 fail-closed（打印 ANCHOR-MISS 并计入不合格）
# 不适用条件：① 腿看不见「密级判定算法是否正确」——只看见「既有节点真密级 ↔ 写入者 clearance」是否被比对（§5.2 P0-2 可判性边界）；② 不覆盖「存量已在队列里的提案由**属主**accept」那条遗留（属主 clearance 够，判据要比较「提案密级 vs 目标当前密级」，本批不动）；③ 不覆盖 require_layer 在索引缺 sensitivity 时回读 fm 失败回落 internal 的 fail-open 固有面（#346 遗留，直写面同款）；④ 不覆盖真实 stdio / 令牌签发面（另一守卫 test_issue320/test_issue320_vstate_requires_verify 覆盖工具面）；⑤ 不判 orchestr 经 consistency(history) 枚举 private id（#298 残留，本批不碰）；⑥ **本腿要求 A 组三面各自独立库**——若共用一个库，前一面可达（撤闸后直写成功）会把目标降成更低密级，使后一面的闸「钝化」而假绿/串味（本轮实测：共库时 M1 多红一条 A2，红项集合不再严格相等）⇒ 共库读数**无效**。属腿的夹具约束，不是实现约束（与 #471「读者恰好同会话」、#472 夹具坑同族）。
"""issue #346 守卫：覆写既有节点时「声明的密级」不得绕过「既有真密级」。

病象（修前）：`MdCGSecure.propose` 只拿**声明值**比自己（`require_layer_write(声明层, 声明密级)`），
`MdCG.add` 的保护/层闸只在**跨层**时按既有真密级判（N221 分支 `_prev_layer != layer`）。
于是 clearance 上限 internal 的 orchestr 令牌对属主 contextual 层 private 节点
`cg(op=write, sensitivity="internal")` 先入队、再自己 `review_decide(accept)`，节点被整条
覆写成 internal **明文**（盘面不再是 mdcg-enc），无令牌访客可读——三条落盘出口（直写、
审核 accept/edit、C 类变更单）都汇到 `MdCG.add`，却没有任何一处比对「既有 private ＞ 写入者 internal」。

修法（两站点，纯加严，判据单点 `protect.require_layer`）：
  · `MdCG.add`：把 require_layer 从「仅跨层」提到「prev_entry 存在即调」——同层覆写也按既有
    真层+真密级过 principal 层闸；跨层支只保留 `guard_move`（次序不变：层闸在先、保护闸在后）。
  · `MdCGSecure.propose`：入队前按既有节点真层+真密级再判一次，提案者自己落不了盘的覆写不入队。

夹具约束（不适用条件⑥）：A 组三面**必须各自独立库**。共库时「前一面可达」会把目标\n降成更低密级，使后一面的闸钝化——本轮实测共库形态下 M1 多红一条 A2（红项串味、\n「多站点红项不重叠」判据当场失效）。这是腿的夹具缺陷，不是实现的缺陷。\n\n本守卫的判别力来自非恒真对照：K1-K4 是「防一刀切」的反向腿（合法写必须仍然成功），
M1/M3 撤或软化 add 闸、M2/M4 撤或软化入队闸——两组红项集合**互不重叠**，
证明腿分别钉在两个站点上（而非一个闸包打天下）。
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_TMP = tempfile.mkdtemp(prefix="iss346_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore", "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP, "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
                   "MDCG_AUTONOMY": "confirm"})
os.environ.pop("MDCG_READ_CACHE", None)

from md_cg import tokens as _tk                       # noqa: E402
from md_cg.mdcos import MdCGSecure                    # noqa: E402
from md_cg.mdcg import MdCG                           # noqa: E402
from md_cg.security import AccessDenied, Principal    # noqa: E402

PASSED, FAILS = [], []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
        PASSED.append(name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:240])
        FAILS.append(name)


def _ccg(nid):
    return chr(10).join(["# 功能名：端口配置 " + nid, "# 生效条件：服务启动时读取",
                         "# 子功能：监听端口", "# 执行：绑定 " + nid,
                         "# 验证方式：外部裁决", "# 不适用条件：无"])


def _mk(role):
    sp = _tk.role_spec(role)
    return Principal(clearance=sp["clearance_cap"], can_write=sp["can_write"],
                     can_admin=sp["can_admin"], role=role,
                     layers_allow=sp["layers_allow"], ops_allow=sp["ops_allow"])


def _cg(role, root):
    return MdCGSecure(root, principal=_mk(role), autoflush=1)


def _try(fn):
    """返回 (是否未被拒, 结果, 异常类名)。AccessDenied 单独标注。"""
    try:
        return True, fn(), None
    except AccessDenied:
        return False, None, "AccessDenied"
    except Exception as exc:                             # noqa: BLE001
        return False, None, type(exc).__name__


def _raw(root, cg, nid):
    p = os.path.join(root, cg.index["nodes"][nid]["path"])
    with open(p, encoding="utf-8") as f:
        return f.read()


def _content(cg, nid):
    node = cg.get(nid)
    return (node or {}).get("content") or ""


# ============================================ A 组：正向腿（越权必须 fail-closed）
def group_a(tmp):
    print("== A 组：正向腿——直写 / 入队 / accept 三路越权必须被拒 ==")
    # 三个面**各自独立库**：同库会互相污染（撤 add 闸后直写成功会把目标降成
    # internal，使后续入队面「本来就有闸」被前一步的后果掩盖）⇒ 红项集合会
    # 串味，多站点「红项不重叠」的判据就失效。
    # ---------- 面 1：直写面（root1）
    root1 = os.path.join(tmp, "a_direct")
    owner1 = _cg("designer", root1)
    owner1.add("v_own", _ccg("v_own"), layer="contextual", sensitivity="private")
    owner1.flush()
    plain = _raw(root1, owner1, "v_own")
    _check("A0 前置：属主 private 节点落盘为密文（mdcg-enc 在位）",
           "mdcg-enc" in plain, "head=%r" % plain[:40])
    orch1 = _cg("orchestr", root1)
    ok, _r, err = _try(lambda: orch1.add("v_own", _ccg("v_own") + chr(10) + "ATTACK_DIRECT",
                                         layer="contextual", sensitivity="internal"))
    _check("A1 直写面：orchestr(clearance=internal) 显式声明 internal 覆写既有 private → AccessDenied",
           (not ok) and err == "AccessDenied", "ok=%s err=%s" % (ok, err))
    orch1.close()
    owner1.close()
    owner1b = _cg("designer", root1)
    sens = ((owner1b.get("v_own") or {}).get("frontmatter") or {}).get("sensitivity")
    _check("A5 后果面：攻击后节点密级仍为 private",
           sens == "private", "sensitivity=%r" % sens)
    raw = _raw(root1, owner1b, "v_own")
    _check("A6 后果面：盘面仍为密文（未被降级为明文）",
           "mdcg-enc" in raw and "ATTACK_DIRECT" not in raw,
           "enc=%s" % ("mdcg-enc" in raw))
    owner1b.close()

    # ---------- 面 2：入队面（root2，独立库）
    root2 = os.path.join(tmp, "a_queue")
    owner2 = _cg("designer", root2)
    owner2.add("v_q", _ccg("v_q"), layer="contextual", sensitivity="private")
    owner2.flush()
    orch2 = _cg("orchestr", root2)
    ok2, _r2, err2 = _try(lambda: orch2.propose("v_q", _ccg("v_q") + chr(10) + "ATTACK_QUEUE",
                                                layer="contextual", sensitivity="internal"))
    _check("A2 入队面：同一覆写经 propose 也不得入队（提案者自己落不了盘的不进队列）",
           (not ok2) and err2 == "AccessDenied", "ok=%s err=%s" % (ok2, err2))
    orch2.close()
    owner2.close()

    # ---------- 面 3：accept 落盘面（root3，独立库）
    root3 = os.path.join(tmp, "a_accept")
    owner3 = _cg("designer", root3)
    orch3 = _cg("orchestr", root3)
    r3 = orch3.propose("v_late", _ccg("v_late") + chr(10) + "ATTACK_ACCEPT",
                       layer="contextual", sensitivity="internal")
    pid = r3 if isinstance(r3, str) else (r3 or {}).get("pid")   # MdCGOS.propose 返回 pid 串
    _check("A3 前置：目标不存在时 orchestr 的提案可正常入队（入队闸不误伤新 id）",
           bool(pid), "r=%r" % (r3,))
    owner3.add("v_late", _ccg("v_late"), layer="contextual", sensitivity="private")
    owner3.flush()
    ok4, _r4, err4 = _try(lambda: orch3.review_decide(pid, "accept"))
    after = _content(owner3, "v_late")
    _check("A4 accept 落盘面：目标在队列期间升为 private ⇒ 裁决落盘被拒（覆写未生效）",
           "ATTACK_ACCEPT" not in after,
           "accept_ok=%s err=%s content=%r" % (ok4, err4, after[:40]))
    orch3.close()
    owner3.close()


# ============================================ K 组：反向腿①（防一刀切）
def group_k(tmp):
    print("== K 组：反向腿①——合法写必须照常成功 ==")
    root = os.path.join(tmp, "k")
    owner = _cg("designer", root)
    owner.add("k_priv", _ccg("k_priv"), layer="contextual", sensitivity="private")
    owner.add("k_int", _ccg("k_int"), layer="contextual", sensitivity="internal")
    owner.flush()
    ok1, _r, err1 = _try(lambda: owner.add("k_priv", _ccg("k_priv") + chr(10) + "LEGAL_SAME_SENS",
                                           layer="contextual", sensitivity="private"))
    _check("K1 合法：属主覆写自己的 private 节点（同密级同层）仍成功",
           ok1, "err=%s" % err1)
    ok2, _r2, err2 = _try(lambda: owner.add("k_priv", _ccg("k_priv") + chr(10) + "LEGAL_DEMOTE",
                                            layer="contextual", sensitivity="internal"))
    _check("K2 合法：属主**主动降密**（clearance 够）仍成功", ok2, "err=%s" % err2)
    orch = _cg("orchestr", root)
    ok3, _r3, err3 = _try(lambda: orch.add("k_int", _ccg("k_int") + chr(10) + "LEGAL_SAME_LEVEL",
                                           layer="contextual", sensitivity="internal"))
    _check("K3 合法：internal 身份覆写 internal 节点（同层同密级）仍成功",
           ok3, "err=%s" % err3)
    ok4, _r4, err4 = _try(lambda: orch.add("k_new_by_orch", _ccg("k_new") + chr(10) + "LEGAL_NEW_ID",
                                           layer="contextual", sensitivity="internal"))
    _check("K4 合法：新 id 落盘（无既有节点）不受本闸影响", ok4, "err=%s" % err4)
    bare_root = os.path.join(tmp, "k_bare")
    bare = MdCG(bare_root)
    bare.add("b1", _ccg("b1"), layer="contextual")
    ok5, _r5, err5 = _try(lambda: bare.add("b1", _ccg("b1") + chr(10) + "BARE_OVERWRITE",
                                           layer="contextual"))
    _check("K5 合法：无 principal 的裸 MdCG 覆写照旧放行（require_layer 无 principal 不判定）",
           ok5, "err=%s" % err5)
    bare.close()
    orch.close()
    owner.close()


# ============================================ E 组：源码面（两站点判据在位）
def _ast(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return ast.parse(f.read(), rel)


def _func(rel, cls_name, fn_name):
    for node in ast.walk(_ast(rel)):
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == fn_name:
                    return sub
    return None


def _calls(fn, name):
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            if (getattr(f, "attr", None) or getattr(f, "id", None)) == name:
                out.append(node)
    return out


def group_e(tmp):
    print("== E 组：源码面——两站点判据在位且 add 闸在**同层**也触发 ==")
    add_fn = _func("md_cg/mdcg.py", "MdCG", "add")
    prop_fn = _func("md_cg/mdcos.py", "MdCGSecure", "propose")
    _check("E0 定位成功：MdCG.add 与 MdCGSecure.propose 均可达",
           add_fn is not None and prop_fn is not None)
    rl_add = _calls(add_fn, "require_layer") if add_fn else []
    _check("E1 MdCG.add 调 protect.require_layer 恰一处（判据单点，不自写比较）",
           len(rl_add) == 1, "calls=%d" % len(rl_add))
    rl_prop = _calls(prop_fn, "require_layer") if prop_fn else []
    _check("E2 MdCGSecure.propose 调 protect.require_layer 恰一处（入队闸）",
           len(rl_prop) == 1, "calls=%d" % len(rl_prop))
    inside = []
    if add_fn is not None:
        for node in ast.walk(add_fn):
            if isinstance(node, ast.If):
                dump = ast.dump(node.test)
                if "NotEq" in dump and "_prev_layer" in dump:
                    inside = [c.lineno for c in _calls(node, "require_layer")]
    _check("E3 add 闸**不在**「_prev_layer != layer」的跨层分支内（同层覆写也过闸）",
           inside == [], "inside=%s" % inside)


def main():
    print("== #346 覆写真密级闸 ==")
    try:
        _guard_group("A", group_a, _TMP)
        _guard_group("K", group_k, _TMP)
        _guard_group("E", group_e, _TMP)
    finally:
        pass
    print("=" * 68)
    print("#346 守卫：%d 通过，%d 失败" % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print("  红项：" + f)
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


def _guard_group(tag, fn, tmp):
    """组内异常 fail-closed：异常即红（否则后续断言会被静默跳过 = 假绿）。"""
    try:
        fn(tmp)
    except Exception as exc:                              # noqa: BLE001
        import traceback
        _check("%s0 组内异常（fail-closed：异常即红）" % tag, False,
               "%s: %s" % (type(exc).__name__, exc))
        traceback.print_exc()


# ============================================ M 组：反向腿②（定点变异自证）
#: 每条变异＝(描述, 目标文件, ((old, new), ...), 期望红项集合)。
#: 红项集合必须**严格相等**；两组红项**互不重叠** ⇒ 证明腿分别钉在两个站点上。
_MUTATIONS = (
    ("M1 撤 add 闸（mdcg.py 的 require_layer 调用删除 = #346 同层覆写零闸形态）",
     "md_cg/mdcg.py",
     (("            protect.require_layer(self, node_id, layer=_prev_layer," + chr(10)
       + "                                  sensitivity=prev_entry.get(\"sensitivity\")," + chr(10)
       + "                                  actor=extra.get(\"actor\"))",
       "            pass  # M1 撤 add 闸"),),
     ("A1", "A4", "A5", "A6", "E1")),
    ("M2 撤入队闸（mdcos.py 的 propose 闸整块删除）",
     "md_cg/mdcos.py",
     (("        if isinstance(node_id, str) and node_id:" + chr(10)
       + "            self._maybe_reload_index()" + chr(10)
       + "            _ex = (self.index.get(\"nodes\") or {}).get(node_id)" + chr(10)
       + "            if _ex is not None:" + chr(10)
       + "                protect.require_layer(self, node_id," + chr(10)
       + "                                      layer=_ex.get(\"layer\") or None," + chr(10)
       + "                                      sensitivity=_ex.get(\"sensitivity\") or None)",
       "        pass  # M2 撤入队闸"),),
     ("A2", "E2")),
    ("M3 add 闸软化：按调用方**声明值**判（而非既有真密级）= 缺陷原形态",
     "md_cg/mdcg.py",
     (("            protect.require_layer(self, node_id, layer=_prev_layer," + chr(10)
       + "                                  sensitivity=prev_entry.get(\"sensitivity\")," + chr(10)
       + "                                  actor=extra.get(\"actor\"))",
       "            protect.require_layer(self, node_id, layer=_prev_layer," + chr(10)
       + "                                  sensitivity=extra.get(\"sensitivity\")," + chr(10)
       + "                                  actor=extra.get(\"actor\"))"),),
     ("A1", "A4", "A5", "A6")),
    ("M4 入队闸软化：按调用方**声明值**判（sens）",
     "md_cg/mdcos.py",
     (("                protect.require_layer(self, node_id," + chr(10)
       + "                                      layer=_ex.get(\"layer\") or None," + chr(10)
       + "                                      sensitivity=_ex.get(\"sensitivity\") or None)",
       "                protect.require_layer(self, node_id," + chr(10)
       + "                                      layer=_ex.get(\"layer\") or None," + chr(10)
       + "                                      sensitivity=sens)"),),
     ("A2",)),
)


def _mirror_build():
    """镜像树：**绝不在真实工作树里改源**（写面纪律）。"""
    dst = tempfile.mkdtemp(prefix="iss346_mut_")
    for name in ("md_cg", "lib"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and name.endswith(".py"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for k in ("MDCG_ROOT", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT", "MDCG_DATA_ROOT",
              "MDCG_EXPORT_ROOT", "MDCG_INGEST_ROOT", "MDCG_TOKEN", "MDCG_TOKEN_FILE"):
        env.pop(k, None)
    pr = subprocess.run([sys.executable, "-u", "-X", "utf8", "-m",
                         "md_cg.test_issue346_overwrite_sensitivity_gate"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _apply_text(text, rel, pairs):
    """按目标文件**实际行尾**折算锚点后逐条替换；任一锚点命中数 != 1 返回 (None, 原因)。"""
    eol = (chr(13) + chr(10)) if (chr(13) + chr(10)) in text else chr(10)
    for old, new in pairs:
        o = old.replace(chr(10), eol)
        n = new.replace(chr(10), eol)
        if text.count(o) != 1:
            return None, "锚点在 %s 里命中 %d 次" % (rel, text.count(o))
        text = text.replace(o, n, 1)
    return text, ""


def _mutate():
    print("!! 反向腿②：逐条撤闸／软化判据，守卫必须按指定项转红（红项集合严格相等）")
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
            for root, _dd, _ff in os.walk(tree):
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
                for r in reds2[:12]:
                    print("        FAIL " + r)
                if rc2 == 0:
                    print(chr(10).join(out2.splitlines()[-15:]))
        print("反向腿②：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
