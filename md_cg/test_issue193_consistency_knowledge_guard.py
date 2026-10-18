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

四组判据（与 test_issue193_write_scope.py 的 A/K/E 组互补，不重复）：
  G1 缺陷面   #193 漏比场景（同层形态漏报 BLINDSPOT/ACCEPT）写入面必须抓到；
  G2 阴性判据 跨层不误报（值守点名）：不相关 knowledge 不引发冲突读数，
              且对只读面逐位不可见。非空转由 G1 保证——同一扩面机制在
              G1 已实证发生（write_scope=True 时 scope_layers 含 knowledge）；
  G3 防过修   同层比对既有行为零回归，含 limit 压力下的位移阴性
              （b4d8af8 实测失效点②）；
  G4 钉现状   值守复核补的「已知缺口」判据（2026-10-15 按值守探针读数对拍
              实测坐实）：**如实钉住当前行为**防意外变化——不是修复面，
              真正修复在 main 256d587d / #316 拆分件，本件零代码变化。
              每条断言旁都标注「已知缺口，建议另立 issue；若未来修复则
              此断言应翻转为反义」。缺口清单（可复现的活文档）：
              G4a 镜像方向漏报：EXTRA_SCOPE 只有 contextual→knowledge 单向，
                   knowledge 侧写入 + 既有 contextual 同条件同槽矛盾 ⇒
                   ACCEPT/comparable=0/scanned=1（双漏报，与 #193 原病象
                   同形）；
              G4b 层外额度截断静默：30 条同条件 knowledge 相关节点 +
                   limit=1（contextual 写入面）⇒ scanned=0/kept=0/
                   truncated=False/hint 无/ACCEPT——层外候选零进入候选面，
                   截断连告警都不给；
              G4c 跨层 discipline 硬冲突面（对抗方另报缺口③）：knowledge
                   层纪律节点 ⇒ contextual 写入面 REJECT/strength 1.0、
                   只读面 BLINDSPOT（同一次写入的两面口径分裂）。

变异两向：M1 回退同层形态 ⇒ G1 红、G2/G3 绿（阴性判据不误伤正确收紧）；
M2 还原 b4d8af8 旧形态 ⇒ G2b/G3c 红（阴性判据与位移判据必须咬得住旧形态）。
G4 是钉现状判据，钉的是**本形态**读数，在变异形态下读数必然漂移（G4c 的
写入面随 M1 回退消失 ⇒ BLINDSPOT；G4b2 对照面的 kept 随 M1 回退 1→0；
G4b 的场景在 M2 旧形态下层外候选进同池 ⇒ scanned/kept 非 0；G4b2 在 M2
下转可观测（truncated）；G4c 只读面被 M2 拉动 ⇒ REJECT）——这不是守卫
失效，恰是新旧形态读数差异的佐证。为保 M1/M2 红项读数与本件改前逐位一致
（本件定位＝零代码变化的回归门，变异自证的对象是 G1-G3 的修复面），变异跑
按 _MUTATIONS 各条的 skip 清单跳过对应 G4 判据（打印 SKIP 行，不静默）；
plain 跑与未变异镜像基线**全量执行** G4。

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

# G4（钉现状）用：被检内容取自由正文（无 CCG 条件行）——缺口①②的值守探针
# 形态都以 no_terms 被检触发（不扩面 / 不进候选面的机制根源）；G4c 用 ccg 形态
# （纪律命中看正文子串，与条件声明无关）。
FREE2 = "Redis 端口是 6380"
K_FREE = "日志归档周期七天"   # knowledge 层无条件声明节点（work_wip 类，
                              # 不受六要素闸约束；comparable=0 的对照源）
K_DISC = ccg("端口纪律", "写入纪律", "以既有取值为准",
             cond="生产环境", na="禁止 Redis 端口是 6380")


def _pin_skipped(which):
    """变异跑中按 _MUTATIONS 的 skip 清单跳过的钉现状判据（plain 跑不跳）。"""
    skips = {x for x in os.environ.get("ISS193G_SKIP_PINS", "").split(",") if x}
    return which in skips


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


