# -*- coding: utf-8 -*-
"""角色化读取视图四臂对照 bench（第四阶段计划批次 D，H5 验收）。

臂：
  A0 基线     view=None + include_work=True（无差别全量读取：
              不看角色、含工作回执——真无差别口径）
  A1 main     主代理（结论与修正历史）
  A2 verifier 验证端（判据面与环境陷阱）
  A3 receipt  回执审计（命令与预期输出）

指标（复用 budget_tokens 装包口径）：
  tokens  = recall(budget_tokens=BIG) 的 tokens_used——同等读取意图下
            实际装入内容的消耗；budget 给足以免截断干扰四臂横比；
  hit@k   = gold 在 pack 内位置（k=1/5/10）+ MRR。

跑法：
  对齐跑  Q_role × view=role 对比 Q_role × 基线——H5 主判据
          （各对齐臂 token 下降 且 命中率不降）；
  隔离跑  错配组合（如 Q_receipt × main 臂）gold 期望不可见——
          view 过滤真实生效的硬边界实证。

语料：确定性构造（固定词面、无随机、无外部数据依赖），临时库自建自清理。
退出码：0 = H5 通过；1 = 权衡（如实报告，禁止为凑指标调规则表后不复跑）。

运行：python -m md_cg.bench_role_views
"""

import shutil
import sys
import tempfile

from .mdcos import MdCGSecure
from .security import Principal

BIG_BUDGET = 100000   # 给足预算：四臂横比看内容消耗差异，不受截断干扰
# 候选集由词面命中决定（检索器语义，非全池排序——探针实证），k 只是宽松
# 上限：给足以免截断干扰四臂横比；命中率报 hit@1/5/10 + MRR（窗口内位置）。
TOP_K = 32

# ---------------- 语料（确定性；(nid, layer, content_kind, role, content)） ----------------
_CORPUS = [
    # main 域：结论与修正历史（knowledge + text/work_done，无 role）
    ("bm1", "knowledge", "text", None,
     "发布回滚结论：主支合并验证完成，回滚脚本已归档备查"),
    ("bm2", "knowledge", "work_done", None,
     "编译链修复工作完成：名实校验五处缺陷全部清零"),
    ("bm3", "knowledge", "text", None,
     "缓存刷新结论：快照增量重放语义已锁定不变"),
    ("bm4", "knowledge", "work_done", None,
     "索引迁移完成：三处白名单补齐内容类型字段"),
    ("bm5", "knowledge", "text", None,
     "检索对齐结论：四路融合排序与基线逐位一致"),
    # verifier 域：判据面与环境陷阱（ccg_marks 或 contextual 层 text）
    ("bv1", "knowledge", "ccg_marks", None,
     "环境陷阱判据：GBK 解码异常须显式声明 UTF-8 标志"),
    ("bv2", "knowledge", "ccg_marks", None,
     "静默失败判据：多行内联命令退出码不可信，须脚本文件驱动"),
    ("bv3", "contextual", "text", None,
     "情境上下文实录：命令链尾部被引号换行吞没"),
    ("bv4", "contextual", "ccg_marks", None,
     "情境判据：提交显示成功但推送静默未执行的取证要点"),
    ("bv5", "contextual", "text", None,
     "上下文补充：重建成果曾被陈旧常驻进程覆盖回滚"),
    # receipt 域：命令与预期输出（code + WORK_ROLES）
    ("br1", "knowledge", "code", "command",
     "推送命令：git push origin main，预期输出复核通过"),
    ("br2", "knowledge", "code", "tool-output",
     "状态命令输出：ahead 2 尚未推送，工作区存在改动"),
    ("br3", "knowledge", "code", "edit",
     "补丁片段：--root 参数移动到子命令之后生效"),
    ("br4", "knowledge", "code", "command",
     "导入命令：python migrate_receipts 脚本文件驱动执行"),
    ("br5", "knowledge", "code", "tool-output",
     "测试命令输出：53 ok 0 fail 全绿通过"),
    # 干扰：无差读取臂的背景噪声（视图臂应剔除或降位）
    ("bd1", "knowledge", "text", None, "会议纪要：季度规划讨论了若干方向性议题"),
    ("bd2", "knowledge", "text", None, "读书笔记：系统一致性与反馈回路的一般性介绍"),
    ("bd3", "contextual", "text", None, "闲聊上下文：天气与周末安排的对话残留"),
    ("bd4", "knowledge", "code", None, "示例代码片段：打印问候语的演示脚本"),
    ("bd5", "knowledge", "work_done", None, "例行工作完成记录：周报已按时提交"),
    ("bd6", "knowledge", "ccg_marks", None, "通用判据示例：正常路径与边界条件各自成立"),
    # 跨域诱饵：词面横跨多域——基线（无差别）会命中，视图臂应剔除，
    # 打破「各域词面天然隔离」的失真（首跑实证：verifier 臂 -0.0% 的根因）。
    ("dk1", "knowledge", "work_done", None,
     "判据复盘工作完成：陷阱用例与命令输出的归档记录"),
    ("dk2", "contextual", "text", None,
     "结论情境补充：命令归档上下文中的判据留痕"),
    ("dk3", "knowledge", "code", "command",
     "对照命令：结论与判据的输出对照脚本"),
]

