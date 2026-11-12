# -*- coding: utf-8 -*-
# 功能名：verify(weakened) 的降级轮必须落盘，回执必须等于盘面（issue #410）
# 生效条件：python -X utf8 -m md_cg.test_issue410_verify_demote_write [--mutate]；被测面＝md_cg/mdcg.py::MdCG.verify 的 confirmed/weakened 两分支（含落盘尾单点 _land_fm）
# 子功能：A 组＝连续 weakened 到降级轮（回执==盘面、状态自洽、证据不丢、重开后索引==盘面）；K 组＝非恒真对照（非降级轮不受扰、不搬层、schema 不变、落盘恰好一次）；E 组＝**分支级**源码判据（单点 + 两分支都过它 + 回执回读）
# 执行：--mutate 时在镜像树里回缺陷/收紧（摘降级分支落盘、摘标脏、摘非降级分支落盘），守卫必须按指定项转红；另调 _guard_kit 两骨架
# 验证方式：全部 PASS 即通过（退出码 0）；变异与骨架红项集合须与预期逐项相符
# 不适用条件：不判档位闸（verify 四面不接 E 面闸，见 #408）；不判「降级 + 受保护节点」组合（guard_move 先拦，属既有面）；不判工具面 mdcg_verify（同一实现）；不判 confidence 是否应夹回阈值之下（**语义裁定**，归维护者——本批只主张「回执说什么，盘面就该是什么」）
"""issue #410 守卫：回执与盘面必须同源。

病象（修前）：`verify` 的 **降级分支**整段跳过落盘尾（`_write_node` + 索引同步
+ `_dirty`）——本轮 `confidence`/`evidence_count`/`negative_evidence`/
`evidence_log` 只在内存里，回执却照报内存值；盘面仍是旧值，于是同一份 .md 里
`layer: contextual`（已降级）与 `confidence: 0.3`（**高于**触发降级的阈值 0.2）
自相矛盾，且**触发降级的证据本身丢了**。

修法（落结构性不变量）：把本轮 fm 的**落盘尾收成单点** `_land_fm()`
（写盘 + 索引同步 + 标脏），**两个分支都只经它**；降级轮顺序＝
`_land_fm()` → `_move_layer` → `set_state`；回执字段改为**落盘后回读**。

⚠ 本守卫的族判据是**分支级**（不是函数级）：`verify` 体内本来就有
`_write_node`（在 else 分支），函数级扫描会判它「有落盘」——真实缺陷恰是
**分支级不对称**（#421「声称的面 > 实际的面」的同形坑）。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from unittest import mock

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import _guard_kit as GK        # noqa: E402
from md_cg import mdcg as _mdcg           # noqa: E402
from md_cg.mdcos import MdCGOS            # noqa: E402

FAILS = []
_TMP = tempfile.mkdtemp(prefix="iss410_")
_CCG = chr(10).join(["# 功能名：证据节点", "# 生效条件：本地合成库", "# 子功能：无",
                     "# 执行：无", "# 验证方式：test", "# 不适用条件：无",
                     "# 正文：证据节点正文"])


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


def _disk(root):
    """直接读盘上 .md 的 frontmatter 行（**不靠 cg.get**，与报告口径一致）。"""
    for layer in ("knowledge", "contextual"):
        for dp, _dd, ff in os.walk(os.path.join(root, layer)):
            for f in sorted(ff):
                if not f.endswith(".md"):
                    continue
                txt = open(os.path.join(dp, f), encoding="utf-8").read()
                fm, in_fm = {}, False
                for line in txt.splitlines():
                    if line.strip() == "---":
                        if in_fm:
                            break
                        in_fm = True
                        continue
                    if not in_fm:
                        continue
                    m = re.match(r"(\w+):\s*(.*)$", line)
                    if m:
                        fm[m.group(1)] = m.group(2).strip()
                return (os.path.relpath(os.path.join(dp, f), root), fm, txt)
    return None, {}, ""


def _new(tag):
    d = os.path.join(_TMP, tag)
    os.makedirs(d, exist_ok=True)
    cg = MdCGOS(d)
    cg.add("ev_1", _CCG, layer="knowledge")
    cg.flush()
    cg.close()
    return d


def _round(root, verdict="weakened", evidence="证据"):
    cg = MdCGOS(root)
    r = cg.verify("ev_1", evidence, verdict)
    cg.flush()
    cg.close()
    return r


print("== A 组：降级轮（#410 正题） ==")
_root = _new("demote")
_r1 = _round(_root, evidence="证据 1")
_r2 = _round(_root, evidence="证据 2")
_r3 = _round(_root, evidence="证据 3")           # 第三轮：confidence 0.3→0.15 < 0.2 ⇒ 降级
_rel, _fm, _txt = _disk(_root)
_check("A01 降级轮：回执 confidence == 盘面 confidence（修前 0.15 vs 0.3）",
       str(_r3.get("confidence")) == _fm.get("confidence"),
       (_r3.get("confidence"), _fm.get("confidence")))
_check("A02 降级轮：回执 evidence_count == 盘面（修前 3 vs 2）",
       str(_r3.get("evidence_count")) == _fm.get("evidence_count"),
       (_r3.get("evidence_count"), _fm.get("evidence_count")))
_check("A03 状态自洽：盘面 layer=contextual 且 confidence < DEMOTE_CONFIDENCE（修前 0.3 在阈值之上）",
       _fm.get("layer", "").strip('"') == "contextual"
       and float(_fm.get("confidence")) < _mdcg.DEMOTE_CONFIDENCE,
       _fm)
_check("A04 触发降级的证据不丢：盘面 negative_evidence 已 +1 且 evidence_log 含本轮裁决",
       int(_fm.get("negative_evidence") or 0) >= 1
       and '"weakened"' in _txt and "证据 3" in _txt, _fm)
_check("A08 本轮值确实落盘：盘面 confidence == 0.15 且 evidence_count == 3（修前一个字节没写）",
       _fm.get("confidence") == "0.15" and _fm.get("evidence_count") == "3", _fm)
# A05：**flush 但不 close**（模拟「写后未收尾就退出」）——只有 _dirty 进了分片日志，
# 新实例才能重放出 evidence_count；漏标脏时索引停在旧值、与盘面漂移（修前形态）。
_root_dirty = _new("dirty")
_cgd = MdCGOS(_root_dirty)
_cgd.verify("ev_1", "证据 1", "weakened")
_cgd.flush()                      # 不 close：不给 compact 用内存索引兜底的机会
_cgd = None
_cgd2 = MdCGOS(_root_dirty)
_e5 = (_cgd2.index.get("nodes") or {}).get("ev_1") or {}
_fm5 = _disk(_root_dirty)[1]
_check("A05 未收尾（flush 不 close）后重开：索引 evidence_count == 盘面（标脏⇒日志⇒重放）",
       int(_e5.get("evidence_count") or -1) == int(_fm5.get("evidence_count") or -2),
       (_e5.get("evidence_count"), _fm5.get("evidence_count")))
_cgd2.close()

print("== K 组：非恒真对照 ==")
_check("K01 非降级轮（第 1/2 轮）回执 == 盘面（逐位不受扰）",
       str(_r1.get("confidence")) == "0.45" and str(_r2.get("confidence")) == "0.3",
       (_r1.get("confidence"), _r2.get("confidence")))
_root_k = _new("nodemote")
_rk = _round(_root_k, verdict="confirmed", evidence="正例")
_relk, _fmk, _ = _disk(_root_k)
_check("K02 未触发降级：层仍在 knowledge（不误搬）+ 回执 == 盘面",
       _fmk.get("layer", "").strip('"') == "knowledge"
       and str(_rk.get("confidence")) == _fmk.get("confidence"),
       (_fmk, _rk.get("confidence")))
_check("K03 回执 schema 不变（action/confidence/evidence_count/demoted/verification/propagation 六键俱在）",
       sorted(set(_r3) & {"action", "confidence", "evidence_count", "demoted",
                          "verification", "propagation"})
       == sorted(["action", "confidence", "evidence_count", "demoted",
                  "verification", "propagation"]), sorted(_r3))
_root_w = _new("onewrite")
_cgw = MdCGOS(_root_w)
_w = _cgw.verify("ev_1", "证据 1", "weakened")
_cgw.flush()
_cnt = {"n": 0}
_orig = _mdcg.MdCG._write_node


def _counting(self, *a, **kw):
    _cnt["n"] += 1
    return _orig(self, *a, **kw)


with mock.patch.object(_mdcg.MdCG, "_write_node", _counting):
    _cw = MdCGOS(_root_w)
    _cw.verify("ev_1", "证据 2", "weakened")     # 0.45→0.3，非降级
    _cw.close()
_cgw.close()
_check("K04 落盘尾不重复：一次非降级 verify **恰**落一次盘（新单点没引入额外写）",
       _cnt["n"] == 1, _cnt["n"])
_cnt2 = {"n": 0}


def _counting2(self, *a, **kw):
    _cnt2["n"] += 1
    return _orig(self, *a, **kw)


with mock.patch.object(_mdcg.MdCG, "_write_node", _counting2):
    _cw2 = MdCGOS(_root_w)
    _cw2.verify("ev_1", "证据 3", "weakened")     # 0.3→0.15 ⇒ 降级轮
    _cw2.close()
# 降级轮合法写点 = 3（落盘尾 1 + _move_layer 搬层 1 + set_state 补 lifecycle_state 1）；
# 重复落盘（过度方向）会变成 4 ⇒ 本腿专打「多写一次」。
_check("K05 降级轮写点恰为 3（落盘尾 + 搬层 + set_state；重复落盘=过度方向，本腿专打）",
       _cnt2["n"] == 3, _cnt2["n"])

print("== E 组：分支级源码判据（不是函数级） ==")
_SRC = open(os.path.join(_REPO, "md_cg", "mdcg.py"), encoding="utf-8").read()
_V = _SRC.split("    def verify(self, node_id")[1].split("    def flywheel_step")[0]
_check("E01 落盘尾是**单点**：verify 体内 _write_node 只出现在 _land_fm 内",
       _V.count("_write_node(") == 1 and "def _land_fm():" in _V,
       _V.count("_write_node("))
_check("E02 两个分支都过它（>=2 处调用：降级分支 + 非降级分支）",
       _V.count("_land_fm()") >= 2, _V.count("_land_fm()"))
_dem = _V.split("if (verdict == \"weakened\" and fm[\"confidence\"]")[1]     .split("else:")[0]
_check("E03 **分支级**：降级分支体内含 _land_fm()（函数级判据看不见 #410）",
       "_land_fm()" in _dem, _dem[:120])
_check("E04 回执走**落盘后回读**（_dfm.get 取自 self.get(node_id)）",
       "_disk = self.get(node_id)" in _V and '_dfm.get("confidence"' in _V)

print("== 骨架①：枚举完备性自证（分支级） ==")


def _discover(texts):
    """守卫自己的**分支级**枚举：命中「改了 fm 却在该分支内不落盘」的 verify 分支。"""
    import ast as _ast
    hits = []
    for rel, src in texts.items():
        try:
            tree = _ast.parse(src)
        except SyntaxError:
            continue
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.FunctionDef) or node.name != "verify":
                continue
            for sub in _ast.walk(node):
                seg = _ast.get_source_segment(src, sub) or ""
                if "fm[" not in seg and "fm.setdefault" not in seg:
                    continue
                if "if " in seg and "_write_node" not in seg and "_land_fm" not in seg:
                    hits.append((rel, sub.lineno))
                break
    return hits


_S_OLD = ("def verify(self, node_id):" + chr(10) + "    fm = {}" + chr(10)
          + "    fm['confidence'] = 1" + chr(10)
          + "    if fm['confidence'] < 0.2:" + chr(10)
          + "        self._move_layer(node_id, 'contextual')" + chr(10)
          + "    return fm")
_S_NEW = ("def verify(self, node_id):" + chr(10) + "    fm = {}" + chr(10)
          + "    fm['confidence'] = 1" + chr(10)
          + "    if fm['confidence'] < 0.2:" + chr(10) + "        _land_fm()" + chr(10)
          + "    return fm")
_ok_e, _det_e = GK.assert_enumeration_complete(
    _discover,
    [("应命中·降级分支改了 fm 却不落盘", _S_OLD, True, "a.py"),
     ("不应命中·降级分支过了落盘尾", _S_NEW, False, "b.py"),
     ("不应命中·无 fm 变更的无关函数", "def other():" + chr(10) + "    return 1",
      False, "c.py")])
_check("E05 骨架①分支级枚举完备性（应命中/不应命中两侧）", _ok_e, _det_e)

print("== 骨架② / 变异 ==")
_NL = "\r\n" if b"\r\n" in open(os.path.join(_REPO, "md_cg", "mdcg.py"),
                                   "rb").read()[:8192] else "\n"


def _j(*lines):
    return _NL.join(lines)


_REVERT = (_j("            # #410：**先落盘本轮 fm，再搬层**——_move_layer 读到的就是这份新 fm，",
              "            # 搬过去的内容与回执同源（顺序依据见交付汇报）。",
              "            _land_fm()"),
           "            pass  # 变异/回退：降级轮不落盘（回到修前）")
_MUTATIONS = (
    ("M1 回缺陷：降级轮不落盘（只搬层）", "md_cg/mdcg.py", (_REVERT,),
     # 注：A01/A02（回执==盘面）在 M1 下**反而绿**——回执已改为盘面回读，两边都是旧值；
     # 真正打「本轮丢失」的是 A03（状态矛盾）/A04（证据丢）/A08（本轮值未落盘）。
     ("A03", "A04", "A08", "E03", "K05")),
    # M2 取**过度方向**：降级分支重复落盘（不该多写一次）——由 K05 抓
    ("M2 过度：降级分支重复落盘", "md_cg/mdcg.py",
     ((_j("            _land_fm()", "            demoted = self._move_layer("),
       _j("            _land_fm()", "            _land_fm()  # 变异：重复落盘",
          "            demoted = self._move_layer(")),),
     ("K05",)),
    ("M3 单点被拆：非降级分支不再过落盘尾", "md_cg/mdcg.py",
     (("            _land_fm()      # #410：与非降级轮**同一条落盘尾**（单点）",
       "            pass  # 变异：非降级轮不走单点"),),
     ("A03", "A04", "A05", "A08", "K01", "K04", "K05")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss410_mut_")
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
                         "md_cg.test_issue410_verify_demote_write"],
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
        for desc, rel, pairs, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = open(p, encoding="utf-8", newline="").read()
            if any(t.count(o) != 1 for o, _n in pairs):
                bad.append("%s 锚点命中 %s" % (desc, [t.count(o) for o, _n in pairs]))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            for o, n in pairs:
                t = t.replace(o, n, 1)
            open(p, "w", encoding="utf-8", newline="").write(t)
            for r, dd, ff in os.walk(tree):
                if os.path.basename(r) == "__pycache__":
                    shutil.rmtree(r, ignore_errors=True)
            rc2, reds2, _o2 = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s 红项=%d 指定命中=%d/%d" % (desc, len(reds2),
                                                           len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s 实际=%s 期望=%s rc=%d" % (desc, hit, sorted(exp), rc2))
                for r in reds2[:6]:
                    print("        FAIL " + r)
        # ⚠ 骨架②内部按目标文件行尾折算 ⇒ 这里必须传 **LF** 锚点
        # （传 CRLF 会被再折一次成 \r\r\n，锚点命中 0 次）。
        ok_r, det_r = GK.assert_revert_reddens(
            _mirror_build,
            [("md_cg/mdcg.py", _REVERT[0].replace("\r\n", "\n"),
              _REVERT[1].replace("\r\n", "\n"))],
            _run_in, ("A03", "A04", "A08", "E03", "K05"), "md_cg/mdcg.py")
        print("  骨架②回退即红：%s %s" % ("OK" if ok_r else "MISMATCH",
                                          json.dumps(det_r, ensure_ascii=False)[:200]))
        if not ok_r:
            bad.append("骨架②未按预期转红")
        print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


shutil.rmtree(_TMP, ignore_errors=True)
print("")
print("issue #410 结果：%s" % ("全部通过" if not FAILS else "%d 失败" % len(FAILS)))


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
