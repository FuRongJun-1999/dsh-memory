# -*- coding: utf-8 -*-
# 功能名：受保护节点可降级（#733）/ 覆写继承元数据（#732）/ superseded 取代 / retag 只改元数据
# 生效条件：python -X utf8 -m md_cg.test_issue733_verify_override_and_overwrite_inherit；被测面＝MdCG.verify（weakened 与 superseded 两分支）、MdCG.add 的覆写继承、MdCG.retag
# 子功能：G1＝weakened 的 override 透传（受保护节点修前恒拒）；G2＝覆写成「历史与证据」列的继承；G3＝superseded 不删除且不动验证态；G4＝retag 换桶且正文/证据逐字节不变
# 执行：每组建独立临时库，直接调库层 API，断言盘面（读 .md）而非回执单面
# 验证方式：全部 PASS 即退出码 0；任一 FAIL 退出码 1
# 不适用条件：不判 superseded 的检索面排除（既有 is_retired 已有守卫）；不判 edges 的重派生（本批不实现 linkref 重跑，只在正文未变时继承）；不判工具面参数校验
"""守卫：issue #733 + #732 的四条修复。

#733（本组 G1）：`verify(verdict="weakened", override=True)` 对受保护节点仍被拒。
根因是 `set_verification()` 调用漏传 `override` —— 而该函数签名里就有这个参数，
`falsified` 分支也是透传的（对照 `protect.guard_forget(override=...)`）。
后果：受保护节点（importance≥0.7）**只能被确认、不能被存疑**，`doubted` 恒不可达。

#732（本组 G2）：`add()` 是全量重建 fm，同 id 覆写会把 created_at 改成现在、
session 变 unattributed、并丢掉 evidence_log / protected。本组断言这些列被继承，
且「正文逐字未变」时连 edges / importance 也保住。

G3：`falsified` 的语义是**删除**（写 rej_ 存根 + 原文进 trash），而「曾经正确、
后来被取代」不是「假」。lifecycle 里早有 `superseded`（`active/converged/demoted →
superseded`，且可回滚），缺的只是工具面入口。本组断言：不删文件、不动
verification_state、并落 superseded_by。

G4：给存量节点补 `domain:` 标签以迁出 `orphan` 桶，此前只能靠同 id 覆写（撞 #732）。
`retag` 走 add() 的既有写链，但显式保证正文不变 ⇒ 命中 BODY_SAME 继承分支。
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

os.environ.setdefault("MDCG_AUTONOMY", "full")

from md_cg.mdcos import MdCGOS       # noqa: E402

FAILS = []
_TMP = tempfile.mkdtemp(prefix="iss733_")

_CCG = "\n".join([
    "# 功能名：证据节点",
    "# 生效条件：本地合成库",
    "# 子功能：无",
    "# 执行：无",
    "# 验证方式：test",
    "# 不适用条件：无",
    "# 正文：证据节点正文",
])

_CCG2 = _CCG.replace("证据节点正文", "证据节点正文（第二版）")


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:240])
        FAILS.append(name)


def _new(tag, nid="t_ev", importance=0.8, tags=None):
    d = os.path.join(_TMP, tag)
    os.makedirs(d, exist_ok=True)
    cg = MdCGOS(d)
    cg.add(nid, _CCG, layer="knowledge", importance=importance, tags=tags)
    cg.flush()
    return d, cg


def _fm(cg, nid):
    return (cg.get(nid) or {}).get("frontmatter") or {}


print("== G1：verify(weakened) 的 override 必须透传（#733） ==")
_root1, _cg1 = _new("g1")
_fm0 = _fm(_cg1, "t_ev")
_check("G1-0 前置：节点确实受保护（importance≥0.7 自动打位）",
       bool(_fm0.get("protected")), _fm0.get("protected"))
_r_no = _cg1.verify("t_ev", "证据 A", "weakened")
_v_no = (_r_no or {}).get("verification") or {}
_check("G1-1 不给 override ⇒ 仍是 protected（负路由，修前修后都该如此）",
       _v_no.get("code") == "protected" and _v_no.get("ok") is False,
       _v_no)
_r_yes = _cg1.verify("t_ev", "证据 B", "weakened", override=True)
_v_yes = (_r_yes or {}).get("verification") or {}
_check("G1-2 给了 override=True ⇒ 必须放行（修前恒 protected，本组即红点）",
       _v_yes.get("code") == "ok" and _v_yes.get("ok") is True, _v_yes)
_check("G1-3 放行后盘面验证态真的变成 doubted（不是只改回执）",
       (_fm(_cg1, "t_ev").get("verification_state") or "").strip('"')
       == "doubted",
       _fm(_cg1, "t_ev").get("verification_state"))
_check("G1-4 两次裁决的证据都记进 evidence_log（负路由不回滚证据计数）",
       len(_fm(_cg1, "t_ev").get("evidence_log") or []) >= 1)
_cg1.flush()
_cg1.close()

print(chr(10) + "== G1b：连续 weakened 触发降级迁层时，override 也要透传到 _move_layer ==")
_root1b, _cg1b = _new("g1b", nid="t_dm", importance=0.8)
_ok = True
_err = None
for _i in range(3):                     # 0.6 → 0.45 → 0.30 → 0.15（< DEMOTE 0.2）
    try:
        _cg1b.verify("t_dm", "连续负证据 #%d" % _i, "weakened", override=True)
    except Exception as _e:             # noqa: BLE001
        _ok = False
        _err = "%s: %s" % (type(_e).__name__, _e)
        break
_check("G1b-1 受保护节点连续 weakened 不抛 ProtectionError（修前第三轮抛）",
       _ok, _err)
_check("G1b-2 第三轮确实降级迁出到 contextual（按既有 confidence<0.2 规则）",
       ((_cg1b.get("t_dm") or {}).get("frontmatter") or {}).get("layer")
       == "contextual",
       ((_cg1b.get("t_dm") or {}).get("frontmatter") or {}).get("layer"))
_cg1b.flush()
_cg1b.close()


print("\n== G2：覆写继承「历史与证据」列（#732） ==")
_root2, _cg2 = _new("g2")
_cg2.verify("t_ev", "首次验证", "confirmed")
_before = _fm(_cg2, "t_ev")
_cg2.add("t_ev", _CCG2, layer="knowledge", importance=0.8)
_after = _fm(_cg2, "t_ev")
_check("G2-1 created_at 不被重置（出生时间只写一次）",
       _before.get("created_at") == _after.get("created_at"),
       (_before.get("created_at"), _after.get("created_at")))
_check("G2-2 session 不被重置成 unattributed",
       _before.get("session") == _after.get("session"),
       (_before.get("session"), _after.get("session")))
_check("G2-3 evidence_log 不被抹掉",
       len(_after.get("evidence_log") or []) == len(
           _before.get("evidence_log") or []),
       _after.get("evidence_log"))
_check("G2-4 evidence_count 不被归零",
       _after.get("evidence_count") == _before.get("evidence_count"),
       (_before.get("evidence_count"), _after.get("evidence_count")))
_check("G2-5 protected 位不被撤销（保护单向）",
       bool(_after.get("protected")) is True, _after.get("protected"))
_check("G2-6 正文确实换成了第二版（继承没有把新内容也挡掉）",
       "第二版" in ((_cg2.get("t_ev") or {}).get("content") or ""))
_cg2.flush()

print(chr(10) + "== G2b：正文逐字未变时，edges 继承 / importance 走「传 None 才继承」 ==")
_cg2.add("t_ev", _CCG2, layer="knowledge")   # 不传 importance ⇒ 应继承旧值
_same = _fm(_cg2, "t_ev")
_check("G2b-1 不传 importance 时继承旧值（不再回落 0.5）",
       _same.get("importance") == _after.get("importance"),
       (_after.get("importance"), _same.get("importance")))
_check("G2b-2 edges 不被清空（auto:linkref 只派生一次，覆写不重跑）",
       (_same.get("edges") or []) == (_after.get("edges") or []),
       (_after.get("edges"), _same.get("edges")))
_cg2.close()

print("\n== G3：superseded = 被取代，不是被证伪（不删除） ==")
_root3, _cg3 = _new("g3", nid="t_old", importance=0.8)
_cg3.add("t_new", _CCG2, layer="knowledge", importance=0.8)
_fm3_before = _fm(_cg3, "t_old")
try:
    _cg3.verify("t_old", "缺 superseded_by", "superseded")
    _check("G3-1 不给 superseded_by ⇒ 必须报错", False, "没有抛错")
except ValueError as _e:
    _check("G3-1 不给 superseded_by ⇒ 必须报错（取代要能指名替代者）",
           "superseded_by" in str(_e), _e)
_r3 = _cg3.verify("t_old", "升级到 t_new", "superseded",
                  superseded_by="t_new")
_check("G3-2 superseded 返回 ok=True（负路由时不吞错）",
       bool((_r3 or {}).get("ok")), _r3)
_fm3 = _fm(_cg3, "t_old")
_check("G3-3 lifecycle_state 变成 superseded",
       (_fm3.get("lifecycle_state") or "").strip('"') == "superseded",
       _fm3.get("lifecycle_state"))
_check("G3-4 superseded_by 指向替代者（可追溯取代关系）",
       (_fm3.get("superseded_by") or "").strip('"') == "t_new",
       _fm3.get("superseded_by"))
_check("G3-5 节点仍在（不是 falsified 的删除语义）",
       (_cg3.get("t_old") or None) is not None)
_check("G3-6 verification_state 不被改写（「是否当前版本」与「还成不成立」正交）",
       (_fm3.get("verification_state") or "").strip('"')
       == (_fm3_before.get("verification_state") or "").strip('"'),
       (_fm3_before.get("verification_state"),
        _fm3.get("verification_state")))
_check("G3-7 正文与证据链原样（不受取代影响）",
       str((_cg3.get("t_old") or {}).get("content") or "").rstrip('\n')
       == _CCG.rstrip('\n'))
_cg3.flush()
_cg3.close()

print("\n== G4：retag 只改元数据，正文与证据逐字节不变 ==")
_root4, _cg4 = _new("g4", nid="t_rt", importance=0.8)
_cg4.verify("t_rt", "先验证一次，留下 evidence_log", "confirmed")
_fm4_before = _fm(_cg4, "t_rt")
_body_before = (_cg4.get("t_rt") or {}).get("content")
_plan = _cg4.retag("t_rt", tags_add=["domain:测试域"], dry_run=True)
_check("G4-1 dry_run 只算不写：返回将落到的桶（cond_ 前缀）",
       str(_plan.get("bucket") or "").startswith("cond_"),
       _plan.get("bucket"))
_check("G4-2 dry_run 时盘面没动（路径与 tags 都还是旧的）",
       _fm(_cg4, "t_rt").get("tags") == _fm4_before.get("tags"))
_real = _cg4.retag("t_rt", tags_add=["domain:测试域"],
                   condition_space_patch={"observation_position": "测试域"})
_fm4 = _fm(_cg4, "t_rt")
_check("G4-3 落盘后 bucket 变成 cond_ 前缀（真的换桶了）",
       str(_real.get("bucket") or "").startswith("cond_"),
       _real.get("bucket"))
_check("G4-4 tags 里出现了 domain:测试域",
       "domain:测试域" in (_fm4.get("tags") or []), _fm4.get("tags"))
_check("G4-5 正文逐字节未变",
       (_cg4.get("t_rt") or {}).get("content") == _body_before)
_check("G4-6 created_at 未变",
       _fm4.get("created_at") == _fm4_before.get("created_at"),
       (_fm4_before.get("created_at"), _fm4.get("created_at")))
_check("G4-7 evidence_log 未丢",
       len(_fm4.get("evidence_log") or []) == len(
           _fm4_before.get("evidence_log") or []))
_check("G4-8 protected 未丢",
       bool(_fm4.get("protected")) is True, _fm4.get("protected"))
_check("G4-9 节点仍可读（换桶没有把索引写坏）",
       (_cg4.get("t_rt") or {}).get("path") == _real.get("to_path"),
       ((_cg4.get("t_rt") or {}).get("path"), _real.get("to_path")))
_cg4.flush()
_cg4.close()

print("\n== G5：maintain action=retag 的工具面分派 ==")
_root5, _cg5 = _new("g5", nid="t_mt", importance=0.8)
_d5 = _cg5.maintain(action="retag", node_id="t_mt",
                    tags_add=["domain:测试域"], tags_remove=[],
                    condition_space_patch={"observation_position": "测试域"},
                    apply=False)
_check("G5-1 apply=False 缺省 dry_run：返回 dry_run=True 且不落盘",
       bool(_d5.get("dry_run")) and
       "domain:测试域" not in (_fm(_cg5, "t_mt").get("tags") or []), _d5)
_d5b = _cg5.maintain(action="retag", node_id="t_mt",
                     tags_add=["domain:测试域"],
                     condition_space_patch={"observation_position": "测试域"},
                     apply=True)
_check("G5-2 apply=True 才真落盘：换桶且 tags 到位",
       str(_d5b.get("bucket") or "").startswith("cond_")
       and "domain:测试域" in (_fm(_cg5, "t_mt").get("tags") or []), _d5b)
_check("G5-3 分派未把正文写坏（仍可读且正文未变）",
       str((_cg5.get("t_mt") or {}).get("content") or "").rstrip(chr(10))
       == _CCG.rstrip(chr(10)))
_cg5.flush()
_cg5.close()

print(chr(10) + "== G6：write 元数据补丁（只给 tags，不给 content） ==")
_root6, _cg6 = _new("g6", nid="t_wp", importance=0.8)
_cg6.add("t_wp_ref", _CCG2, layer="knowledge", importance=0.5)
_cg6.verify("t_wp", "先验证一次", "confirmed")
_f6 = _fm(_cg6, "t_wp")
_b6 = (_cg6.get("t_wp") or {}).get("content")
from md_cg.mcp_server import _cg_dispatch          # noqa: E402
_r6 = _cg_dispatch(_cg6, {"op": "write", "node_id": "t_wp",
                          "tags": ["domain:测试域"]})
_check("G6-1 直接落盘（不再出变更单）：committed=True 且 moved_to 为空",
       bool(_r6.get("committed")) and not _r6.get("moved_to"),
       {k: _r6.get(k) for k in ("committed", "moved_to", "pid")})
_f6b = _fm(_cg6, "t_wp")
_check("G6-2 tags 打上了 domain:测试域",
       "domain:测试域" in (_f6b.get("tags") or []), _f6b.get("tags"))
_check("G6-3 正文逐字节未变（补丁不动正文）",
       str((_cg6.get("t_wp") or {}).get("content") or "").rstrip(chr(10))
       == str(_b6 or "").rstrip(chr(10)))
_check("G6-4 created_at 未被重置",
       _f6b.get("created_at") == _f6.get("created_at"),
       (_f6.get("created_at"), _f6b.get("created_at")))
_check("G6-5 evidence_log / protected 未丢",
       len(_f6b.get("evidence_log") or []) == len(_f6.get("evidence_log") or [])
       and bool(_f6b.get("protected")))
_check("G6-6b importance 不被压回 0.5（_write_values 不得替调用方回落）",
       float(_f6b.get("importance") or 0) == float(_f6.get("importance") or 0),
       (_f6.get("importance"), _f6b.get("importance")))
_check("G6-6 换桶：路径落到 cond_ 前缀",
       str((_cg6.get("t_wp") or {}).get("path") or "").find("cond_") > 0,
       (_cg6.get("t_wp") or {}).get("path"))
_check("G6-7 正文真变了的覆写仍然出单（对照腿：换一段正文）",
       bool(_cg_dispatch(_cg6, {"op": "write", "node_id": "t_wp",
                                "content": _CCG2,
                                "tags": ["domain:测试域"]}).get("moved_to")),
       "对照腿：改了正文应回 review_queue")
_cg6.flush()
_cg6.close()


print(chr(10) + "== G7：旧格式正文（无 # 要素行）也能做元数据补丁 ==")
_root7, _cg7 = _new("g7", nid="t_legacy")
_LEGACY = "\n".join(["功能名：旧格式节点", "生效条件：当年合法、现在不合新规",
                     "子功能：无", "执行：无", "验证方式：test",
                     "不适用条件：无"])
import os as _os                                    # noqa: E402
_os.remove(_os.path.join(_root7, (_cg7.get("t_legacy") or {}).get("path")))
_cg7.add("t_legacy", _LEGACY, layer="knowledge", importance=0.8)
_b7 = (_cg7.get("t_legacy") or {}).get("content")
_r7 = _cg_dispatch(_cg7, {"op": "write", "node_id": "t_legacy",
                          "tags": ["domain:测试域"]})
_check("G7-1 旧格式正文的元数据补丁不被内容闸拒收（正文没变，不该重判合规）",
       bool(_r7.get("committed")),
       {k: _r7.get(k) for k in ("committed", "error", "moved_to")})
_check("G7-2 正文原样保留",
       str((_cg7.get("t_legacy") or {}).get("content") or "").rstrip(chr(10))
       == str(_b7 or "").rstrip(chr(10)))
_check("G7-3 domain 标签已打上",
       "domain:测试域" in ((_fm(_cg7, "t_legacy").get("tags")) or []))
_cg7.flush()
_cg7.close()


print("\n== 结果 ==")
if FAILS:
    print("FAIL %d 项：%s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("全部 PASS")
sys.exit(0)