# ------------------------------------------------------- G4 钉现状（缺口）
def g4_group():
    """已知缺口「钉现状」判据（值守复核 2026-10-15 补）。

    本组**不断言正确行为**——如实钉住当前读数，作为回归门防意外变化，并当
    「缺口可复现」的活文档。三条缺口均建议另立 issue（不在本件修：本件定位
    零代码变化的回归门，consistency.py 一字未动；修复面归 #316 拆分件）。
    若未来修复（镜像方向入 EXTRA_SCOPE / 层外候选计入 scanned 与告警面 /
    跨层纪律面统一），对应断言**应翻转为反义**——翻转时同步删去本组注释里
    的「已知缺口」标注并归档 issue。
    """
    print("== G4 钉现状：已知缺口如实读数（建议另立 issue；修复后应翻转） ==")
    # G4a 镜像方向漏报：EXTRA_SCOPE 单向（contextual→knowledge），反向不覆盖。
    # 已知缺口（镜像方向）：knowledge 侧写入 + 既有 contextual 同条件同槽
    # 矛盾（c_conf 取值 6381，被检 6380）⇒ 写入面仍 ACCEPT/comparable=0/
    # scanned=1（scanned=1 是 knowledge 层那条无条件对照节点；矛盾节点在
    # contextual 层，EXTRA_SCOPE 无 knowledge 键 ⇒ 层外跳过）——双漏报：
    # 只读面与写入面读数逐位一致地漏（与 #193 原病象同形，方向相反）。
    # 本守卫先钉住现状防意外变化，若未来补 knowledge→contextual 方向，
    # 此断言应翻转为反义（写入面应抓到 c_conf ⇒ DEFER）。
    if _pin_skipped("G4a"):
        print("  SKIP G4a（变异跑：钉现状判据不计入变异读数，见模块 docstring）")
    else:
        with _Env() as e:
            _write(e.cg, "c_conf", KB1, "contextual")
            e.cg.add("k_free", K_FREE, layer="knowledge",
                     content_kind="work_wip", verification_basis="test",
                     on_conflict="record")
            rw = _vd(e.cg, FREE2, "knowledge", True)
            ok(rw["verdict"] == "ACCEPT"
               and rw.get("comparable") == 0 and rw.get("scanned") == 1
               and not (rw.get("conflicts") or [])
               and rw.get("conflict_strength") == 0.0,
               "G4a 镜像方向漏报现状：knowledge 写入面对 contextual 同条件"
               "同槽矛盾读数 ACCEPT/comparable=0/scanned=1（已知缺口，建议"
               "另立 issue；若补反向扩面应翻转）",
               (rw["verdict"], rw.get("comparable"), rw.get("scanned"),
                _withs(rw)))
            rr = _vd(e.cg, FREE2, "knowledge", False)
            ok(_face(rr) == _face(rw),
               "G4a 双漏报同形：只读面与写入面读数逐位一致（都漏 c_conf）",
               (_face(rr), _face(rw)))
    # G4b 层外额度截断静默：被检未声明条件（no_terms）时不扩面（extra_layers
    # 恒空），30 条词面高度相关的 knowledge 同条件同槽候选**零进入**候选面
    # ⇒ scanned=0/kept=0/truncated=False/hint 无/ACCEPT——截断连告警都不给
    # （对照组见下：被检带条件时 30 条层外候选按 limit 静默砍到 1 条，同样
    # 无任何告警读数）。已知缺口（层外额度静默）：建议另立 issue；若未来把
    # 层外候选计入 scanned/告警面（或 no_terms 也纳入扩面），此断言应翻转
    # 为反义（scanned 应计入层外候选、截断应可观测）。
    if _pin_skipped("G4b"):
        print("  SKIP G4b（变异跑：钉现状判据不计入变异读数，见模块 docstring）")
    else:
        with _Env() as e:
            for i in range(30):
                _write(e.cg, "k_rel%02d" % i,
                       ccg("缓存端口", "连接配置",
                           "Redis 端口取值 %d" % (6400 + i)), "knowledge")
            r = _vd(e.cg, FREE2, "contextual", True, limit=1)
            ok(r["verdict"] == "ACCEPT"
               and r.get("comparable") == 0 and r.get("scanned") == 0
               and r.get("kept") == 0 and r.get("truncated") is False
               and "hint" not in r and not (r.get("conflicts") or []),
               "G4b 层外额度静默现状：30 条同条件 knowledge 相关节点 + "
               "limit=1 ⇒ scanned=0/kept=0/truncated=False/hint 无/ACCEPT"
               "（已知缺口，建议另立 issue；修复后应翻转）",
               (r["verdict"], r.get("comparable"), r.get("scanned"),
                r.get("kept"), r.get("truncated"), r.get("hint")))
    # G4b2（G4b 的对照面，同缺口）：被检带条件（扩面激活）时层外候选进
    # extra_cand 按 limit 静默砍到 1 条——kept=1、truncated 仍 False、hint
    # 仍无，30 条相关层外候选只剩 1 条进精比面且无任何截断告警。读数依赖
    # EXTRA_SCOPE 激活（M1 清空即 kept 1→0）与另道收集（M2 同池即转可观测），
    # 两向变异跑均跳过。若未来把层外候选计入告警面，此断言应翻转。
    if _pin_skipped("G4b2"):
        print("  SKIP G4b2（变异跑：钉现状判据不计入变异读数，见模块 docstring）")
    else:
        with _Env() as e:
            for i in range(30):
                _write(e.cg, "k_rel%02d" % i,
                       ccg("缓存端口", "连接配置",
                           "Redis 端口取值 %d" % (6400 + i)), "knowledge")
            r2 = _vd(e.cg, ccg("缓存端口", "连接配置", FREE2),
                     "contextual", True, limit=1)
            ok(r2.get("kept") == 1 and r2.get("scanned") == 0
               and r2.get("truncated") is False and "hint" not in r2,
               "G4b2 对照：扩面激活时 30 条层外候选静默砍到 1 条（kept=1、"
               "truncated=False、hint 无——额度截断在层外面不可观测）",
               (r2.get("kept"), r2.get("scanned"), r2.get("truncated"),
                r2.get("hint")))
    # G4c 跨层 discipline 硬冲突面（对抗方另报缺口③）：knowledge 层纪律节点
    # （id 前缀 discipline_，negative.reject 命中被检正文）⇒ contextual 写入
    # 面 REJECT/strength 1.0，**只读面 BLINDSPOT**——同一次判定的两面口径
    # 分裂（写入面抓跨层纪律、只读面盲）。已知缺口（跨层纪律面不统一）：
    # 建议另立 issue；若未来统一跨层纪律面（或只读面同样可见），此断言应
    # 翻转为反义（两面应同为 REJECT）。
    if _pin_skipped("G4c"):
        print("  SKIP G4c（变异跑：钉现状判据不计入变异读数，见模块 docstring）")
    else:
        with _Env() as e:
            _write(e.cg, "discipline_port", K_DISC, "knowledge")
            rw = _vd(e.cg, ccg("缓存端口", "连接配置", FREE2),
                     "contextual", True)
            ok(rw["verdict"] == "REJECT" and rw.get("conflict_strength") == 1.0
               and any(c.get("type") == "discipline"
                       and c.get("with") == "discipline_port"
                       and c.get("with_layer") == "knowledge"
                       for c in rw.get("conflicts") or []),
               "G4c 跨层纪律写入面现状：REJECT/strength 1.0、条目点名"
               " knowledge 层纪律节点",
               (rw["verdict"], rw.get("conflict_strength"), _withs(rw)))
            rr = _vd(e.cg, ccg("缓存端口", "连接配置", FREE2),
                     "contextual", False)
            ok(rr["verdict"] == "BLINDSPOT" and not (rr.get("conflicts") or []),
               "G4c 只读面现状：同一纪律节点对只读面不可见（BLINDSPOT，"
               "两面口径分裂——已知缺口，建议另立 issue；统一后应翻转）",
               (rr["verdict"], _withs(rr)))