# ---------------- 三角色查询集（每题唯一 gold；词面与 gold 共享中文 2-gram） ----------------
_QUERY_SETS = {
    "main": [
        ("回滚 结论 归档", "bm1"),
        ("编译链 修复 完成", "bm2"),
        ("缓存 刷新 结论", "bm3"),
        ("索引 迁移 完成", "bm4"),
        ("检索 对齐 一致", "bm5"),
    ],
    "verifier": [
        ("陷阱 判据 编码", "bv1"),
        ("判据 静默 失败", "bv2"),
        ("上下文 吞没 陷阱", "bv3"),
        ("情境 判据 取证", "bv4"),
        ("上下文 覆盖 成果", "bv5"),
    ],
    "receipt": [
        ("推送 命令 输出", "br1"),
        ("状态 输出 推送", "br2"),
        ("补丁 参数 子命令", "br3"),
        ("导入 命令 脚本", "br4"),
        ("测试 输出 全绿", "br5"),
    ],
}

# 对齐跑：查询集 → 自己的视图臂
_ALIGNED = {"main": "main", "verifier": "verifier", "receipt": "receipt"}
# 隔离跑（硬边界）：这些组合 gold 期望不可见
#   receipt 域 gold 带 WORK_ROLES → main/verifier 臂 include_work=False 一票否决；
#   main/verifier 域 gold 无 role → receipt 白名单不收。
_ISOLATED = [("receipt", "main"), ("receipt", "verifier"),
             ("main", "receipt"), ("verifier", "receipt")]


def _mk_cg():
    tmp = tempfile.mkdtemp(prefix="mdcg_bench_rv_")
    p = Principal(tenant="default", actor="bench_role_views", role="designer",
                  can_write=True, can_admin=True)
    cg = MdCGSecure(tmp, principal=p)
    for nid, layer, ck, role, content in _CORPUS:
        kw = {"layer": layer, "content_kind": ck}
        if role is not None:
            kw["role"] = role
        cg.add(nid, content, **kw)
    return cg, tmp


def _run_arm(cg, query, view, include_work=False):
    """单题单臂：返回 (pack 内 id 序列, tokens_used)。

    基线臂传 include_work=True——「无差别全量读取」的忠实口径：
    若基线沿用默认 include_work=False，receipt 域（WORK_ROLES）在基线
    完全不可见（首跑实证 hit 0%），对照便不公平；视图臂保持默认
    include_work=False——view 非空时 role 维度由视图规则接管（receipt
    是默认剔除的补集，这正是视图存在的理由之一）。
    """
    rec = cg.recall(query, budget_tokens=BIG_BUDGET, k=TOP_K,
                    view=view, include_work=include_work)
    return ([p["id"] for p in rec.get("pack") or []],
            int(rec.get("tokens_used") or 0))


