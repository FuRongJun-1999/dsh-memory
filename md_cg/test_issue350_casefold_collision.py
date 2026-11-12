# -*- coding: utf-8 -*-
# 功能名：node_id 大小写折叠查重——大小写不敏感 FS 上只差大小写的两次写入不得互相顶替（issue #350）
# 生效条件：python -X utf8 -m md_cg.test_issue350_casefold_collision [--mutate]；被测面=md_cg/mdcg.py 的 MdCG.add
# 子功能：A 组=只差大小写的新 id 拒写（anchor 层 / 工具面 self 层）；K 组=同 id 精确覆写照旧放行、新 id 不受影响
# 执行：--mutate 时把查重改回无（即 #350 修前），守卫必须转红
# 验证方式：全部 PASS 即通过；--mutate 下变异的「指定命中」须与预期一致
# 不适用条件：不判 trash/restore 的同名覆盖（报告修复建议 3，未落码）；不判 _scan_nodes 告警（建议 4，未落码）；不判 #322 锁键的 casefold（建议 5）；不覆盖 macOS APFS 实机
"""issue #350 守卫：只差大小写的 node_id 在大小写不敏感 FS 上是同一个文件。

病象（修前）：节点文件名就是 node_id，而「已存在/受保护/原密级」全部按区分
大小写的索引键判断。Windows NTFS / macOS APFS 默认卷上，User_Identity.md 与
user_identity.md 是同一个文件：写入 user_identity 被当成新节点，保护闸/冻结副本/
跨层闸/#297 密级继承全部不生效，os.replace 把先写者整份换掉，回执 ok:true，
重启后先写者从库里消失且库根无任何副本。

项目方已在 Windows（受影响平台）实跑报告自带复现：修前「命中缺陷 3 / 3」，
修后两条碰撞路径都 ValueError 拒绝。
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
_TMP = tempfile.mkdtemp(prefix="iss350_")
os.environ.update({"MDCG_ROOT": _TMP + "/brainroot", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore", "MDCG_EXPORT_ROOT": _TMP,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})
from md_cg.mdcos import MdCGSecure  # noqa: E402
from md_cg.security import Principal  # noqa: E402
from md_cg import mcp_server as _ms, protect  # noqa: E402

_SECRET = "OWNPRIV_A 银行卡密码 4242"
FAILS = []


def _ccg(tag, do):
    return ("# 功能名：%s\n# 生效条件：%s 相关会话\n# 子功能：%s 记录\n# 执行：%s\n"
            "# 验证方式：用户自述\n# 不适用条件：与 %s 无关的话题"
            % (tag, tag, tag, do, tag))


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


_cg = MdCGSecure(_TMP + "/brainroot",
                 principal=Principal(role="designer", clearance="private",
                                     can_write=True, can_admin=True), autoflush=1)

def _call(cg, name, args):
    """MCP 分派面的薄封装：异常折成 {'_exc': ...}，便于断言。"""
    try:
        return _ms._dispatch(cg, name, args)
    except Exception as e:                      # noqa: BLE001
        return {"_exc": type(e).__name__ + ":" + str(e)[:110]}


print("== A 组：只差大小写的新 id 拒写 ==")
_cg.add("User_Identity", _ccg("身份锚", "我对花生严重过敏"),
        layer="anchor", importance=0.9)
_check("A1 前提：anchor 节点 User_Identity 为不可篡改层",
       protect.is_immutable(_cg, "User_Identity")[0], "")

_a2 = _call_ok = None
try:
    _cg.add("User_Identity", _ccg("随手记", "今天天气不错"), layer="anchor")
    _a2 = "放行"
except Exception as e:                                      # noqa: BLE001
    _a2 = type(e).__name__
_check("A2 同 id 覆写 anchor → 拒（ProtectionError，既有面不退化）",
       _a2 == "ProtectionError", _a2)

try:
    _cg.add("user_identity", _ccg("随手记", "今天天气不错"), layer="anchor")
    _a3 = "放行"
except ValueError as e:
    _a3 = "ValueError:" + str(e)[:60]
except Exception as e:                                      # noqa: BLE001
    _a3 = type(e).__name__
_check("A3 只差大小写 user_identity → 拒（ValueError，#350 收口）",
       str(_a3).startswith("ValueError"), _a3)

print("== A 组（续）：工具面 self 层 ==")
_t1 = _call(_cg, "cg", {"op": "write", "node_id": "User_Profile",
                        "content": _ccg("用户画像", "生产库端口 7001"),
                        "layer": "self", "content_kind": "text",
                        "verification_basis": "other"})
_check("A4 工具面写 User_Profile → 成功",
       _t1.get("ok") is True and _t1.get("committed") is True, _t1)

_t2 = _call(_cg, "cg", {"op": "write", "node_id": "user_profile",
                        "content": _ccg("口头禅", "用户喜欢说好的"),
                        "layer": "self", "content_kind": "text",
                        "verification_basis": "other"})
_check("A5 工具面写 user_profile（只差大小写）→ 拒",
       "AccessDenied" in str(_t2) or "ValueError" in str(_t2)
       or "只差大小写" in str(_t2), str(_t2)[:160])

print("== K 组：非恒真对照 ==")
_g = _cg.get("User_Profile") or {}
_check("K1 User_Profile 正文未被顶替（仍是 7001）",
       "7001" in (_g.get("content") or ""), (_g.get("content") or "")[:40])

_k2a = _call(_cg, "cg", {"op": "write", "node_id": "Tag_Note",
                         "content": _ccg("标签", "初版标签"), "layer": "contextual",
                         "content_kind": "text", "verification_basis": "other"})
_t3 = _call(_cg, "cg", {"op": "write", "node_id": "Tag_Note",
                        "content": _ccg("标签", "改版标签"), "layer": "contextual",
                        "content_kind": "text",
                        "verification_basis": "other"})
_check("K2 **同 id 精确**覆写（contextual 层）→ 不被大小写闸拦（口径：只拦新 id 的碰撞；"
       "confirm 档下它进审核队列是既有自治语义，与本闸无关）",
       "AccessDenied" not in str(_k2a) and "只差大小写" not in str(_k2a)
       and "AccessDenied" not in str(_t3) and "只差大小写" not in str(_t3),
       str(_t3)[:160])

_t4 = _call(_cg, "cg", {"op": "write", "node_id": "Brand_New_Node",
                        "content": _ccg("新节点", "全新内容"),
                        "layer": "self", "content_kind": "text",
                        "verification_basis": "other"})
_check("K3 全新 id → 照常放行（不误伤正常新建）",
       _t4.get("ok") is True and _t4.get("committed") is True, str(_t4)[:140])

print("== E 组：单点 ==")
from md_cg import mdcg as _mdcg  # noqa: E402
_src = __import__("inspect").getsource(_mdcg.MdCG.add)
_check("E1 MdCG.add 体内有大小写折叠查重（casefold）",
       "casefold" in _src, [l for l in _src.splitlines()
                            if "casefold" in l][:2])

_cg.close()
shutil.rmtree(_TMP, ignore_errors=True)

print("")
if FAILS:
    print("issue #350 结果：%d 失败" % len(FAILS))
else:
    print("issue #350 结果：全部通过")

# ------------------------------------------------------------------ 定点变异
_MUTATIONS = (
    ("V1 摘掉大小写折叠查重（回到 #350 修前：后写者整份顶替）",
     "md_cg/mdcg.py",
     "        if (node_id not in _nodes350 and isinstance(node_id, str) and node_id):",
     "        if False:",
     ("A3",)),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss350_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml", "package.json")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    import subprocess
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue350_casefold_collision"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
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
            t = open(p, encoding="utf-8", newline="").read()
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