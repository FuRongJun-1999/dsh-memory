# -*- coding: utf-8 -*-
"""md_cg · P6 验收：离线固化（反思单元 → 白箱闸门 → 验证单元 → 固化）

运行：python -m md_cg.test_p6_consolidate

验证口径（对齐工作纪律第 3/5 条「不猜测、未经验证不固化」）：
  1. 候选解析：JSON 容错 + 字段别名（子内容→子功能）
  2. grounding：幻觉候选被拦截（正文无据即 REJECT）
  3. replay：正例召回 / 负例分离 / 无冲突；负条件自否定正文 → 拒绝
  4. 验证单元裁决：**只能否决、不能新增**；全否 → REJECT
  5. 角色配置：反思=DeepSeek、验证=GLM，且凭证不跨厂商挪用
  6. 全链路：dry-run 不写盘；apply 写盘；四要素 + 验证方式落盘；provenance 可审计
  7. 索引一致性：新增 `# 不适用条件：`/`# 验证方式：` 后索引同步
  8. 幂等 + 不覆盖人工既有字段
  9. 验证单元不可用 → DEFER（不写盘）；--no-verify 降级可跑通
 10. 验证方式补全（零 LLM）+ 与生产 _path_semantic 的一致性回归
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

from . import nodefile
from .consolidate import (BASIS_TEMPLATE, REFLECT_ROLE, VERIFY_ROLE, body_text,
                          consolidate, existing_fields, fill_verification_basis,
                          grounding_filter, grounding_score, narrow_by_verdict,
                          parse_candidate, parse_verdict, replay_check,
                          role_config)
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


# 待补节点：只有功能名 + 正文，四要素全缺
BODY = ("# 功能名：微分方程应用\n"
        "微分方程应用：建模与求解，使用数值方法迭代求解，需给定边界条件\n")

# 反思单元候选：三条有据 + 一条域外负条件（与正文共享「边界条件」但整体域外）
CAND = {
    "生效条件": ["微分方程", "数值方法"],
    "子功能": ["建模", "求解"],
    "执行": "使用数值方法迭代求解",
    "不适用条件": ["边界条件缺失"],
}
CAND_JSON = json.dumps(CAND, ensure_ascii=False)
REFLECT_MODEL = "deepseek-v4.1-flash-expires-on-0910"
VERIFY_MODEL = "glm-5.3-flash"
BASIS = BASIS_TEMPLATE.format(reflect=REFLECT_MODEL, verify=VERIFY_MODEL)


def fake_reflect(prompt):
    """反思单元：带代码围栏，检验解析容错。"""
    return "```json\n" + CAND_JSON + "\n```"


def make_verify(drop=(), keep=None, extra=None):
    """构造验证单元：默认全部放行；可指定删除/收窄/额外字段。"""
    def _fn(prompt):
        out = {}
        for f, v in CAND.items():
            terms = v if isinstance(v, list) else [v]
            if keep is not None and f in keep:
                out[f] = {"keep": list(keep[f]), "drop": [],
                          "reason": "收窄"}
            else:
                out[f] = {"keep": [t for t in terms if t not in drop],
                          "drop": [t for t in terms if t in drop],
                          "reason": "逐条核验"}
        if extra:
            out.update(extra)
        return json.dumps(out, ensure_ascii=False)
    return _fn


fake_verify = make_verify()


def new_root(n=1):
    root = tempfile.mkdtemp(prefix="mdcg_p6_")
    cg = MdCGOS(root)
    for i in range(n):
        cg.add(f"n{i + 1}", BODY, tags=["数学"])
    cg.flush()
    rel = {f"n{i + 1}": cg.get(f"n{i + 1}")["path"] for i in range(n)}
    cg.close()
    return root, rel


def main():
    # ---------------- 1. 候选解析 ----------------
    print("\n【1】候选解析（JSON 容错 + 字段别名）")
    c = parse_candidate("```json\n" + CAND_JSON + "\n```")
    check("解析带围栏的 JSON", c.get("生效条件") == ["微分方程", "数值方法"], str(c.get("生效条件")))
    c2 = parse_candidate('前置说明 {"子内容": ["甲","乙"], "如何执行": "先做甲", '
                         '"适用条件": ["丙"], "不适用条件": ["丁"]} 后置说明')
    check("别名：子内容→子功能", c2.get("子功能") == ["甲", "乙"], str(c2.get("子功能")))
    check("别名：如何执行→执行", c2.get("执行") == "先做甲", str(c2.get("执行")))
    check("别名：适用条件→生效条件", c2.get("生效条件") == ["丙"], str(c2.get("生效条件")))
    check("垃圾输入 → 空字典", parse_candidate("这不是 JSON") == {})
    check("超长候选被丢弃", parse_candidate('{"执行": "' + "长" * 60 + '"}') == {})

    # ---------------- 2. grounding：幻觉拦截 ----------------
    print("\n【2】grounding 支撑度（正文无据即幻觉）")
    check("有据短语支撑度 = 1.0", grounding_score("微分方程", BODY) == 1.0,
          str(grounding_score("微分方程", BODY)))
    check("幻觉短语支撑度 = 0.0", grounding_score("拉普拉斯变换", BODY) == 0.0,
          str(grounding_score("拉普拉斯变换", BODY)))
    kept, gdet = grounding_filter(
        {"生效条件": ["微分方程", "拉普拉斯变换"], "执行": "使用数值方法迭代求解"}, BODY)
    check("grounding 丢弃幻觉、保留有据",
          kept.get("生效条件") == ["微分方程"] and "拉普拉斯变换" not in str(kept),
          str(kept.get("生效条件")))
    check("grounding 明细可审计", gdet["生效条件"]["scores"]["拉普拉斯变换"] == 0.0,
          str(gdet["生效条件"]["scores"]))
    check("无据字段整体被丢弃",
          "执行" not in grounding_filter({"执行": "完全无关的编造内容"}, BODY)[0])
    check("body_text 剥离 CCG 声明行（声明不是正文）",
          body_text("# 功能名：甲\n# 不适用条件：乙\n丙丁\n") == "丙丁\n",
          repr(body_text("# 功能名：甲\n# 不适用条件：乙\n丙丁\n")))

    # ---------------- 3. replay：条件稳定性 ----------------
    print("\n【3】replay 回放（正例召回 + 负例分离 + 无冲突）")
    ok = replay_check(["微分方程", "数值方法"], ["边界条件缺失"], BODY)
    check("合法候选 → replay 通过", ok["ok"] is True, str(ok))
    check("  正例召回成立", ok["pos_recall"] is True)
    check("  负例分离成立", ok["neg_separated"] is True)
    bad_neg = replay_check(["建模"], ["使用数值方法迭代求解"], BODY)
    check("负条件与正文强相关 → 拒绝", bad_neg["neg_separated"] is False, str(bad_neg))
    conflict = replay_check(["微分方程"], ["微分方程"], BODY)
    check("生效/不适用互相覆盖 → 拒绝", conflict["no_conflict"] is False, str(conflict))

    # ---------------- 4. 验证单元：只能否决 ----------------
    print("\n【4】验证单元裁决（只能否决、不能新增）")
    v = parse_verdict(json.dumps({"生效条件": {"keep": ["微分方程"], "drop": ["数值方法"],
                                               "reason": "无据"}, "子功能": ["建模"]},
                                 ensure_ascii=False))
    check("裁决解析：dict 形态", v["生效条件"]["keep"] == ["微分方程"]
          and v["生效条件"]["drop"] == ["数值方法"], str(v["生效条件"]))
    check("裁决解析：数组形态 = 全 keep", v["子功能"]["keep"] == ["建模"]
          and v["子功能"]["has_keep"] is True, str(v["子功能"]))
    check("裁决解析：垃圾输入 → 空", parse_verdict("nope") == {})

    n_kept, n_drop = narrow_by_verdict(
        {"生效条件": ["A", "B", "C"], "子功能": ["X"], "执行": "E"},
        {"生效条件": {"keep": ["A", "Z"], "drop": ["B"], "has_keep": True,
                      "reason": "r"}})
    check("keep 取交集（无法新增 Z）", n_kept["生效条件"] == ["A"], str(n_kept))
    check("drop 生效", "B" in n_drop["生效条件"]["terms"], str(n_drop))
    check("未表态字段保留（沉默≠否决）", n_kept.get("子功能") == ["X"]
          and n_kept.get("执行") == "E")
    only_drop, _ = narrow_by_verdict(
        {"生效条件": ["A", "B"]},
        {"生效条件": {"drop": ["B"], "has_keep": False, "reason": ""}})
    check("只给 drop 时不误删", only_drop["生效条件"] == ["A"], str(only_drop))
    all_no, _ = narrow_by_verdict(
        {"生效条件": ["A"]},
        {"生效条件": {"keep": [], "has_keep": True, "reason": "全否"}})
    check("显式空 keep → 全部否决", all_no == {}, str(all_no))
    check("验证单元凭空新增的条目不会落地",
          "凭空新增" not in str(narrow_by_verdict(
              {"子功能": ["建模"]},
              {"子功能": {"keep": ["建模", "凭空新增"], "has_keep": True}})[0]))

    # ---------------- 5. 角色配置 ----------------
    print("\n【5】角色配置（反思=DeepSeek / 验证=GLM，凭证不跨厂商）")
    saved = {k: os.environ.pop(k, None) for k in (
        "MDCG_LLM_KEY", "MDCG_LLM_MODEL", "MDCG_LLM_BASE", "MDCG_REFLECT_MODEL",
        "MDCG_REFLECT_BASE", "MDCG_REFLECT_KEY", "MDCG_VERIFY_MODEL",
        "MDCG_VERIFY_BASE", "MDCG_VERIFY_KEY", "ZHIPU_API_KEY", "ZHIPUAI_API_KEY",
        "GLM_API_KEY", "BIGMODEL_API_KEY", "DEEPSEEK_API_KEY")}
    try:
        os.environ["DEEPSEEK_API_KEY"] = "sk-fake-deepseek"
        check("反思单元默认模型", role_config(REFLECT_ROLE)[0] == REFLECT_MODEL,
              role_config(REFLECT_ROLE)[0])
        check("验证单元默认模型", role_config(VERIFY_ROLE)[0] == VERIFY_MODEL,
              role_config(VERIFY_ROLE)[0])
        check("反思单元可用 DeepSeek 凭证",
              role_config(REFLECT_ROLE)[2] == "sk-fake-deepseek")
        check("验证单元**不**挪用 DeepSeek 凭证",
              role_config(VERIFY_ROLE)[2] is None, str(role_config(VERIFY_ROLE)[2]))
        check("验证单元默认网关为智谱",
              "bigmodel" in role_config(VERIFY_ROLE)[1], role_config(VERIFY_ROLE)[1])
        os.environ["ZHIPU_API_KEY"] = "sk-fake-glm"
        check("验证单元识别 ZHIPU_API_KEY 别名",
              role_config(VERIFY_ROLE)[2] == "sk-fake-glm")
        os.environ["MDCG_REFLECT_MODEL"] = "deepseek-v4-pro"
        check("环境变量可覆盖默认模型",
              role_config(REFLECT_ROLE)[0] == "deepseek-v4-pro")
    finally:
        for k, val in saved.items():
            if val is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = val

    # ---------------- 6. 全链路 ----------------
    print("\n【6】全链路（dry-run 不写盘 → apply 写盘）")
    root, rel = new_root(1)
    try:
        node_path = os.path.join(root, rel["n1"])
        with open(node_path, encoding="utf-8") as f:
            before = f.read()
        check("初始节点四要素全缺", len(existing_fields(*nodefile.loads(before))) == 0)

        rep = consolidate(root, reflect_fn=fake_reflect, verify_fn=fake_verify,
                          reflect_model=REFLECT_MODEL, verify_model=VERIFY_MODEL,
                          verification_basis=BASIS)
        check("dry-run 判定 ACCEPT", rep["accepted"] == 1, str(rep["accepted"]))
        check("dry-run 不写盘", rep["written"] == 0
              and open(node_path, encoding="utf-8").read() == before)
        check("报告记录双模型",
              rep["reflect"] and rep["verify"]
              and rep["reflect_model"] == REFLECT_MODEL
              and rep["verify_model"] == VERIFY_MODEL, str(rep["reflect_model"]))

        rep2 = consolidate(root, apply=True, reflect_fn=fake_reflect,
                           verify_fn=fake_verify, reflect_model=REFLECT_MODEL,
                           verify_model=VERIFY_MODEL, verification_basis=BASIS)
        check("apply 写盘 1 个节点", rep2["written"] == 1, str(rep2["written"]))
        fm, content = nodefile.loads(open(node_path, encoding="utf-8").read())
        cm = (fm.get("state_attributes") or {}).get("comment") or {}
        check("生效条件落盘", cm.get("生效条件") == "微分方程；数值方法", str(cm.get("生效条件")))
        check("子功能落盘", cm.get("子功能") == "建模；求解", str(cm.get("子功能")))
        check("执行落盘", cm.get("执行") == "使用数值方法迭代求解", str(cm.get("执行")))
        check("不适用条件落盘", cm.get("不适用条件") == "边界条件缺失", str(cm.get("不适用条件")))
        check("正文写入 CCG 行", all(f"# {f}：" in content for f in
                                ("生效条件", "子功能", "执行", "不适用条件")))
        check("验证方式落盘", cm.get("验证方式") == BASIS, str(cm.get("验证方式")))
        check("验证方式写入正文", f"# 验证方式：{BASIS}" in content)
        check("frontmatter 枚举落到 other", fm.get("verification_basis") == "other",
              str(fm.get("verification_basis")))
        check("frontmatter.non_applicable_conditions 同步",
              fm.get("non_applicable_conditions") == ["边界条件缺失"],
              str(fm.get("non_applicable_conditions")))
        prov = fm.get("llm_consolidation") or {}
        check("provenance 记录双模型与哈希",
              prov.get("reflect", {}).get("model") == REFLECT_MODEL
              and prov.get("verify", {}).get("model") == VERIFY_MODEL
              and bool(prov.get("source_hash"))
              and bool(prov.get("reflect", {}).get("prompt_hash"))
              and bool(prov.get("verify", {}).get("prompt_hash")),
              str({k: prov.get(k, {}).get("model") for k in ("reflect", "verify")}))
        check("provenance 不含正文载荷（只存哈希）",
              "微分方程应用：建模" not in json.dumps(prov, ensure_ascii=False))
        check("CCG 完整度提升（含验证方式）",
              nodefile.ccg_completeness(content)["complete"] is True,
              str(nodefile.ccg_completeness(content)["required_present"]))

        # ---------------- 7. 索引一致性 ----------------
        print("\n【7】索引一致性（正文变更后重建）")
        cg2 = MdCGOS(root)
        e = cg2.index["nodes"].get("n1") or {}
        check("has_neg_conditions 已同步", e.get("has_neg_conditions") is True,
              str(e.get("has_neg_conditions")))
        check("content_hash 已更新", e.get("content_hash") != "", str(e.get("content_hash")))
        cg2.close()

        # ---------------- 8. 幂等 + 不覆盖 ----------------
        print("\n【8】幂等与「不覆盖人工既有字段」")
        rep3 = consolidate(root, apply=True, reflect_fn=fake_reflect,
                           verify_fn=fake_verify, verification_basis=BASIS)
        check("二次运行幂等（无新增）",
              rep3["accepted"] == 0 and rep3["skipped_complete"] >= 1,
              f"accepted={rep3['accepted']} skipped={rep3['skipped_complete']}")

        fm, content = nodefile.loads(open(node_path, encoding="utf-8").read())
        cm = fm["state_attributes"]["comment"]
        cm["执行"] = "人工写的执行方式"
        cm.pop("子功能", None)
        content = "\n".join(l for l in content.split("\n")
                            if not l.strip().startswith("# 执行")
                            and not l.strip().startswith("# 子功能"))
        with open(node_path, "w", encoding="utf-8") as f:
            f.write(nodefile.dumps(fm, content))
        rep_m = consolidate(root, apply=True, reflect_fn=fake_reflect,
                            verify_fn=fake_verify, verification_basis=BASIS)
        check("已写入的声明行不干扰 replay（回归）",
              rep_m["accepted"] == 1, str(rep_m["reasons"]))
        fm2, _ = nodefile.loads(open(node_path, encoding="utf-8").read())
        cm2 = fm2["state_attributes"]["comment"]
        check("人工字段不被覆盖", cm2.get("执行") == "人工写的执行方式", str(cm2.get("执行")))
        check("缺失字段被补齐", cm2.get("子功能") == "建模；求解", str(cm2.get("子功能")))

        # ---------------- 9. 一致性回归 ----------------
        print("\n【9】一致性回归：固化结果驱动生产 _path_semantic")
        cg3 = MdCGOS(root)
        cands = cg3._candidates()
        sem = {n["id"]: s for n, s in cg3._path_semantic("微分方程", cands)}
        sem_neg = {n["id"] for n, _ in cg3._path_semantic("边界条件缺失", cands)}
        check("正例：生效条件 → 生产路召回本节点", "n1" in sem, str(sem))
        check("负例：不适用条件 → 生产路条件级剔除", "n1" not in sem_neg, str(sem_neg))
        rrf = cg3.search_rrf("微分方程")
        check("默认四路 RRF 仍可用（未受影响）",
              isinstance(rrf, tuple) and len(rrf) == 2, str(type(rrf)))
        cg3.close()
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ---------------- 10. 验证单元不可用 → DEFER ----------------
    print("\n【10】验证单元不可用 → DEFER（纪律 5：未经验证不固化）")
    root, rel = new_root(1)
    try:
        node_path = os.path.join(root, rel["n1"])
        before = open(node_path, encoding="utf-8").read()
        rep = consolidate(root, apply=True, reflect_fn=fake_reflect,
                          reflect_model=REFLECT_MODEL, require_verify=True)
        check("无验证单元 → 全部 DEFER",
              rep["deferred"] == 1 and rep["accepted"] == 0, str(rep["reasons"]))
        check("DEFER 原因为 verify_unavailable",
              "verify_unavailable" in rep["reasons"], str(rep["reasons"]))
        check("DEFER 不写盘", open(node_path, encoding="utf-8").read() == before)
        rep2 = consolidate(root, apply=True, reflect_fn=fake_reflect,
                           require_verify=False)
        check("--no-verify 降级可跑通", rep2["accepted"] == 1 and rep2["written"] == 1,
              str(rep2["reasons"]))
        fm3, _ = nodefile.loads(open(node_path, encoding="utf-8").read())
        check("provenance 标记验证单元 skipped",
              fm3["llm_consolidation"]["verify"].get("status") == "skipped",
              str(fm3["llm_consolidation"]["verify"]))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ---------------- 11. 验证单元全否 → REJECT ----------------
    print("\n【11】验证单元否决全部候选 → REJECT")
    root, rel = new_root(1)
    try:
        node_path = os.path.join(root, rel["n1"])
        before = open(node_path, encoding="utf-8").read()
        rep = consolidate(root, apply=True, reflect_fn=fake_reflect,
                          verify_fn=make_verify(drop=(
                              "微分方程", "数值方法", "建模", "求解",
                              "使用数值方法迭代求解", "边界条件缺失")))
        check("全否 → REJECT", rep["rejected"] == 1 and rep["accepted"] == 0,
              str(rep["reasons"]))
        check("REJECT 原因为 verify_rejected",
              "verify_rejected" in rep["reasons"], str(rep["reasons"]))
        check("REJECT 不写盘", open(node_path, encoding="utf-8").read() == before)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ---------------- 12. 验证方式补全（零 LLM） ----------------
    print("\n【12】验证方式补全（零 LLM 成本）")
    root, rel = new_root(2)
    try:
        rep = fill_verification_basis(root, BASIS, apply=False)
        check("dry-run 只统计不写盘",
              rep["targeted"] == 2 and rep["written"] == 0, str(rep))
        rep2 = fill_verification_basis(root, BASIS, apply=True)
        check("apply 补齐 2 个节点", rep2["written"] == 2, str(rep2["written"]))
        fm4, content4 = nodefile.loads(
            open(os.path.join(root, rel["n1"]), encoding="utf-8").read())
        check("验证方式写入正文与 comment",
              f"# 验证方式：{BASIS}" in content4
              and (fm4["state_attributes"]["comment"]).get("验证方式") == BASIS)
        check("验证方式计入 CCG 完整度",
              "验证方式" in nodefile.ccg_completeness(content4)["required_present"])
        rep3 = fill_verification_basis(root, BASIS, apply=True)
        check("已有验证方式 → 跳过（幂等）",
              rep3["written"] == 0 and rep3["skipped_present"] == 2, str(rep3))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 68)
    print(f"通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：" + ", ".join(FAILS))
    print("=" * 68)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
