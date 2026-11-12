# -*- coding: utf-8 -*-
# 功能名：gated 写入的 BLINDSPOT 不得静默丢弃（issue #361）
# 生效条件：python -X utf8 -m md_cg.test_issue361_blindspot_not_silent_drop [--mutate]；被测面=md_cg/mdcg.py 的 MdCG.add 冲突路由 + md_cg/mdcos.py 的 MdCGOS.remember_gated ACCEPT 分支
# 子功能：A 组=新库首写 BLINDSPOT 恒放行落盘、返回体带去向、自我维持破除、批量 20 条零静默丢弃；K 组=非恒真对照（正常路径照常落盘 / REJECT 三态语义不变 / 只读判定面不扩面 / 判定层未被改写）；E 组=源码面单点
# 执行：新库上直调 remember_gated(consistency=True, on_conflict="defer")，读返回体 + 盘面节点数 + inbox 行数；再直调 MdCG.add 复算 REJECT 的三种 on_conflict
# 验证方式：全部 PASS 即通过；--mutate 走镜像树定点变异，变异后红项必须**恰为**预期集合（M1 回退 BLINDSPOT 放行 / M2 摘掉判定回填 / M3 摘掉 REJECT 去向词）
# 不适用条件：①只判「冲突闸 BLINDSPOT 的路由」，不覆盖 writelimit 限流 DEFER 出口（其语义是「先别写」，原文在 recent 时间线，issue50-b 明确排除）②不判密级/加密面 ③不判 writepipe 链的 gated 分支（该处 consistency=False，本不产生 BLINDSPOT）④不改判定层四态（BLINDSPOT 仍是 BLINDSPOT，只改路由）⑤不判 for get / 落盘之后的检索资格（另属 CCG 六要素面）
"""issue #361 守卫：BLINDSPOT 不得静默丢弃。

病象（修前，报告方实测《民法典》批量 200/200 丢失）：`mdcg_remember(gated=true)`
在新库（尚无已声明条件节点）写入时，主动遗忘闸判 ACCEPT 之后
`consistency.check` 判 BLINDSPOT（comparable==0，「检测前提不存在」），
`MdCG.add` 的 `on_conflict="defer"` 出口 `return None`，`remember_gated` 就地改
verdict="DEFER" 且**既不落盘也不入队**——正文不在任何节点、不在 inbox.jsonl，
返回体无 moved_to/proposed/conflict/reason。且空库自我维持：comparable 恒 0，
下一条照样丢（库永远写不进第一条）。

处置（与 issue #26 同一判据同一口径）：**判定层不动**（BLINDSPOT 仍是
BLINDSPOT，只读 check 面一字不改），**路由层对齐写链**
`writepipe._gate_consistency`——BLINDSPOT 恒放行、REJECT 维持 on_conflict 语义；
并由 `MdCG.add` 新增的只读回填槽 `consistency_out` 把本次判定带回调用方
（`out["consistency"]`，与 `writepipe._executor` 同名同义）。

★**归因手法（跨流并发时通用，值得复用）＝「HEAD 导出树」对照**：
本仓常有数条流同时在改不同文件，全量红项未必是你的。判「这条红是不是我改出来的」
不要靠推理，靠**只读导出改动前的树**再跑同一个守卫：

    git -C <repo> archive HEAD -o <tmp>/head.tar
    mkdir <tmp>/tree_head && tar -xf <tmp>/head.tar -C <tmp>/tree_head
    $env:PYTHONPATH='<tmp>/tree_head'; python -X utf8 -m md_cg.<守卫>
（路径分隔符统一写正斜杠，避免字符串里的反斜杠触发 invalid escape 警告）

导出树**不含未提交改动**，故两边读数之差即「本工作树相对 HEAD 的行为变化」，能把
「他流的未完成改动」与「自己的改动」干净隔离。本件实测：`md_cg.test_n209_verify_write_face_gates`
在导出树上 23 passed / 0 failed、在工作树上 22/1 ⇒ 该回归由「层保护」那条流引入，
与 #361 无关（`git archive` 是**只读**命令，不落任何工作树改动；与 `_mirror_build`
的区别是后者复制**当前**工作树、用于定点变异）。
"""
import glob
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
_TMP = tempfile.mkdtemp(prefix="iss361_")
os.environ.update({"MDCG_ROOT": _TMP + "/brainroot",
                   "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})

from md_cg import autonomy_modes                     # noqa: E402

# 夹具隔离：本守卫考的是「BLINDSPOT 的去向」，不是自治档位；显式置 full 档，
# 让 remember_gated 的写入行为回到「动作直落」（同 test_issue190 的口径）。
os.environ[autonomy_modes.AUTONOMY_ENV_KEYS["mode"]] = "full"

from md_cg import consistency, mdcg                 # noqa: E402
from md_cg.mdcos import MdCGSecure                   # noqa: E402
from md_cg.security import Principal                 # noqa: E402

FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


def _new(tag):
    root = os.path.join(_TMP, tag)
    return MdCGSecure(root, principal=Principal(
        role="designer", clearance="private", can_write=True,
        can_admin=True), autoflush=1), root


#: 20 条互不相同的主题——批量形态要证明「不是单条偶发」，且需要**首条落盘后
#: 其余不再 BLINDSPOT 且照常落盘**（若写成近重复内容，其余会落到遗忘闸的
#: 「半重复 DEFER」出口——那测的是另一条出口，测不出本缺陷）。
_TOPICS = (
    ("配电房巡检", "高压开关柜", "记录柜体温度读数"),
    ("冷库温控", "冷库压缩机", "校准启停压力阈值"),
    ("消防泵房", "消防稳压泵", "核对出口压力表读数"),
    ("电梯年检", "曳引机钢丝绳", "测量磨损量并登记"),
    ("锅炉水质", "锅炉软水器", "检测硬度与含氧量"),
    ("空调滤网", "组合式空调机组", "记录滤网前后压差"),
    ("污水提升站", "潜水排污泵", "核对液位浮球动作位"),
    ("变配电室", "干式变压器", "记录绕组温升曲线"),
    ("空压机房", "螺杆空压机", "记录排气温度与油位"),
    ("不间断电源室", "蓄电池组", "测量单体端电压"),
    ("消防栓管网", "室外消火栓", "测量栓口静压"),
    ("燃气调压站", "调压器切断阀", "核对切断压力设定值"),
    ("库房货架", "横梁式货架", "检查横梁卡扣锁止"),
    ("叉车班检", "电动叉车", "核对制动片间隙"),
    ("光伏阵列", "组串式逆变器", "记录直流侧绝缘阻值"),
    ("弱电机房", "核心交换机", "核对端口错包计数"),
    ("水处理加药", "计量泵", "校准冲程频率"),
    ("隧道风机", "射流风机", "核对振动速度有效值"),
    ("边坡监测", "测斜管", "读取累计位移量"),
    ("桥梁支座", "板式橡胶支座", "测量剪切变形量"),
)

#: 不适用条件取一个与全部主题词面**不相交**的固定短语：一是避免自否定
#: （负条件与正文强相关 → REJECT），二是避免 20 条之间互相条件互斥。
_NEG = "台风橙色预警期间"


def _ccg(i):
    """CCG 六要素齐全、且逐行带本主题独有词的正文。

    逐行塞主题词是为了把两条节点之间的词面重合压到遗忘闸的「半重复」阈值
    （0.60）以下——否则 20 条会全部落进 DEFER 出口，批量读数就测不到本缺陷。
    """
    fn, cond, body = _TOPICS[i % len(_TOPICS)]
    return ("# 功能名：%s\n"
            "# 生效条件：处理 %s 的 %s 任务时\n"
            "# 子功能：%s\n"
            "# 执行：按 %s 定位并回填 %s 台账\n"
            "# 验证方式：与 %s 的 %s 现场记录逐字比对\n"
            "# 不适用条件：%s\n"
            "正文：%s 的 %s 处置要点是%s。\n"
            % (fn, cond, fn, body, cond, fn, cond, fn, _NEG, cond, fn, body))


def _ccg_selfneg():
    """自否定正文：不适用条件「超时」命中自身生效条件「超时 30s 允许并发」。

    L1-a 自否定只看新正文自身（consistency.py :751-757），故这是**不依赖既有库**
    的确定性 REJECT 构造（test_write_return_shape G7h 同源）。
    """
    return ("# 功能名：冲突体\n"
            "# 生效条件：超时 30s 允许并发\n"
            "# 不适用条件：超时\n"
            "正文：本轮不引入任何等待。\n")


def _written(out):
    return bool(out.get("written"))


def _has_route(out):
    """有去向＝落盘 / 入队 / 合并 / 丢弃 / 出单 / 明确挡下，任一可追溯出口。"""
    return any(out.get(k) for k in ("written", "proposed", "moved_to",
                                     "merged_into", "dropped", "mutation", "pid"))


def _nodes(root):
    return glob.glob(os.path.join(root, "**", "*.md"), recursive=True)


def _inbox_lines(root):
    n = 0
    for f in glob.glob(os.path.join(root, "**", "inbox*.jsonl"), recursive=True):
        with open(f, encoding="utf-8", errors="replace") as fh:
            n += sum(1 for ln in fh if ln.strip())
    return n


def _batch(n, layer="knowledge"):
    """批量形态：返回 (落盘数, 有去向数, 无去向数, 判定态分布, 盘面)。"""
    cg, root = _new("batch361")
    landed = routed = 0
    states = {}
    for i in range(n):
        out = cg.remember_gated("b361_%d" % i, _ccg(i), layer=layer,
                                consistency=True, on_conflict="defer")
        cv = (out.get("consistency") or {}).get("verdict") or out.get("verdict")
        states[cv] = states.get(cv, 0) + 1
        if _written(out):
            landed += 1
        if _has_route(out):
            routed += 1
    cg.close()
    return (landed, routed, n - routed, states,
            (len(_nodes(root)), _inbox_lines(root)))


print("== A 组：新库首写 BLINDSPOT 必须落盘且带去向 ==")
_a_cg, _a_root = _new("a1")
_a_content = _ccg(1)
# A2 的命中点先算：与 A1 同一份内容、同一层——证明 A1 命中的确实是 BLINDSPOT
# 分支（comparable==0），而不是「本来就不冲突」。
_a_vd = _a_cg.check_consistency(_a_content, layer="contextual",
                                exclude="a361_1", write_scope=True,
                                auto_flywheel=False)
_a1 = _a_cg.remember_gated("a361_1", _a_content, layer="contextual",
                           consistency=True, on_conflict="defer")
_check("A1 新库首写（contextual＝插件缺省层）→ 落盘（修前 written=None、盘上 0 节点）",
       _written(_a1), json.dumps(_a1, ensure_ascii=False, default=str)[:200])
_check("A1b 与盘面事实一致（节点文件确在盘上）",
       len(_nodes(_a_root)) == 1, len(_nodes(_a_root)))
_check("A2 命中点确认：同一内容 check_consistency 判 BLINDSPOT 且 comparable==0",
       _a_vd.get("verdict") == "BLINDSPOT" and _a_vd.get("comparable") == 0,
       (_a_vd.get("verdict"), _a_vd.get("comparable"), _a_vd.get("reason")))
_ac = _a1.get("consistency") or {}
_check("A3 去向/追溯可观测：返回体带 written + consistency(BLINDSPOT/comparable/reason)，"
       "且无 moved_to（证明不是被挡下）",
       _written(_a1) and _ac.get("verdict") == "BLINDSPOT"
       and _ac.get("comparable") == 0 and bool(_ac.get("reason"))
       and "moved_to" not in _a1,
       sorted(_a1))
_a_cg.close()

_a4cg, _a4root = _new("a4")
_a4a = _a4cg.remember_gated("a361_3", _ccg(1), layer="knowledge",
                            consistency=True, on_conflict="defer")
# 第二条的冲突判定显式复算（ACCEPT 态按「闸门有读数才随体带回」口径不落键，
# 故不依赖返回体，直接用 check_consistency 取 comparable）。
_a4v = _a4cg.check_consistency(_ccg(2), layer="knowledge", exclude="a361_4",
                               write_scope=True, auto_flywheel=False)
_a4b = _a4cg.remember_gated("a361_4", _ccg(2), layer="knowledge",
                            consistency=True, on_conflict="defer")
_a4av = _a4a.get("consistency") or {}
_check("A4 空库首写判 BLINDSPOT 并落盘；第二条 comparable>=1、判 ACCEPT 且落盘"
       "（空库自我维持被破除，修前 comparable 恒 0）",
       _a4av.get("verdict") == "BLINDSPOT" and _written(_a4a)
       and _a4v.get("verdict") == "ACCEPT" and _a4v.get("comparable", 0) >= 1
       and _written(_a4b),
       (_a4av.get("verdict"), _a4v.get("verdict"), _a4v.get("comparable"),
        _written(_a4a), _written(_a4b)))
_a4cg.close()

print("== A5 批量 20 条（报告方实测《民法典》批量 200/200 丢失）==")
_landed, _routed, _orphan, _states, _disk = _batch(20)
print("   [读数] 落盘=%d 有去向=%d 无去向=%d 判定态=%s 盘面(节点,inbox行)=%s"
      % (_landed, _routed, _orphan, _states, _disk))
_check("A5a 批量 20 条零静默丢弃（无去向 == 0；报告方修前读数 20/20 无去向）",
       _orphan == 0, (_orphan, _states))
_check("A5b 批量 20 条 ≥1 条真落盘（修前 0 条：库越空越写不进）",
       _landed >= 1, _landed)
_check("A5c 首条之后不再 BLINDSPOT（自我维持破除）",
       _states.get("BLINDSPOT", 0) <= 1, _states)

print("== K 组：非恒真对照（修复没把正常路径一起关掉）==")
# K1 的第一条用 on_conflict="record" 落库——该出口修前修后都放行 BLINDSPOT，
# 故 K1 与 A 组的修复点**解耦**：变异镜像里 K1 也必须保持绿（它是非恒真对照，
# 不是修复点的复读）。第二条走 defer，验「正常写入照常落盘、不经拦截出口」。
_k1cg, _k1root = _new("k1")
_k1cg.remember_gated("k361_a", _ccg(1), layer="knowledge",
                     consistency=True, on_conflict="record")
_k1b = _k1cg.remember_gated("k361_b", _ccg(2), layer="knowledge",
                            consistency=True, on_conflict="defer")
_check("K1 有既有声明条件的库上正常写入照常落盘、不经任何拦截出口"
       "（无 moved_to / proposed / dropped）",
       _written(_k1b) and not _k1b.get("moved_to")
       and not _k1b.get("proposed") and not _k1b.get("dropped")
       and _k1b.get("verdict") == "ACCEPT",
       json.dumps(_k1b, ensure_ascii=False, default=str)[:220])
# K1b 过度收紧方向的对照：口径是「闸门有读数（非 ACCEPT）才随体带回」，故无冲突
# 的正常写入**不得**多出新键（不动面对拍 test_mode_parity Q 组以此为判据）。
_check("K1b 无冲突（ACCEPT）写入不新增 consistency 键——不动面口径",
       "consistency" not in _k1b, sorted(_k1b))
_k1cg.close()

_k2cg, _k2root = _new("k2")
_k2 = _k2cg.add("k361_rej1", _ccg_selfneg(), layer="knowledge",
                consistency=True, on_conflict="defer")
_check("K2 REJECT + on_conflict=defer 仍不落盘（返回 None，既有语义不变）",
       _k2 is None and _k2cg.get("k361_rej1") is None, _k2)
try:
    _k2cg.add("k361_rej2", _ccg_selfneg(), layer="knowledge",
              consistency=True, on_conflict="reject")
    _k3 = "放行"
except consistency.ConsistencyError as _e:
    _k3 = "ConsistencyError:" + str(_e.verdict)
except Exception as _e:                                      # noqa: BLE001
    _k3 = type(_e).__name__
_check("K3 REJECT + on_conflict=reject 仍抛 ConsistencyError（既有面不退化）",
       str(_k3).startswith("ConsistencyError:REJECT"), _k3)
_k4 = _k2cg.add("k361_rej3", _ccg_selfneg(), layer="knowledge",
                consistency=True, on_conflict="record")
_fm4 = (_k2cg.get("k361_rej3") or {}).get("frontmatter") or {}
_check("K4 REJECT + on_conflict=record 仍记录后放行（fm.consistency 落 REJECT）",
       _k4 == "k361_rej3"
       and (_fm4.get("consistency") or {}).get("verdict") == "REJECT",
       (_k4, _fm4.get("consistency")))
_k2cg.close()

# K5/K6：判定层一个字没动——四态仍诚实，只读面仍不扩面（issue #193 K1 同口径）
_k5cg, _k5root = _new("k5")
_k5cg.add("k361_kb", _ccg(1), layer="knowledge")
_k5_ro = _k5cg.check_consistency(_ccg(2), layer="contextual",
                                 write_scope=False, auto_flywheel=False)
_k5_rw = _k5cg.check_consistency(_ccg(2), layer="contextual",
                                 write_scope=True, auto_flywheel=False)
_check("K5 只读判定面不扩面：contextual 写入比对范围仍不看 knowledge（BLINDSPOT）",
       _k5_ro.get("verdict") == "BLINDSPOT" and _k5_rw.get("comparable", 0) >= 1,
       (_k5_ro.get("verdict"), _k5_rw.get("verdict"), _k5_rw.get("comparable")))
_k5cg.close()
_k6cg, _k6root = _new("k6")
_k6 = _k6cg.check_consistency(_ccg(1), layer="knowledge",
                              write_scope=True, auto_flywheel=False)
_check("K6 判定层未被改写成 ACCEPT：空库带条件内容仍如实判 BLINDSPOT",
       _k6.get("verdict") == "BLINDSPOT" and _k6.get("comparable") == 0,
       (_k6.get("verdict"), _k6.get("comparable")))
_k6cg.close()

# K7：REJECT-defer 经 remember_gated 出口仍不落盘，且必须给出向（#109 的同一面）
_k7cg, _k7root = _new("k7")
_k7 = _k7cg.remember_gated("k361_rejg", _ccg_selfneg(), layer="knowledge",
                           consistency=True, on_conflict="defer")
_check("K7 REJECT-defer 出口不落盘 + moved_to=conflict_deferred + 判定随体带回",
       (not _written(_k7)) and _k7.get("verdict") == "DEFER"
       and _k7.get("moved_to") == "conflict_deferred"
       and (_k7.get("consistency") or {}).get("verdict") == "REJECT",
       json.dumps(_k7, ensure_ascii=False, default=str)[:220])
_k7cg.close()

print("== E 组：源码面单点 ==")
_add_src = inspect.getsource(mdcg.MdCG.add)
_rg_src = inspect.getsource(MdCGSecure.remember_gated)
_ck_src = inspect.getsource(consistency.check)
_check("E1 MdCG.add 的 defer 拦截只绑 REJECT（BLINDSPOT 已摘出）",
       'if v == "REJECT" and on_conflict == "defer":' in _add_src
       and '("REJECT", "BLINDSPOT")' not in _add_src,
       [l.strip() for l in _add_src.splitlines()
        if "on_conflict" in l and "defer" in l][:2])
_check("E2 MdCG.add 有只读回填槽 consistency_out（三条出口都可追溯）",
       'consistency_out["consistency"] = vd' in _add_src
       and "consistency_out: dict = None" in _add_src)
_check("E3 remember_gated 接线：回填槽入参 + 非 ACCEPT 态带 consistency + REJECT 支带去向词",
       "consistency_out=_cgate" in _rg_src
       and 'out["consistency"] = _cvd' in _rg_src
       and '_cvd.get("verdict") != "ACCEPT"' in _rg_src
       and 'out["moved_to"] = "conflict_deferred"' in _rg_src)
_check("E4 判定层未改：consistency.check 仍保留 comparable==0 的 BLINDSPOT 分支",
       'elif comparable == 0 and (pos or neg):' in _ck_src
       and 'verdict = "BLINDSPOT"' in _ck_src)

shutil.rmtree(_TMP, ignore_errors=True)

print("")
if FAILS:
    print("issue #361 结果：%d 失败 → %s" % (len(FAILS), ", ".join(FAILS)))
else:
    print("issue #361 结果：全部通过")

# ------------------------------------------------------------- 定点变异（镜像树）
_MUTATIONS = (
    # (描述, ((文件, 旧锚点行组, 新锚点行组), ...), 预期红项集合)
    # 预期红项是**精确集合**：多红＝伤及无关判据，少红＝变异没打中修复点。
    ("M1 把 BLINDSPOT 重新算回 defer 拦截（回到 mdcg 侧修前形态：既不落盘也不入队）",
     (("md_cg/mdcg.py",
       ['            if v == "REJECT" and on_conflict == "defer":',
        '                return None'],
       ['            if v in ("REJECT", "BLINDSPOT") and on_conflict == "defer":',
        '                return None']),),
     ("A1", "A1b", "A3", "A4", "A5b", "A5c", "E1")),
    ("M2 摘掉判定回填（放行支不再带 consistency，去向不可追溯）",
     (("md_cg/mdcos.py",
       ['                if _cvd is not None and _cvd.get("verdict") != "ACCEPT":'],
       ['                if False:']),),
     ("A3", "A4", "E3", "K7")),
    ("M3 摘掉 REJECT-defer 的去向词（该出口重新变成无去向键）",
     (("md_cg/mdcos.py",
       ['                    out["moved_to"] = "conflict_deferred"'],
       ['                    pass']),),
     ("K7", "E3")),
    ("M4 两处同时回退＝ #361 真·修前形态（mdcg 拦截 + mdcos 无去向）",
     (("md_cg/mdcg.py",
       ['            if v == "REJECT" and on_conflict == "defer":',
        '                return None'],
       ['            if v in ("REJECT", "BLINDSPOT") and on_conflict == "defer":',
        '                return None']),
      ("md_cg/mdcos.py",
       ['                out["moved_to"] = "conflict_deferred"'],
       ['                pass']),),
     ("A1", "A1b", "A3", "A4", "A5a", "A5b", "A5c", "E1", "E3", "K7")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss361_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and name.endswith(".py"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _nl_of(path):
    """按目标文件**实际行尾**折算（本仓 CRLF/LF 混合）。"""
    with open(path, "rb") as fh:
        raw = fh.read(8192)
    return "\r\n" if b"\r\n" in raw else "\n"


def _anchor(parts, nl):
    """跨行锚点用 chr(10) 拼接后按目标文件行尾折算（不写多行字符串字面量）。"""
    return nl.join(parts)


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue361_blindspot_not_silent_drop"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "FAIL " in ln]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：把修复点改回改动前形态 / 摘掉接线，守卫必须转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-25:]))
        for ln in out.splitlines():
            if "[读数]" in ln:
                print("  修后读数（未变异镜像）：" + ln.strip())
        okc, bad = 0, []
        for desc, edits, exp in _MUTATIONS:
            backups, miss = [], []
            for rel, oldp, newp in edits:
                p = os.path.join(tree, rel)
                nl = _nl_of(p)
                old, new = _anchor(oldp, nl), _anchor(newp, nl)
                with open(p, encoding="utf-8", newline="") as fh:
                    t = fh.read()
                if t.count(old) != 1:
                    miss.append("%s —— 锚点命中 %d 次" % (rel, t.count(old)))
                    continue
                backups.append((p, t))
                with open(p, "w", encoding="utf-8", newline="") as fh:
                    fh.write(t.replace(old, new, 1))
            if miss:
                bad.append("%s —— %s" % (desc, "；".join(miss)))
                print("  ANCHOR-MISS " + desc)
                for p, t in backups:
                    with open(p, "w", encoding="utf-8", newline="") as fh:
                        fh.write(t)
                continue
            rc2, reds2, out2 = _run_in(tree)
            for p, t in backups:
                with open(p, "w", encoding="utf-8", newline="") as fh:
                    fh.write(t)
            # 逐条按「红项名 + 空格」前缀折算（避免 A1 把 A1b 一并吞掉），
            # 得到「实际命中的预期红项集合」。
            hit = sorted({e for r in reds2 for e in exp
                          if r.startswith(e + " ")})
            # 严格口径：红项必须**恰为**预期集合（多红＝伤及无关判据，少红＝变异无效）
            if rc2 != 0 and hit == sorted(exp) and len(reds2) == len(exp):
                okc += 1
                print("  OK   %s  红项=%d 指定命中=%d/%d"
                      % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s  红项=%d 指定命中=%d/%d rc=%d"
                      % (desc, len(reds2), len(hit), len(exp), rc2))
                for r in reds2[:14]:
                    print("        FAIL " + r)
            for ln in out2.splitlines():
                if "[读数]" in ln:
                    print("        变异后读数：" + ln.strip())
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
