# -*- coding: utf-8 -*-
# 功能名：doc 密级判据面必须是「摄取根 + path」拼回的完整路径（issue #452）
# 生效条件：python -X utf8 -m md_cg.test_issue452_sensitive_ingest_root [--mutate]；被测面=md_cg/refindex.py 的 add_items 判据面（_sens_judge_path）与 docindex.sensitivity_for 入参契约
# 子功能：A 组=摄取根即敏感目录时 record/internal 写者 fail-closed（dir 两形状 + file 腿，issue 未测项）；B 组=record/private 写者三形状同判 private + 显式 sensitivity 覆盖仍生效；C 组=internal 身份读不回 private 节点正文；K 组=反向腿（无提示目录不误收紧）+ 判据直调三写法
# 执行：--mutate 时把判据面改回相对路径（即 #452 修前形态），守卫必须转红
# 验证方式：全部 PASS 即通过；--mutate 下变异的「指定命中」须与预期一致
# 不适用条件：不覆盖 code_ref 链（code 节点不经 sensitivity_for 判级）；不覆盖 logref 真源判（write_session 显式传 override）；不测 search 摘要面（可读性证据取 cg.get 节点正文）
"""issue #452 守卫：docindex/refindex 摄取根本身是敏感目录时不得绕过密级判定。

病象（修前）：`add_items` 的判据只看 `it["path"]`（相对被摄取根）。当
`cg(op=ingest, action=dir, path=<…>/private)` 时 item path 只剩 `hr_archive.md`，
`private` 这一段正是摄取根自身，被 relpath 剥掉 ⇒ 提示永远命中不了：同一份
文档、同一个写者，从父目录摄取是 private/fail-closed，从该目录本身摄取却
落 internal，且 internal 身份经 `cg.get` 读回含敏感词的摘要正文（P1）。

修复（判据面单点，不改存储路径）：`doc_ref.path` ↔ `doc_ref.root` 的 join 是
回读契约、node_id 哈希的也是相对路径，都不许动；判据入参单独换成
`_sens_judge_path(root, path)` = 拼根后的绝对路径。故本守卫同时钉：
  ① 三种摄取形状（dir 敏感根本身 / dir 父目录 / file 单文件）判级一致；
  ② internal 档身份写不进、也读不回（fail-closed 两面）；
  ③ 反向腿：无提示路径仍 internal（不得全收紧成 private）；
  ④ 显式 sensitivity 覆盖仍优先（判据面变化不破 override 语义）。
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
_TMP = tempfile.mkdtemp(prefix="iss452_")
os.environ.update({"MDCG_ROOT": _TMP + "/brainroot", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore", "MDCG_EXPORT_ROOT": _TMP,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
                   "MDCG_INGEST_ROOT": _TMP})   # issue 前提：摄取目录在白名单内
from md_cg.mdcos import MdCGSecure  # noqa: E402
from md_cg.security import Principal  # noqa: E402
from md_cg import docindex  # noqa: E402
from md_cg import mcp_server as _ms  # noqa: E402

FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


def _mk(tag, clearance="internal"):
    return MdCGSecure(_TMP + "/brain_" + tag,
                      principal=Principal(role="record", clearance=clearance,
                                          can_write=True), autoflush=1)


def _ingest(cg, args):
    try:
        return _ms._dispatch(cg, "cg", dict({"op": "ingest"}, **args))
    except Exception as e:                      # noqa: BLE001
        return {"_exc": type(e).__name__ + ":" + str(e)[:120]}


def _doc_sens(cg):
    """读回库内全部 doc 节点的 frontmatter 密级（读不了记 READ-DENIED）。"""
    out = {}
    for nid in (cg.index.get("nodes") or {}):
        try:
            fm = (cg.get(nid) or {}).get("frontmatter") or {}
        except Exception:                       # noqa: BLE001
            fm = {"sensitivity": "READ-DENIED"}
        if "doc" in (fm.get("tags") or []):
            out[nid] = fm.get("sensitivity")
    return out


_HR = """# 一、背景

本文件属于人事档案，包含员工姓名、薪酬与健康状况等不应扩散的信息。
人事档案由人事部专人保管，任何形式的复制、转发与摘录都必须事先报备，
违规扩散将按保密制度追责。

## 保管要求

档案中的薪酬数据为公司机密口径，健康状况信息涉及员工个人隐私，
两者均不得进入公开检索通道。借阅需两级审批并全程留痕，离职人员
档案封存十年后方可按制度销毁。
"""

_NOTE = """# 一、公开说明