def main():
    print("issue #193 返工守卫：扩面四面判据（G1 缺陷／G2 跨层不误报／"
          "G3 零回归／G4 钉现状）")
    g1_group()
    g2_group()
    g3_group()
    g4_group()
    print("")
    print("issue #193 返工守卫结果：%d 通过 / %d 失败" % (_OK, _FAIL))
    return 1 if _FAIL else 0


# 锚点全部单行且唯一（跨行锚点在本仓踩 CRLF：表里的 \n 拼不出 \r\n）。
# 每条变异第 6 个字段 skip_pins：变异跑（--mutate 的子进程）中跳过的 G4
# 钉现状判据——它们的读数钉的是**本形态**，在该变异形态下必然漂移（非守卫
# 失效，见模块 docstring）；跳过的判据打印 SKIP 行，plain 跑不跳。M1/M2 的
# 期望红项（exp）因此与本件改前逐位一致。
_MUTATIONS = (
    ("M1 回退 main 的同层形态（EXTRA_SCOPE 清空）：#193 漏比必须复发、"
     "阴性判据不得误伤（G1 红、G2/G3 绿）；G4c 的写入面读数随扩面回退消失"
     "（BLINDSPOT）、G4b2 对照面的 kept 随扩面回退 1→0 ⇒ 变异跑跳过 G4b2/G4c"
     "（G4a/G4b 主断言读数与 EXTRA_SCOPE 无关，仍执行且须绿）",
     "md_cg/consistency.py",
     'EXTRA_SCOPE = {"contextual": ("knowledge",)}',
     "EXTRA_SCOPE = {}",
     ("G1a", "G1b"),
     ("G4b2", "G4c")),
    ("M2 还原 b4d8af8 旧形态（层过滤器无条件放行 knowledge：无闸、无另道、"
     "层外候选同池竞争）：只读面被拉动（G2b）＋同层名额被挤占（G3c）必须转红；"
     "G4b 场景下层外候选进同池（scanned/kept 非 0）、G4b2 转可观测（truncated）"
     "、G4c 只读面被拉动（REJECT）⇒ 变异跑跳过 G4b/G4b2/G4c（G4a 在该变异下"
     "层过滤对 knowledge 写入等价，仍执行且须绿）",
     "md_cg/consistency.py",
     '        if layer and e.get("layer") != layer:',
     '        if layer and e.get("layer") != layer and e.get("layer") != "knowledge":',
     ("G1a", "G1b", "G2b", "G3c"),
     ("G4b", "G4b2", "G4c")),
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


def _reds_in(base, skip_pins=()):
    import subprocess
    env = dict(os.environ)
    env["PYTHONPATH"] = base
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["ISS193G_SKIP_PINS"] = ",".join(skip_pins)
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
        for name, rel, old, new, exp, skip_pins in _MUTATIONS:
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
                rc2, reds2, out2 = _reds_in(base, skip_pins)
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
