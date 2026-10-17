# -*- coding: utf-8 -*-
# 功能名：override 审计行执行者归属（issue #451）
# 生效条件：python -X utf8 -m md_cg.test_issue451_override_write_actor [--mutate]；被测面＝md_cg/protect.py 的 _allow（override_write / override_move / override_forget 三类 override 审计行 actor 兜底的**单点**）与其上调用面（mdcg.add 的 extra.get("actor")、工具面 mdcg_remember 直写、裸守卫 guard_*）
# 子功能：W 组＝工具面 mdcg_remember(override=True) 覆写 anchor（issue §一① 形态）；E 组＝引擎写原点 cg.add(override=True)（工具面直写 / 变更单执行 / 引擎面三条路的公共汇点，issue §一② 的落盘站点）；R 组＝反向腿（显式声明 actor 优先于实例身份，issue §四「现绿」侧）；M 组＝override_move / override_forget（issue §六请维护者一并收口的姊妹动作）；K 组＝非恒真对照（非受保护节点零 override 行、行对同一 node 配对）；S 组＝结构单点（兜底恰在 _allow 一处、调用面未被复制第二份口径）
# 执行：--mutate 时在镜像树里去掉 _allow 的 actor 兜底（回到 #451 修前形态），守卫必须且仅须 W02/E01/M01/M02/S01 转红；另调 _guard_kit.assert_revert_reddens 骨架②实跑回退
# 验证方式：全部 PASS 即通过（退出码 0）；变异红项集合须与预期逐项相符（多红少红皆不合格）
# 不适用条件：不判前像缺失的 fail-open/fail-closed（#413 既有裁定，本件不改语义）；不判审核队列普通提案 accept 不带 override 的既有语义（另一站点）；不判 _audit.jsonl 普通审计面（issue 实测有名）；不改 mdcg.py 调用面——单点收口按 issue §四方案① 选 _allow，调用方显式声明仍优先
"""issue #451 守卫：override 审计行不记执行者（actor: null）—— P1 审计留痕完整性。

病象（修前，探针实测）：`mdcg_remember(..., override=True)` 覆写 anchor 节点后
`_protected_audit.jsonl` 里同一时刻的两行：

    action=snapshot        actor='bob-toolface'     ← 前像行**有**名字
    action=override_write  actor=None               ← 覆写行**没有**名字

根因（issue §二）：actor 判据被写了两份——`snapshot()` / `snapshot_preimage()`
在 `_audit` 落点兜底 `getattr(cg, "actor", None)`，而 `_allow` 把调用方传入值
原样转 `_audit`；`mdcg.add` 的调用面传 `extra.get("actor")`（载荷无 actor 即
None）⇒ `override_write` / `override_move` 行无主。姊妹动作 `override_forget`
的调用面（mdcos forget / verify falsified）自带实例身份兜底，故有名——**同一
时刻信息拿得到，只有这一条出口丢了**。

修法（issue §四方案①，单点）：`_allow` 兜底 `actor if actor is not None else
getattr(cg, "actor", None)`，与同文件 `snapshot()` / `snapshot_preimage()`
同口径；三类 override 动作（write/move/forget）一次收口；显式声明值恒优先。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# W 组（工具面直写腿）需要档位放行：进程级 env，先于 md_cg 导入设置。
# 本守卫由 run_tests.py 以**每文件一个子进程**执行（实测 scripts/run_tests.py
# 的收集面），不向其他守卫泄漏；--mutate 镜像子进程经 os.environ 继承同值。
os.environ["MDCG_AUTONOMY"] = "full"

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import _guard_kit as GK        # noqa: E402
from md_cg import protect                 # noqa: E402
from md_cg import mcp_server as _ms       # noqa: E402
from md_cg.mdcos import MdCGOS            # noqa: E402

FAILS = []
_TMP = tempfile.mkdtemp(prefix="iss451_")
_CCG = chr(10).join(["# 功能名：override 目标节点", "# 生效条件：本地合成库",
                     "# 子功能：无", "# 执行：无", "# 验证方式：test",
                     "# 不适用条件：无", "# 正文：issue451 探针"])


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


def _lib(tag, actor):
    """合成库 + 一个 anchor 节点（层保护 ⇒ is_immutable 真 ⇒ guard_write 走 _allow）。"""
    d = os.path.join(_TMP, tag)
    os.makedirs(d, exist_ok=True)
    cg = MdCGOS(d, actor=actor)
    cg.add("anch_t", _CCG, layer="anchor")
    cg.flush()
    return cg


def _rows(cg):
    p = os.path.join(cg.root, protect.AUDIT_FILE)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _actors(cg, action, node_id=None):
    return [r.get("actor") for r in _rows(cg)
            if r.get("action") == action
            and (node_id is None or r.get("node_id") == node_id)]


print("== W 组：工具面 mdcg_remember(override=True) 覆写 anchor（issue §一①） ==")
_cgW = _lib("w", "bob-toolface")
_rW = _ms._dispatch(_cgW, "mdcg_remember",
                    {"node_id": "anch_t", "content": _CCG + " v2",
                     "layer": "anchor", "override": True})
_check("W01 前提：工具面直写落盘（committed=true；env 档位未生效时此处先红，别误判 W02）",
       bool(_rW.get("ok")) and bool(_rW.get("committed")),
       {k: _rW.get(k) for k in ("ok", "committed", "moved_to")})
_check("W02 主张：override_write 行 actor 非空且等于身份 actor（修前 None）",
       _actors(_cgW, "override_write", "anch_t") == ["bob-toolface"],
       _rows(_cgW))
_check("W03 对照：同一次覆写的前像行 snapshot 有名（修前也绿——信息在同一时刻拿得到）",
       "bob-toolface" in _actors(_cgW, "snapshot", "anch_t"),
       _actors(_cgW, "snapshot", "anch_t"))
_cgW.close()

print("== E 组：引擎写原点 cg.add(override=True)（两写面公共汇点，issue §一② 落盘站点） ==")
_cgE = _lib("e", "engine-actor")
_cgE.add("anch_t", _CCG + " v2", layer="anchor", override=True)
_check("E01 主张：引擎面 override_write 行 actor 等于实例身份（修前 None）",
       _actors(_cgE, "override_write", "anch_t") == ["engine-actor"],
       _rows(_cgE))
_cgE.add("anch_t", _CCG + " v3", layer="anchor", override=True,
         actor="declared-x")
_check("E02 反向腿：载荷显式声明 actor 时以显式值为准（现绿，不因兜底被实例身份盖掉）",
       _actors(_cgE, "override_write", "anch_t")[-1] == "declared-x",
       _actors(_cgE, "override_write", "anch_t"))
_cgE.close()

print("== R 组：反向腿（裸守卫显式 actor 优先） ==")
_cgR = _lib("r", "instance-actor")
_fr = protect.guard_write(_cgR, "anch_t", override=True, actor="explicit-451")
_check("R01 guard_write(actor=…) 显式值逐字落行（返回体 audit.actor 同源）",
       isinstance(_fr, dict)
       and _actors(_cgR, "override_write", "anch_t") == ["explicit-451"]
       and (_fr.get("audit") or {}).get("actor") == "explicit-451",
       _fr if not isinstance(_fr, dict) else (_fr or {}).get("audit"))
_cgR.close()

print("== M 组：override_move / override_forget（姊妹动作，同一单点收口） ==")
_cgM = _lib("m", "move-actor")
protect.guard_move(_cgM, "anch_t", "knowledge", override=True)
_check("M01 主张：override_move 行 actor 等于实例身份（issue §六未测项，修前 None）",
       _actors(_cgM, "override_move", "anch_t") == ["move-actor"],
       _rows(_cgM))
_cgM2 = _lib("m2", "forget-actor")
protect.guard_forget(_cgM2, "anch_t", override=True)
_check("M02 主张：guard_forget 未显式传 actor 时同样兜底实例身份（单点族全覆盖）",
       _actors(_cgM2, "override_forget", "anch_t") == ["forget-actor"],
       _rows(_cgM2))
_cgM.close()
_cgM2.close()

print("== K 组：非恒真对照 ==")
_cgK = _lib("k", "plain-actor")
_cgK.add("kn1", _CCG, layer="knowledge")            # 非受保护层新节点
_cgK.add("kn1", _CCG + " v2", layer="knowledge")    # 覆写不受保护 ⇒ 无 override 行
_check("K01 非受保护节点覆写不产生任何 override_* 审计行（兜底不越界）",
       not [r for r in _rows(_cgK) if str(r.get("action") or "").startswith("override")],
       _rows(_cgK))
_cgK.add("anch_t", _CCG + " v2", layer="anchor", override=True)
_acts = {r.get("action") for r in _rows(_cgK) if r.get("node_id") == "anch_t"}
_check("K02 行对配对：同一 node 的 snapshot 与 override_write 行同在（事件不静默）",
       {"snapshot", "override_write"} <= _acts, _acts)
_cgK.close()

print("== S 组：结构单点（兜底恰一处，调用面不复制第二份口径） ==")
_SRC = open(os.path.join(_REPO, "md_cg", "protect.py"),
            encoding="utf-8", newline="").read().replace("\r\n", "\n")
_ALLOW_WIN = _SRC[_SRC.index("def _allow"): _SRC.index("def guard_write")]
_FALLBACK = 'actor if actor is not None else getattr(cg, "actor", None)'
_check("S01 _allow 内兜底恰一处（三类 override 动作共用；去掉即回到 #451 修前）",
       _ALLOW_WIN.count(_FALLBACK) == 1,
       _ALLOW_WIN.count(_FALLBACK))
_MDCG_SRC = open(os.path.join(_REPO, "md_cg", "mdcg.py"),
                 encoding="utf-8", newline="").read().replace("\r\n", "\n")
_check("S02 调用面保持声明式透传（extra.get(\"actor\")）——收口只在 _allow 单点，不写两份",
       "actor=extra.get(\"actor\"))" in _MDCG_SRC,
       _MDCG_SRC.count("extra.get(\"actor\")"))

shutil.rmtree(_TMP, ignore_errors=True)
print("")
print("issue #451 结果：%s" % ("全部通过" if not FAILS else "%d 失败" % len(FAILS)))


# ---------------------------------------------------------------- 变异自证
_NL = "\r\n" if b"\r\n" in open(os.path.join(_REPO, "md_cg", "protect.py"),
                                "rb").read()[:8192] else "\n"

# 定点变异：去掉 _allow 的 actor 兜底（回到 #451 修前形态——调用方传 None 即落 None）。
_FIX_BODY = ("    rec = _audit(cg, action, node_id, why," + chr(10)
             + "                 actor if actor is not None"
               " else getattr(cg, \"actor\", None)," + chr(10)
             + "                 snap)")
_PRE_BODY = "    rec = _audit(cg, action, node_id, why, actor, snap)"
# 期望转红＝四条主张腿（工具面/引擎面/move/forget 的 actor 归属）+ 结构单点；
# W01（前提）、W03（snapshot 对照）、E02/R01（反向腿现绿侧）、K 组（对照）必须仍绿。
_EXPECT_REDS = ("W02", "E01", "M01", "M02", "S01")


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss451_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env.update({"PYTHONPATH": tree, "PYTHONUTF8": "1",
                "PYTHONDONTWRITEBYTECODE": "1"})
    env.pop("MDCG_ROOT", None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue451_override_write_actor"],
                        cwd=tree, env=env, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-20:]))
            bad.append("镜像基线即红")
        p = os.path.join(tree, "md_cg", "protect.py")
        t = open(p, encoding="utf-8", newline="").read()
        fix_nl = _FIX_BODY.replace(chr(10), _NL)
        pre_nl = _PRE_BODY.replace(chr(10), _NL)
        if t.count(fix_nl) != 1:
            bad.append("变异锚点命中 %d 次" % t.count(fix_nl))
            print("  ANCHOR-MISS 去掉兜底（命中 %d 次）" % t.count(fix_nl))
        else:
            open(p, "w", encoding="utf-8", newline="").write(
                t.replace(fix_nl, pre_nl, 1))
            for r, dd, ff in os.walk(tree):
                if os.path.basename(r) == "__pycache__":
                    shutil.rmtree(r, ignore_errors=True)
            rc2, reds2, _o2 = _run_in(tree)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(_EXPECT_REDS):
                print("  OK   去掉 _allow 兜底 红项=%d 指定命中=%d/%d"
                      % (len(reds2), len(hit), len(_EXPECT_REDS)))
            else:
                bad.append("去掉 _allow 兜底")
                print("  MISMATCH 去掉兜底 实际=%s 期望=%s rc=%d"
                      % (hit, sorted(_EXPECT_REDS), rc2))
                for r in reds2[:8]:
                    print("        FAIL " + r)
        ok_r, det_r = GK.assert_revert_reddens(
            _mirror_build,
            [("md_cg/protect.py", _FIX_BODY, _PRE_BODY)],
            _run_in, _EXPECT_REDS, "md_cg/protect.py")
        print("  骨架②回退即红：%s %s" % ("OK" if ok_r else "MISMATCH",
                                          json.dumps(det_r, ensure_ascii=False)[:200]))
        if not ok_r:
            bad.append("骨架②未按预期转红")
        print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