def _metrics(hits_by_k, token_list):
    """hits_by_k: 每题 gold 在 pack 的 1-based 位置（不可见=0）。"""
    n = len(token_list)
    mrr = sum(1.0 / h for h in hits_by_k if h > 0) / max(n, 1)
    return {"hit@1": sum(1 for h in hits_by_k if 1 <= h <= 1) / n,
            "hit@5": sum(1 for h in hits_by_k if 1 <= h <= 5) / n,
            "hit@10": sum(1 for h in hits_by_k if 1 <= h <= 10) / n,
            "mrr": mrr,
            "tokens": sum(token_list) / n}


def _fmt(m):
    return ("hit@1 %.0f%%  hit@5 %.0f%%  hit@10 %.0f%%  MRR %.3f  tokens %.0f"
            % (m["hit@1"] * 100, m["hit@5"] * 100, m["hit@10"] * 100,
               m["mrr"], m["tokens"]))


def main():
    cg, tmp = _mk_cg()
    ok = True
    try:
        print("==== bench_role_views：角色化读取视图四臂对照（H5） ====")
        print("语料 %d 节点（main 域 5 / verifier 域 5 / receipt 域 5 / "
              "干扰 6 / 跨域诱饵 3），查询 3 类 × 5 题，k=%d，budget=%d"
              % (len(_CORPUS), TOP_K, BIG_BUDGET))

        # ---------- 对齐跑（H5 主判据） ----------
        print("\n---- 对齐跑：Q_role × view=role vs 基线（含诱饵词面跨域命中） ----")
        token_pass, hit_pass = True, True
        for role, view in _ALIGNED.items():
            qs = _QUERY_SETS[role]
            pos0, tok0 = [], []
            posv, tokv = [], []
            for q, gold in qs:
                ids0, t0 = _run_arm(cg, q, None, include_work=True)
                idsv, tv = _run_arm(cg, q, view)
                pos0.append(ids0.index(gold) + 1 if gold in ids0 else 0)
                posv.append(idsv.index(gold) + 1 if gold in idsv else 0)
                tok0.append(t0)
                tokv.append(tv)
            m0, mv = _metrics(pos0, tok0), _metrics(posv, tokv)
            drop = (m0["tokens"] - mv["tokens"]) / m0["tokens"] * 100.0
            t_ok = mv["tokens"] < m0["tokens"]
            h_ok = (mv["hit@1"] >= m0["hit@1"] and mv["hit@5"] >= m0["hit@5"]
                    and mv["hit@10"] >= m0["hit@10"] and mv["mrr"] >= m0["mrr"])
            token_pass &= t_ok
            hit_pass &= h_ok
            print("\n[%s] view=%s（token %s）" %
                  (role, view, "下降" if t_ok else "未下降"))
            print("  基线    %s" % _fmt(m0))
            print("  %s  %s   (%+.1f%% tokens)" %
                  (view.ljust(9), _fmt(mv), -drop))

        # ---------- 隔离跑（硬边界实证） ----------
        print("\n---- 隔离跑：错配组合 gold 期望不可见 ----")
        iso_pass = True
        for role, view in _ISOLATED:
            missed = 0
            for q, gold in _QUERY_SETS[role]:
                ids, _t = _run_arm(cg, q, view)
                if gold not in ids:
                    missed += 1
            this_ok = missed == len(_QUERY_SETS[role])
            iso_pass &= this_ok
            print("  Q_%s × view=%-8s gold 不可见 %d/%d %s"
                  % (role, view, missed, len(_QUERY_SETS[role]),
                     "" if this_ok else "  <-- 泄漏"))

        # ---------- H5 判定 ----------
        print("\n==== H5 判定 ====")
        print("  各对齐臂 token 下降      : %s" % ("PASS" if token_pass else "FAIL"))
        print("  各对齐臂 命中率不降      : %s" % ("PASS" if hit_pass else "FAIL"))
        print("  隔离跑 无泄漏（辅助证据）: %s" % ("PASS" if iso_pass else "FAIL"))
        if not (token_pass and hit_pass):
            print("\n权衡（如实报告，不作单向通过声明）：")
            print("  存在「token 未下降或命中率下降」的对齐臂——")
            print("  上表数字为准；禁止为凑指标调规则表后不复跑。")
        ok = token_pass and hit_pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