本目录是无密级提示路径下的普通文档，用于反向腿：判据面收紧后
它必须仍然是 internal，不得把所有文档都误判成 private。

## 使用指引

任何人都可以检索本说明，作为「不误收紧」的对照样本存在。
"""

# 语料：corp/ 下只有 private/（隔离 A2/B2 的遍历顺序不确定性）；open_docs/ 无任何提示段。
_corp = os.path.join(_TMP, "corp")
_priv = os.path.join(_corp, "private")
os.makedirs(_priv)
with open(os.path.join(_priv, "hr_archive.md"), "w", encoding="utf-8") as f:
    f.write(_HR)
_open_dir = os.path.join(_TMP, "open_docs")
os.makedirs(_open_dir)
with open(os.path.join(_open_dir, "notes.md"), "w", encoding="utf-8") as f:
    f.write(_NOTE)

print("== K 组：判据直调（纯函数面锚定，三写法）==")
_k0a = docindex.sensitivity_for("hr_archive.md")
_k0b = docindex.sensitivity_for("private/hr_archive.md")
_k0c = docindex.sensitivity_for(os.path.join(_priv, "hr_archive.md"))
_check("K0a 裸文件名（无段可命中）→ internal", _k0a[0] == "internal", _k0a)
_check("K0b 相对含提示段 → private", _k0b[0] == "private", _k0b)
_check("K0c 绝对路径（判据面口径）→ private", _k0c[0] == "private", _k0c)

print("== A 组：record/internal 写者，摄取根即敏感目录 → fail-closed ==")
_cgA1 = _mk("A1")
_rA1 = _ingest(_cgA1, {"action": "dir", "path": _priv})
_check("A1 dir 摄取 private 目录本身 → AccessDenied（写入敏感度 private）",
       "AccessDenied" in str(_rA1.get("_exc")), _rA1)
_check("A1 零节点落盘（不半写）", not _doc_sens(_cgA1), _doc_sens(_cgA1))
_cgA1.close()

_cgA2 = _mk("A2")
_rA2 = _ingest(_cgA2, {"action": "dir", "path": _corp})
_check("A2 dir 摄取父目录 → 同样 AccessDenied（同一文档不因 path 写法放松）",
       "AccessDenied" in str(_rA2.get("_exc")), _rA2)
_cgA2.close()

_cgA3 = _mk("A3")
_rA3 = _ingest(_cgA3, {"action": "file",
                       "path": os.path.join(_priv, "hr_archive.md")})
_check("A3 file 单文件摄取（issue 未测腿）→ 同样 AccessDenied",
       "AccessDenied" in str(_rA3.get("_exc")), _rA3)
_check("A3 零节点落盘", not _doc_sens(_cgA3), _doc_sens(_cgA3))
_cgA3.close()

print("== B 组：record/private 写者，三种摄取形状同判 private ==")
_cgB1 = _mk("B1", clearance="private")
_rB1 = _ingest(_cgB1, {"action": "dir", "path": _priv})
_sensB1 = _doc_sens(_cgB1)
_check("B1 dir(敏感根本身) → 全部节点 private",
       bool(_sensB1) and set(_sensB1.values()) == {"private"}, _sensB1)
_cgB1.close()                      # C 组以低权身份重开同一库，先落盘关句柄

_cgB2 = _mk("B2", clearance="private")
_rB2 = _ingest(_cgB2, {"action": "dir", "path": _corp})
_sensB2 = _doc_sens(_cgB2)
_check("B2 dir(父目录) → 同一物理文件判级与 B1 一致（private）",
       bool(_sensB2) and set(_sensB2.values()) == {"private"}, _sensB2)
_cgB2.close()

_cgB3 = _mk("B3", clearance="private")
_rB3 = _ingest(_cgB3, {"action": "file",
                       "path": os.path.join(_priv, "hr_archive.md")})
_sensB3 = _doc_sens(_cgB3)
_check("B3 file 腿 → 与 B1/B2 同判 private（三形状一致）",
       bool(_sensB3) and set(_sensB3.values()) == {"private"}, _sensB3)
_cgB3.close()

_cgB4 = _mk("B4", clearance="internal")
_rB4 = _ingest(_cgB4, {"action": "dir", "path": _priv, "sensitivity": "public"})
_sensB4 = _doc_sens(_cgB4)
_check("B4 显式 sensitivity=public 覆盖仍优先（判据面只补默认档）",
       _rB4.get("ok") and set(_sensB4.values()) == {"public"},
       (str(_rB4)[:120], _sensB4))
_cgB4.close()

print("== C 组：internal 身份读不回 private 节点正文 ==")
_cgC = MdCGSecure(_TMP + "/brain_B1",
                  principal=Principal(role="record", clearance="internal",
                                      can_write=True), autoflush=1)
_leak = None
for nid in (_cgC.index.get("nodes") or {}):
    try:
        body = str(_cgC.get(nid) or {})
    except Exception as e:                      # noqa: BLE001
        body = "EXC:" + type(e).__name__
    if any(w in body for w in ("薪酬", "健康状况", "人事档案")):
        _leak = nid
        break
_check("C1 internal 身份 get 不到敏感正文（读面 fail-closed）",
       _leak is None, "泄漏节点=" + str(_leak))
_cgC.close()

print("== K 组：反向腿（无提示目录不得误收紧）==")
_cgK = _mk("K")
_rK = _ingest(_cgK, {"action": "dir", "path": _open_dir})
_sensK = _doc_sens(_cgK)
_check("K1 无提示路径照常 internal（不把全部文档收紧成 private）",
       _rK.get("ok") and bool(_sensK)
       and set(_sensK.values()) == {"internal"},
       (str(_rK)[:120], _sensK))
_cgK.close()

shutil.rmtree(_TMP, ignore_errors=True)

print("")
if FAILS:
    print("issue #452 结果：%d 失败" % len(FAILS))
else:
    print("issue #452 结果：全部通过")

# ------------------------------------------------------------------ 定点变异
# 锚点取「注释行 + 判据行」两行（在 refindex.py 里唯一）；行尾按目标文件实际 NL 折算。
_MUTATIONS = (
    # 预期红项用「编号 + 首词」的唯一前缀（A1/A3 各有两条子断言：拒写 + 零落盘）；
    # B2 在修前本就判 private（提示段在相对路径里），不转红是正确的对照。
    ("V1 判据面改回相对路径（即 #452 修前：只看 it['path']）",
     "md_cg/refindex.py",
     "            s, _basis = docindex.sensitivity_for(" + chr(10)
     + "                _sens_judge_path(root, it.get(\"path\")), sensitivity)",
     "            s, _basis = docindex.sensitivity_for(it.get(\"path\") or \"\", sensitivity)",
     ("A1 dir", "A1 零", "A3 file", "A3 零", "B1 dir", "B3 file", "C1")),
    ("V2 _sens_judge_path 丢根（只返回 rel，判据面退化）",
     "md_cg/refindex.py",
     "        return os.path.abspath(os.path.join(str(root or \"\"), str(rel or \"\")))",
     "        return str(rel or \"\")",
     ("A1 dir", "A1 零", "A3 file", "A3 零", "B1 dir", "B3 file", "C1")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss452_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml",
                                              "package.json")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    import subprocess
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["MDCG_INGEST_ROOT"] = ""               # 由被测脚本自身重设为它的 _TMP
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue452_sensitive_ingest_root"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1200)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "FAIL " in ln]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：把判据改回改动前形态，守卫必须转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-25:]))
        ok, bad = 0, []
        for desc, rel, old, new, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            raw = open(p, "rb").read()
            # 锚点按 \n 构造，目标文件可能是 CRLF——按文件实际行尾折算后再比对。
            _nl = "\r\n" if b"\r\n" in raw[:8192] else "\n"
            t = raw.decode("utf-8")
            old = old.replace("\n", _nl)
            new = new.replace("\n", _nl)
            if t.count(old) != 1:
                bad.append("%s —— 锚点命中 %d 次" % (desc, t.count(old)))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            open(p, "w", encoding="utf-8", newline="").write(t.replace(old, new, 1))
            rc2, reds2, out2 = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = [r for r in reds2 if r.startswith(exp)]
            if rc2 != 0 and len(hit) == len(exp):
                ok += 1
                print("  OK   %s  红项=%d 指定命中=%d/%d"
                      % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s  红项=%d 指定命中=%d/%d rc=%d"
                      % (desc, len(reds2), len(hit), len(exp), rc2))
                for r in reds2[:8]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    if "--mutate" in sys.argv:
        _mutate()
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
