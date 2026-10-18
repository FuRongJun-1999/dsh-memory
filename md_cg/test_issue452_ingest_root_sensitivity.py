# -*- coding: utf-8 -*-
# 功能名：摄取根自身是敏感目录时，来源密级判据不得被相对路径抹掉——issue #452
# 生效条件：python -X utf8 -m md_cg.test_issue452_ingest_root_sensitivity [--mutate]；被测面＝md_cg/sources.py::source_sensitivity/add_items_with_source_sensitivity 与 ingest_file/ingest_dir 的密级取值点，判据本体仍是 md_cg/docindex.py::sensitivity_for
# 子功能：A 组＝同一份文档以 path=<base>/private 与 path=<base> 两种形状摄取，密级必须一致（都 private）且 internal 身份写不进；B 组＝非恒真反向腿（路径不含提示仍 internal，不把所有文档收紧成 private）；C 组＝判据单点与输入面（sensitivity_for 只有一份实现、取值点喂的是绝对路径）
# 执行：--mutate 时在镜像树里回退「按来源文件继承密级」与「判据入参改回相对路径」两处，守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；默认模式另做源码锚点自检（关键判据字面量缺失 ⇒ exit 2，fail-closed）；--mutate 模式红项集合须与预期逐项相符
# 不适用条件：不判 code_ref 链（代码节点不走密级提示判据）；不判 item["path"]/doc_ref.path 的**取值口径**是否改成绝对路径（换 id 会动存量幂等，属单独立项）；不判 sensitivity_for 的提示词表本身（PRIVATE_HINTS 内容不在本条）；不判白名单外的摄取（那是 #425/#351 的面）
"""issue #452 守卫：来源密级判据的**输入面**必须包含摄取根自身的路径段。

病象（修前）：`docindex.index_dir` 产出的 item["path"] 是**相对被摄取根**的；
`refindex.add_items` 用 `docindex.sensitivity_for(it["path"])` 判密级。当摄取根
**本身就是敏感目录**（`ingest(path=<…>/private)`）时，`private` 这一段正是 root
自身，被 relpath 抹掉 ⇒ 提示命中不了，敏感文档以 internal 落库，internal 档身份
读得回其正文摘要。同一内容换成父目录摄取则正确判 private 并 fail-closed。

修法（条件层）：判据仍只有 `docindex.sensitivity_for` 一处，但喂给它的是**源文件
的绝对路径**——绝对路径的段集合 ⊇ 相对路径的段集合，只会更严、不会更松。
`item["path"]` 保持相对 root（节点 id / doc_ref 稳定标识不变）。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

for _k in [k for k in os.environ if k.startswith("MDCG_")]:
    del os.environ[_k]

FAILS = []
_T = tempfile.mkdtemp(prefix="iss452_")
BASE = os.path.join(_T, "base")
ROOT = os.path.join(_T, "brain")
os.environ.update(HOME=_T, MDCG_ROOT=ROOT,
                  MDCG_STATE_ROOT=os.path.join(_T, "stateroot"),
                  MDCG_AUX_ROOT=os.path.join(_T, "auxroot"),
                  MDCG_DATA_ROOT=os.path.join(_T, "dataroot"),
                  MDCG_EXPORT_ROOT=_T, MDCG_SUSTAIN="0", MDCG_SLEEP="0",
                  MDCG_INGEST_ROOT=BASE)

from md_cg.mdcos import MdCGSecure           # noqa: E402
from md_cg.security import Principal         # noqa: E402
from md_cg.tokens import role_spec           # noqa: E402
from md_cg import mcp_server as ms           # noqa: E402
from md_cg import docindex, sources          # noqa: E402

DOC = ("# 功能名：一、背景\n# 生效条件：人事档案\n# 子功能：员工资料\n"
       "# 执行：本文件属于人事档案，包含员工姓名、**薪酬**与**健康状况**等不应扩散的信息。\n"
       "# 验证方式：test\n# 不适用条件：无\n\n## 细节\n"
       + "HRMARK1 员工张三年薪 42 万，健康状况详见附件。" * 8)
PLAIN = ("# 功能名：公开说明\n# 生效条件：通用\n# 子功能：无\n# 执行：公开资料，不含敏感信息。\n"
         "# 验证方式：test\n# 不适用条件：无\n\n## 细节\n" + "OPENMARK1 公开内容。" * 20)


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


def P(role, clr):
    s = role_spec(role)
    return Principal(role=role, clearance=clr, can_write=s["can_write"],
                     can_admin=s["can_admin"], layers_allow=s["layers_allow"],
                     ops_allow=s["ops_allow"])


def _fresh():
    for d in ("brain", "stateroot", "auxroot", "dataroot"):
        p = os.path.join(_T, d)
        shutil.rmtree(p, ignore_errors=True)
        os.makedirs(p, exist_ok=True)
    os.makedirs(os.path.join(BASE, "private"), exist_ok=True)
    os.makedirs(os.path.join(BASE, "public"), exist_ok=True)
    with open(os.path.join(BASE, "private", "hr_archive.md"), "w", encoding="utf-8") as f:
        f.write(DOC)
    with open(os.path.join(BASE, "public", "open.md"), "w", encoding="utf-8") as f:
        f.write(PLAIN)


def _try_dir(path):
    cg = MdCGSecure(ROOT, principal=P("record", "internal"), autoflush=1)
    try:
        r = ms._dispatch(cg, "cg", {"op": "ingest", "action": "dir", "path": path})
    except Exception as e:                    # noqa: BLE001
        r = {"_exc": type(e).__name__, "_msg": str(e)[:100]}
    sens, readable = {}, {}
    for nid in list((cg.index.get("nodes") or {})):
        if not nid.startswith("doc_"):
            continue
        n = cg.get(nid) or {}
        ref = (n.get("frontmatter") or {}).get("doc_ref") or {}
        sens[nid] = ((ref.get("path") or ""), (n.get("frontmatter") or {}).get("sensitivity"))
        readable[nid] = "HRMARK1" in (n.get("content") or "")
    cg.close()
    return r, sens, readable


def _hr_landed(sens):
    """落库条目里指向 hr_archive.md 的（相对路径, 密级）——它一个都不该存在。"""
    return [v for v in sens.values() if str(v[0]).endswith("hr_archive.md")]


print("== A 组：同一文档两种摄取形状，密级必须一致且写不进（#452 正题） ==")
_fresh()
_ra, _sa, _reada = _try_dir(os.path.join(BASE, "private"))
print("[A] path=<base>/private -> ok=%s exc=%s | 密级=%s | 同身份读回敏感正文=%s"
      % (_ra.get("ok"), _ra.get("_exc"), _sa, _reada))
_check("A1 摄取根自身带 private 提示 ⇒ 内部身份写不进（fail-closed，修前 ok=True 且落 internal）",
       _ra.get("_exc") == "AccessDenied" and not _sa, _ra)
_check("A2 不得留下任何指向 hr_archive.md 的 doc 节点（修前：internal 且同身份读得回正文）",
       not _hr_landed(_sa) and not any(_reada.values()), (_hr_landed(_sa), _reada))

_fresh()
_rb, _sb, _readb = _try_dir(BASE)
print("[B] path=<base>        -> ok=%s exc=%s | 密级=%s" % (_rb.get("ok"), _rb.get("_exc"), _sb))
_check("A3 父目录摄取同样 fail-closed（两种形状结论一致——修前 A=internal / B=private）",
       _rb.get("_exc") == "AccessDenied" and not _sb, _rb)
_check("A4 两种形状都未把 hr_archive.md 落成 doc 节点（同一文档两种 path 结论一致）",
       not _hr_landed(_sa) and not _hr_landed(_sb), (_hr_landed(_sa), _hr_landed(_sb)))

print("== B 组：非恒真反向腿（不得把所有文档都收紧成 private） ==")
_fresh()
_rp, _sp, _readp = _try_dir(os.path.join(BASE, "public"))
_check("B01 路径不含私有提示 ⇒ 仍落 internal（不误收紧）",
       _rp.get("ok") is True and _sp
       and all(v[1] == "internal" for v in _sp.values()), (_rp.get("ok"), _sp))
_check("B02 反向腿前提：公开文档确实被索引了（不是空扫假绿）",
       len(_sp) > 0, _sp)

print("== D 组：来源声明面继承（#425 修复建议 3：源 frontmatter 的 sensitivity 更严时取更严） ==")
_fresh()
# 把一份 restricted 节点文件**复制到库外**（路径段不含任何私有提示）再摄取：
# 路径判据只会给 internal；来源声明面必须把它拉回 restricted ⇒ internal 身份写不进。
_copy = os.path.join(BASE, "public", "copied_node.md")
with open(_copy, "w", encoding="utf-8") as f:
    f.write("---\nsensitivity: restricted\nlayer: knowledge\n---\n" + DOC)
_rd, _sd, _readd = _try_dir(os.path.join(BASE, "public"))
_check("D01 库外副本带 frontmatter sensitivity: restricted ⇒ 内部身份写不进（修前：落 internal）",
       _rd.get("_exc") == "AccessDenied" and not _hr_landed(_sd),
       (_rd, _hr_landed(_sd)))
os.remove(_copy)
_fresh()
_rp2, _sp2, _readp2 = _try_dir(os.path.join(BASE, "public"))
_check("D02 对照：无 frontmatter 声明的普通外部文档仍按 internal 正常摄取",
       _rp2.get("ok") is True and _sp2
       and all(v[1] == "internal" for v in _sp2.values()), (_rp2.get("ok"), _sp2))

print("== C 组：判据单点与输入面（源码锚点） ==")
_SRC_S = open(os.path.join(_REPO, "md_cg", "sources.py"), encoding="utf-8").read()
_SRC_D = open(os.path.join(_REPO, "md_cg", "docindex.py"), encoding="utf-8").read()
_MISSING = [n for n in ("def source_sensitivity(",
                        "def add_items_with_source_sensitivity(",
                        "source_sensitivity(os.path.join(root, rel), sensitivity)")
            if n not in _SRC_S]
_check("C01 密级取值点是单点（source_sensitivity），按来源文件绝对路径取值", not _MISSING, _MISSING)
_check("C02 判据本体只有一份实现（sensitivity_for 定义唯一）",
       _SRC_D.count("def sensitivity_for(") == 1)
_check("C03 摄取链不再直接以 item['path'] 调 refindex.add_items（两个入口都改经继承单点）",
       _SRC_S.count("refindex.add_items(") == 3          # 三处都在继承单点内部
       and _SRC_S.count("add_items_with_source_sensitivity(") == 3,  # def + 2 入口
       (_SRC_S.count("refindex.add_items("),
        _SRC_S.count("add_items_with_source_sensitivity(")))
_check("C04 item['path'] 仍保持相对 root（不改 id / doc_ref 稳定标识）",
       "rel = os.path.relpath(fp, root).replace" in _SRC_D)

if _MISSING and "--mutate" not in sys.argv:
    print("锚点自检失败：关键判据字面量缺失 %s" % _MISSING)
    shutil.rmtree(_T, ignore_errors=True)
    sys.exit(2)


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
                                  or name in ("README.md", "pyproject.toml")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env.update({"PYTHONPATH": tree, "PYTHONUTF8": "1",
                "PYTHONDONTWRITEBYTECODE": "1"})
    for k in ("MDCG_ROOT", "MDCG_TOKEN", "MDCG_VERIFY_KEY", "MDCG_INGEST_ROOT"):
        env.pop(k, None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue452_ingest_root_sensitivity"],
                        cwd=tree, env=env, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=1200)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


_NL = "\r\n" if b"\r\n" in open(os.path.join(_REPO, "md_cg", "sources.py"),
                                 "rb").read()[:8192] else "\n"


def _j(*lines):
    return _NL.join(lines)


_MUTATIONS = (
    ("M1 回缺陷：判据入参改回相对路径（丢掉摄取根自身的段）", "md_cg/sources.py",
     (_j("    from . import docindex, nodefile",
         "    from .security import SENSITIVITY_ORDER",
         "    s, _basis = docindex.sensitivity_for(path, explicit)"),
      _j("    from . import docindex, nodefile",
         "    from .security import SENSITIVITY_ORDER",
         "    s, _basis = docindex.sensitivity_for(os.path.basename(path), explicit)")),
     ("A1", "A2", "A3", "A4")),
    ("M2 回缺陷：摄取链退回批次级 sensitivity（不按来源文件继承）", "md_cg/sources.py",
     (_j("    if kind != \"doc_ref\" or not items:",
         "        return refindex.add_items(cg, items, kind=kind, root=root, layer=layer,",
         "                                  sensitivity=sensitivity, conflicts=conflicts)"),
      _j("    if True:  # 变异：不按来源文件继承",
         "        return refindex.add_items(cg, items, kind=kind, root=root, layer=layer,",
         "                                  sensitivity=sensitivity, conflicts=conflicts)")),
     ("A1", "A2", "A4", "D01")),
    ("M3 回缺陷：丢掉来源声明面（只按路径判据）", "md_cg/sources.py",
     (_j("    cands = [s]",
         "    try:",
         "        with open(path, encoding=\"utf-8\", errors=\"replace\") as f:"),
      _j("    cands = [s]",
         "    return s  # 变异：丢掉来源声明面",
         "    try:",
         "        with open(path, encoding=\"utf-8\", errors=\"replace\") as f:")),
     ("D01",)),
)


def _mutate():
    print("!! 定点变异：回退两处密级继承，守卫必须按指定项转红")
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print("\n".join(out.splitlines()[-20:]))
            bad.append("镜像基线非绿")
        for desc, rel, (old, new), exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = open(p, encoding="utf-8", newline="").read()
            if t.count(old) != 1:
                bad.append("%s 锚点命中 %d 次" % (desc, t.count(old)))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            open(p, "w", encoding="utf-8", newline="").write(t.replace(old, new, 1))
            for r, _dd, _ff in os.walk(tree):
                if os.path.basename(r) == "__pycache__":
                    shutil.rmtree(r, ignore_errors=True)
            rc2, reds2, _o2 = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s  红项=%d 指定命中=%d/%d"
                      % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s 实际=%s 期望=%s rc=%d"
                      % (desc, hit, sorted(exp), rc2))
                for r in reds2[:8]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


shutil.rmtree(_T, ignore_errors=True)
print("")
print("issue #452 结果：%s" % ("全部通过" if not FAILS else "%d 失败" % len(FAILS)))


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
