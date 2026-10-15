# -*- coding: utf-8 -*-
"""issue #193 返工守卫：比对面扩为「同层 ∨ knowledge」的三面判据。

值守存疑点（PR #316 审阅 #193，2026-10-15）：旧分支 b4d8af8 把层过滤器
无条件扩成「同层 ∨ knowledge」（`e.get("layer") != layer and
e.get("layer") != "knowledge"`）——「指定 contextual 比对」时也纳入
knowledge 节点，可能引入跨层误报；值守要求补「跨层不误报」的阴性判据。

返工实测定形态（改前读数，2026-10-15，临时测量脚本已删）：
  · 旧形态（无条件 ∨ knowledge）在**词面无交集**的不相关 knowledge 在场时
    虽不凭空造 DEFER/REJECT（实测仍 ACCEPT/strength 0），但——
    ① 只读指定层比对被拉动：BLINDSPOT→ACCEPT、comparable 0→1（同层语义
       被跨层改写——值守担心的「误报」在读数面坐实）；
    ② 层外候选与同层候选**同池竞争**相关面前 limit：limit=1 实测同层矛盾
       节点被挤出精比面（with 只剩层外节点）——同层检出回归。
  ⇒ 修法取**显式请求式**（任务 3(a) 的兜底形态＝main 已并入的 256d587
    EXTRA_SCOPE 实现）：扩面仅当 write_scope=True（writepipe / MdCG.add 两个
    写入出口显式传），层外候选另道收集不进相关面/保底面，方向单向
    contextual→knowledge，structural/anchor 不纳入。

三组判据（与 test_issue193_write_scope.py 的 A/K/E 组互补，不重复）：
  G1 缺陷面   #193 漏比场景（同层形态漏报 BLINDSPOT/ACCEPT）写入面必须抓到；
  G2 阴性判据 跨层不误报（值守点名）：不相关 knowledge 不引发冲突读数，
              且对只读面逐位不可见。非空转由 G1 保证——同一扩面机制在
              G1 已实证发生（write_scope=True 时 scope_layers 含 knowledge）；
  G3 防过修   同层比对既有行为零回归，含 limit 压力下的位移阴性
              （b4d8af8 实测失效点②）。

变异两向：M1 回退同层形态 ⇒ G1 红、G2/G3 绿（阴性判据不误伤正确收紧）；
M2 还原 b4d8af8 旧形态 ⇒ G2b/G3c 红（阴性判据与位移判据必须咬得住旧形态）。

用法：python -X utf8 -m md_cg.test_issue193_consistency_knowledge_guard [--mutate]
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_OK = 0
_FAIL = 0


def ok(cond, msg, extra=None):
    global _OK, _FAIL
    if cond:
        _OK += 1
        print("  PASS " + msg)
    else:
        _FAIL += 1
        print("  FAIL " + msg)
        if extra is not None:
            print("       " + repr(extra)[:220])


def ccg(fn, sub, exe, cond="生产环境", na="无"):
    return ("# 功能名：%s\n# 生效条件：%s\n# 子功能：%s\n"
            "# 执行：%s\n# 验证方式：test\n# 不适用条件：%s\n") % (fn, cond, sub, exe, na)


class _Env(object):
    """隔离根：每个用例一套临时 MDCG_* 根，互不污染。"""

    def __init__(self):
        self.d = tempfile.mkdtemp(prefix="iss193g_")
        self.env = {
            "MDCG_ROOT": os.path.join(self.d, "brain"),
            "MDCG_STATE_ROOT": os.path.join(self.d, "state"),
            "MDCG_AUX_ROOT": os.path.join(self.d, "auxstore"),
            "MDCG_DATA_ROOT": os.path.join(self.d, "data"),
            "MDCG_EXPORT_ROOT": self.d,
            "MDCG_TOKEN_FILE": os.path.join(self.d, "auxstore", "tokens.json"),
            "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"}
        self._old = {}

    def __enter__(self):
        for k, v in self.env.items():
            self._old[k] = os.environ.get(k)
            os.environ[k] = v
        from md_cg.mdcos import MdCGOS
        self.cg = MdCGOS(self.env["MDCG_ROOT"], autoflush=1)
        return self

    def __exit__(self, *a):
        try:
            self.cg.close()
        except Exception:  # noqa: BLE001
            pass
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.d, ignore_errors=True)
        return False


# 库存节点：kb_port（knowledge，同条件矛盾取值 6379）／KB1（contextual 同槽
# 矛盾取值 6381）／KB2（被检写入，同槽取值 6380）／其余为词面无交集的不相关节点。
KB = ccg("缓存端口", "连接配置", "Redis 端口是 6379")
KB1 = ccg("缓存端口", "连接配置", "Redis 端口是 6381")
KB2 = ccg("缓存端口", "连接配置", "Redis 端口是 6380")
OTHER_CTX = ccg("日志轮转", "日志策略", "轮转周期 7 天", cond="日志系统")
K_UNREL = ccg("日志保留", "日志策略", "保留 7 天", cond="日志系统")
K_OV = ccg("日志保留", "日志策略", "保留 90 天", cond="日志系统", na="生产环境")
K_U1 = ccg("备份节奏", "备份策略", "每日凌晨全量备份", cond="备份窗口")
K_U2 = ccg("告警阈值", "告警策略", "CPU 告警阈值 90%", cond="监控体系")
K_U3 = ccg("索引重建", "索引策略", "每周日凌晨重建索引", cond="维护窗口")


def _write(cg, nid, content, layer, na=None):
    kw = {}
    if na is not None:
        kw["non_applicable_conditions"] = na
    return cg.add(nid, content, layer=layer, content_kind="text",
                  verification_basis="test", on_conflict="record", **kw)


def _vd(cg, content, layer, write_scope, limit=None, nid="probe"):
    kw = {}
    if limit is not None:
        kw["limit"] = limit
    return cg.check_consistency(content, layer=layer, exclude=nid,
                                auto_flywheel=False, log_write=False,
                                write_scope=write_scope, **kw)


def _withs(r):
    return [c.get("with") for c in (r.get("conflicts") or [])]


def _face(r):
    """读数面（G2b 逐位比对的元组）。"""
    return (r.get("verdict"), r.get("conflict_strength"), r.get("comparable"),
            r.get("scanned"), r.get("kept"), tuple(sorted(_withs(r))))


# ---------------------------------------------------------------- G1 缺陷面
def g1_group():
    print("== G1 缺陷面：#193 漏比场景（同层形态漏报）写入面必须抓到 ==")
    with _Env() as e:
        _write(e.cg, "kb_port", KB, "knowledge")
        # G1a：contextual 层内空——同层形态（只读面）BLINDSPOT，写入面必须 DEFER
        r0 = _vd(e.cg, KB2, "contextual", False)
        ok(r0["verdict"] == "BLINDSPOT",
           "G1a 同层形态对照：只读面漏报 BLINDSPOT（#193 要修的读数，修后只扩写入面）",
           r0["verdict"])
        r1 = _vd(e.cg, KB2, "contextual", True)
        ok(r1["verdict"] == "DEFER",
           "G1a 写入面抓到 knowledge 同条件矛盾取值（DEFER）", r1["verdict"])
        ok(any(c.get("with") == "kb_port" for c in r1.get("conflicts") or []),
           "G1a 冲突条目点名 knowledge 节点 kb_port", _withs(r1))
        # G1b：同层只有一条无关节点——同层形态 ACCEPT（第二种漏报形态）
        _write(e.cg, "ctx_other", OTHER_CTX, "contextual")
        r2 = _vd(e.cg, KB2, "contextual", False)
        ok(r2["verdict"] == "ACCEPT",
           "G1b 同层形态对照：同层仅无关节点时只读面漏报 ACCEPT", r2["verdict"])
        r3 = _vd(e.cg, KB2, "contextual", True)
        ok(r3["verdict"] == "DEFER"
           and any(c.get("with") == "kb_port" for c in r3.get("conflicts") or []),
           "G1b 写入面仍抓到（DEFER 且点名 kb_port）", (r3["verdict"], _withs(r3)))


# ------------------------------------------------- G2 阴性判据（值守点名）
def g2_group():
    print("== G2 阴性判据（值守点名）：跨层不误报 ==")
    # G2a：不相关 knowledge 在场，写入面不得产生冲突读数（非空转：扩面发生
    # 由 G1 同机制实证——write_scope=True 时层外候选确实并入精比面）。
    with _Env() as e:
        _write(e.cg, "k_log", K_UNREL, "knowledge")
        r = _vd(e.cg, KB2, "contextual", True)
        ok(r["verdict"] not in ("DEFER", "REJECT")
           and not (r.get("conflicts") or [])
           and r.get("conflict_strength") == 0.0,
           "G2a 不相关 knowledge 不引发跨层误报（非 DEFER/REJECT、无冲突、强度 0）",
           (r["verdict"], r.get("conflict_strength"), _withs(r)))
    # G2b：不相关 knowledge 对只读面**逐位不可见**（在场/不在场读数完全一致）
    with _Env() as e:
        _write(e.cg, "k_log", K_UNREL, "knowledge")
        a = _face(_vd(e.cg, KB2, "contextual", False))
    with _Env() as e:
        b = _face(_vd(e.cg, KB2, "contextual", False))
    ok(a == b,
       "G2b 只读面逐位不变：不相关 knowledge 在场/不在场读数一致", (a, b))
    # G2c：多条不相关 knowledge 也不产生冲突读数
    with _Env() as e:
        for i, c in enumerate((K_U1, K_U2, K_U3)):
            _write(e.cg, "k_u%d" % i, c, "knowledge")
        r = _vd(e.cg, KB2, "contextual", True)
        ok(r["verdict"] not in ("DEFER", "REJECT")
           and not (r.get("conflicts") or []),
           "G2c 三条不相关 knowledge 仍不引发跨层误报",
           (r["verdict"], _withs(r)))


# ---------------------------------------------------------------- G3 防过修
def g3_group():
    print("== G3 防过修：同层比对既有行为零回归 ==")
    # G3a：同层矛盾照抓——写入面与只读面都只点名同层节点
    with _Env() as e:
        _write(e.cg, "c_conf", KB1, "contextual")
        rw = _vd(e.cg, KB2, "contextual", True)
        rr = _vd(e.cg, KB2, "contextual", False)
        ok(rw["verdict"] == "DEFER" and _withs(rw) == ["c_conf"],
           "G3a 同层矛盾写入面照抓（仍只点名 c_conf）", (rw["verdict"], _withs(rw)))
        ok(rr["verdict"] == "DEFER" and _withs(rr) == ["c_conf"],
           "G3a 同层矛盾只读面照抓", (rr["verdict"], _withs(rr)))
    # G3b：不相关 knowledge 加入不改变同层冲突读数（层外候选既不造冲突、
    # 也不改写同层结果）
    with _Env() as e:
        _write(e.cg, "c_conf", KB1, "contextual")
        _write(e.cg, "k_log", K_UNREL, "knowledge")
        r = _vd(e.cg, KB2, "contextual", True)
        ok(r["verdict"] == "DEFER" and _withs(r) == ["c_conf"],
           "G3b 不相关 knowledge 在场时同层冲突读数不变（仍只点名 c_conf）",
           (r["verdict"], _withs(r)))
    # G3c：limit 压力下的位移阴性——层外候选不得挤占同层矛盾的精比名额。
    # b4d8af8 实测失效点：k_ov 的不适用条件命中被检内容的生效条件词面
    # （sift rank 2），同池竞争下 c_conf 被挤出相关面前 limit ⇒ 同层检出丢失。
    with _Env() as e:
        _write(e.cg, "k_ov", K_OV, "knowledge", na=["生产环境"])
        _write(e.cg, "c_conf", KB1, "contextual")
        rw = _vd(e.cg, KB2, "contextual", True, limit=1)
        ok("c_conf" in _withs(rw),
           "G3c limit=1 写入面仍点名同层矛盾 c_conf（层外候选不挤占同层名额）",
           _withs(rw))
        rr = _vd(e.cg, KB2, "contextual", False, limit=1)
        ok(_withs(rr) == ["c_conf"],
           "G3c limit=1 只读面只点名 c_conf（k_ov 对只读面不可见）", _withs(rr))


def main():
    print("issue #193 返工守卫：扩面三面判据（G1 缺陷／G2 跨层不误报／G3 零回归）")
    g1_group()
    g2_group()
    g3_group()
    print("")
    print("issue #193 返工守卫结果：%d 通过 / %d 失败" % (_OK, _FAIL))
    return 1 if _FAIL else 0


# 锚点全部单行且唯一（跨行锚点在本仓踩 CRLF：表里的 \n 拼不出 \r\n）。
_MUTATIONS = (
    ("M1 回退 main 的同层形态（EXTRA_SCOPE 清空）：#193 漏比必须复发、"
     "阴性判据不得误伤（G1 红、G2/G3 绿）",
     "md_cg/consistency.py",
     'EXTRA_SCOPE = {"contextual": ("knowledge",)}',
     "EXTRA_SCOPE = {}",
     ("G1a", "G1b")),
    ("M2 还原 b4d8af8 旧形态（层过滤器无条件放行 knowledge：无闸、无另道、"
     "层外候选同池竞争）：只读面被拉动（G2b）＋同层名额被挤占（G3c）必须转红",
     "md_cg/consistency.py",
     '        if layer and e.get("layer") != layer:',
     '        if layer and e.get("layer") != layer and e.get("layer") != "knowledge":',
     ("G1a", "G1b", "G2b", "G3c")),
)


def _mirror_build():
    """把仓库源码镜像到临时区（排除 .git 与 __pycache__），供变异跑。"""
    src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dst = tempfile.mkdtemp(prefix="iss193g_mut_")
    for name in ("md_cg", "scripts"):
        shutil.copytree(os.path.join(src, name), os.path.join(dst, name),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc",
                                                       "tmp_*"))
    # 根级模块一并镜像（mcp_server.py 顶部 `from utf8_boot import ensure_utf8`
    # 指向仓库根的 utf8_boot.py；只镜像 md_cg/ 会让镜像基线直接崩、rc≠0 而
    # 红项为 0——静默崩溃会让每条变异都「红项不足」看不出真因）。
    for name in sorted(os.listdir(src)):
        p = os.path.join(src, name)
        if not os.path.isfile(p):
            continue
        if name.endswith(".py") or name in ("README.md", "pyproject.toml",
                                            "package.json"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _reds_in(base):
    import subprocess
    env = dict(os.environ)
    env["PYTHONPATH"] = base
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    p = subprocess.run([sys.executable, "-X", "utf8", "-m",
                        "md_cg.test_issue193_consistency_knowledge_guard"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=base, env=env, timeout=900)
    out = (p.stdout or "") + (p.stderr or "")
    reds = [l.strip() for l in out.splitlines()
            if l.strip().startswith("FAIL ") or l.strip().startswith("ANCHOR-MISS")]
    return p.returncode, reds, out


def _mutate_mode():
    print("!! 定点变异两向自证：回退同层形态 ⇒ G1 红、G2/G3 绿；"
          "还原 b4d8af8 旧形态 ⇒ 阴性判据必须咬住\n")
    base = _mirror_build()
    try:
        rc0, reds0, out0 = _reds_in(base)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）"
              % (rc0, len(reds0)))
        bad = []
        if rc0 != 0 or reds0:
            bad.append("镜像基线非绿")
            for l in (out0 or "").splitlines()[-14:]:
                print("      | " + l)
        for name, rel, old, new, exp in _MUTATIONS:
            p = os.path.join(base, rel)
            with open(p, encoding="utf-8", newline="") as f:
                original = f.read()
            if old not in original:
                print("  ANCHOR-MISS %s —— 锚点在 %s 里找不到" % (name, rel))
                bad.append(name + " ANCHOR-MISS")
                continue
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(original.replace(old, new, 1))
            try:
                rc2, reds2, out2 = _reds_in(base)
            finally:
                with open(p, "w", encoding="utf-8", newline="") as f:
                    f.write(original)
            hit = [r for r in reds2 if any(e in r for e in exp)]
            crashed = "Traceback (most recent call last)" in (out2 or "")
            good = bool(hit) and not crashed
            print("  %s %s  红项=%d 指定命中=%d/%d"
                  % ("OK  " if good else "MISMATCH", name, len(reds2),
                     len(hit), len(exp)))
            for r in reds2[:6]:
                print("        " + r[:140])
            if not good:
                bad.append(name)
                if crashed:
                    print("        ——变异后崩溃——")
                    for l in (out2 or "").splitlines()[-10:]:
                        print("        | " + l)
        print("")
        if bad:
            print("定点变异两向自证：FAIL（%d 条不合格）" % len(bad))
            return 1
        print("定点变异两向自证：%d/%d PASS" % (len(_MUTATIONS), len(_MUTATIONS)))
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--mutate" in sys.argv:
        raise SystemExit(_mutate_mode())
    raise SystemExit(main())
