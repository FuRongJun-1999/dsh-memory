# -*- coding: utf-8 -*-
"""安全与健壮性守卫（Refs #1005）：profiles 密级/私密域 fail-closed 隔离、非破坏性 limit、dossier.merge 防御式合入。

# 功能名：test_profiles_security_and_dossier —— 资料卡构建密级与私密域隔离 / limit 非破坏性 / dossier 异构字段容错
# 生效条件：改动 md_cg/profiles.py 或 md_cg/dossier.py 后
# 子功能：
#   ① S1 密级与加密 fail-closed：secret / private / 变体写法 / restricted / 未知密级 / fm.encrypted / ENC_PREFIX 均不得聚合进明文 profile-* 卡，且 guest 无法读到任何泄密片段；
#   ② S2 私密域隔离：带 域:私密（含索引陈旧仅 frontmatter 带标签、以及 diary 声明节点）不得进入 profile-* 卡，mdcg_recall(include_private=False) 零泄露；
#   ③ S3 退役与负路由层隔离：archived / superseded 及 rejected / unresolved / goals 节点不污染 profile-* 卡；
#   ④ L1 非破坏性 limit：limit=1 不截断源节点扫描，既有完整卡不被局部覆盖，多卡增量批写逐次收敛；
#   ⑤ D1 dossier.merge 防御式合入：list[str] / 裸 str / 混合 list[dict|str] 经历与家庭字段不崩溃且不拆字符；ISO 日期串 / 非法日期 / NaN 的 年龄.t 安全比序且不丢历史；profiles.build 端到端渲染不崩。
# 执行：python -X utf8 -m md_cg.test_profiles_security_and_dossier
# 验证方式：全程隔离临时目录（不触宿主 ~/.dsh 或 ~/.mdcg），零裸 nodes 迭代（过 test_h4_sustain_snapshot），全绿退出 0
# 不适用条件：不覆盖外部 LLM 抽取质量
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time

# ── 隔离前置：在 import md_cg 之前切开辅助目录与哑主密钥，避免触碰宿主 ~/.mdcg ──
_TMP = tempfile.mkdtemp(prefix="prof_sec_guard_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "cd" * 32  # dummy test key (never touches host master.key)
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP, "tokens.json")
os.environ["MDCG_WRITE_GATE"] = "warn"
os.makedirs(os.environ["MDCG_AUX_ROOT"], exist_ok=True)
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_SESSION",
           "DSH_SESSION_ID", "MDCG_LEGACY_ENV_AUTH", "MDCG_LEGACY_ENV_ADMIN",
           "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_INCLUDE_PRIVATE"):
    os.environ.pop(_k, None)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from . import crypto, dossier, mcp_server as M, profiles  # noqa: E402
from .mdcos import MdCGOS, MdCGSecure  # noqa: E402
from .security import Principal  # noqa: E402

_PASS = 0
_FAIL = []


# 生效条件：记录单条断言并打印 PASS/FAIL
def _chk(cond: bool, label: str, detail="") -> None:
    global _PASS
    if cond:
        _PASS += 1
        print("  PASS " + label)
    else:
        _FAIL.append(label)
        print("  FAIL " + label + ("  · " + str(detail)[:220] if detail else ""))


# 生效条件：返回 cg 索引中所有 profile-* 节点 id（按 H-4 纪律先取快照再迭代）
def _profile_ids(cg) -> list:
    return [nid for nid in list((cg.index.get("nodes") or {}).keys())
            if str(nid).startswith(profiles.PREFIX)]


def _test_security_and_private_domain(tmp: str) -> None:
    print("\n== [S1-S3] profiles.build / op=profiles 密级、加密、私密域与退役/负路由层隔离 ==")
    root = os.path.join(tmp, "sec_root")
    owner = Principal(tenant="default", actor="owner", role="designer",
                      clearance="secret", can_write=True, can_admin=True,
                      session="sess_owner")
    guest = Principal(tenant="default", actor="guest", role="guest",
                      clearance="internal", can_write=False, can_admin=False,
                      session="sess_guest")
    cg_owner = MdCGSecure(root, principal=owner)
    cg_guest = None
    try:
        # 1) 各档敏感与私密域源节点（含 diary 声明形态与提取形态）
        cg_owner.add(
            "n_sec",
            "我叫沈知夏，DUMMY_SEC_CANARY_9911 在保密单位上班",
            layer="contextual", sensitivity="secret", importance=0.8,
        )
        cg_owner.add(
            "n_priv",
            "我叫周明朗，DUMMY_PRIV_CANARY_8811 住在西城区",
            layer="contextual", sensitivity="private", importance=0.8,
        )
        cg_owner.add(
            "n_rest",
            "我叫顾明轩，DUMMY_REST_CANARY_7733 在研究所有项目",
            layer="contextual", sensitivity="restricted", importance=0.8,
        )
        cg_owner.add(
            "n_unk",
            "我叫韩青岚，DUMMY_UNK_CANARY_6622 未知密级节点",
            layer="contextual", sensitivity="internal", importance=0.8,
        )
        cg_owner.add(
            "n_pdom_idx",
            "我叫林远舟，DUMMY_PDOM_CANARY_8822 私密日记内容",
            layer="contextual", sensitivity="internal", importance=0.8,
            tags=[M.PRIVATE_DOMAIN_TAG],
        )
        cg_owner.add(
            "n_pdom_diary",
            "DUMMY_PDOM_DIARY_CANARY_5544 私密对话",
            layer="contextual", sensitivity="internal", importance=0.8,
            tags=[M.PRIVATE_DOMAIN_TAG],
            diary={"date": "2026-06-01", "speaker": "许安然", "place": "私密小屋"},
        )
        # 索引陈旧场景：仅 frontmatter 带 域:私密 或 encrypted=True 或 ENC_PREFIX 正文
        cg_owner.add(
            "n_pdom_stale",
            "我叫程星野，DUMMY_STALE_PDOM_4433 陈旧索引私密域",
            layer="contextual", sensitivity="internal", importance=0.8,
            tags=[M.PRIVATE_DOMAIN_TAG],
        )
        cg_owner.add(
            "n_fm_enc",
            "我叫叶知秋，DUMMY_FM_ENC_3322 标了加密位",
            layer="contextual", sensitivity="internal", importance=0.8,
        )
        cg_owner.add(
            "n_raw_enc",
            crypto.ENC_PREFIX + "0123456789abcdef:dummy_ciphertext_payload" + crypto.ENC_SUFFIX,
            layer="contextual", sensitivity="internal", importance=0.8,
        )
        # 退役节点与负路由层节点
        cg_owner.add(
            "n_arch",
            "我叫谢归尘，DUMMY_ARCH_CANARY_2211 已归档旧卡",
            layer="contextual", sensitivity="internal", importance=0.8,
        )
        cg_owner.add(
            "n_rej",
            "我叫段云深，DUMMY_REJ_CANARY_1100 被拒假设",
            layer="rejected", sensitivity="internal", importance=0.5,
        )
        # 合法公开/内部节点（应正常入卡）
        cg_owner.add(
            "n_pub",
            "我叫秦渡，26岁，在江北咖啡店做结构设计",
            layer="contextual", sensitivity="internal", importance=0.8,
            tags=["对话"],
        )
        # 与 secret 节点同名人物的公开节点：卡只得含公开内容，绝不可混入 secret 片段
        cg_owner.add(
            "n_pub_same_person",
            "沈知夏说今天在展馆看画展，状态不错",
            layer="contextual", sensitivity="internal", importance=0.8,
            tags=["对话", "person:沈知夏"],
        )
        cg_owner.flush()

        # 确认 secret 节点落盘确为密文
        sec_path = os.path.join(root, cg_owner.index["nodes"]["n_sec"]["path"])
        raw_sec = open(sec_path, encoding="utf-8").read()
        _chk("DUMMY_SEC_CANARY_9911" not in raw_sec and crypto.ENC_PREFIX in raw_sec,
             "S1a 原始 secret 节点盘上已加密")

        # 构造索引陈旧/异常密级/退役场景
        cg_owner.index["nodes"]["n_unk"]["sensitivity"] = "topsecret_unknown_tier"
        cg_owner.index["nodes"]["n_pdom_stale"]["tags"] = []  # 模拟索引漏标签，盘上 fm 仍有 域:私密
        cg_owner.index["nodes"]["n_arch"]["lifecycle_state"] = "archived"
        # 在 n_fm_enc 节点盘上 frontmatter 写入 encrypted: true（索引无此位，测 post-check）
        enc_path = os.path.join(root, cg_owner.index["nodes"]["n_fm_enc"]["path"])
        enc_txt = open(enc_path, encoding="utf-8").read()
        enc_txt = enc_txt.replace('sensitivity: "internal"', 'sensitivity: "internal"\nencrypted: true', 1)
        assert "encrypted: true" in enc_txt
        with open(enc_path, "w", encoding="utf-8") as fh:
            fh.write(enc_txt)

        # 通过 MCP 工具面 cg(op="profiles", dry_run=False) 触发重建
        res = M.call_tool(cg_owner, "cg", {"op": "profiles", "dry_run": False})
        _chk(isinstance(res, dict) and res.get("dry_run") is False,
             "S1b op=profiles(dry_run=False) 正常返回", res)
        _chk(res.get("excluded_sensitive", 0) >= 5
             and (res.get("excluded_sensitive", 0) + res.get("unreadable", 0)) >= 6,
             "S1c 回执透明记录 excluded_sensitive（secret/private/restricted/unknown/fm.encrypted + ENC_PREFIX）", res)
        _chk(res.get("excluded_private_domain", 0) >= 3,
             "S2a 回执透明记录 excluded_private_domain（索引+陈旧索引+diary 私密域）", res)
        _chk(res.get("excluded_layer", 0) >= 1 and res.get("excluded_retired", 0) >= 1,
             "S3a 回执透明记录 excluded_layer 与 excluded_retired", res)

        pids = _profile_ids(cg_owner)
        all_card_text = "\n".join(
            str((cg_owner.get(pid) or {}).get("content") or "")
            for pid in pids
        )
        for canary, label in (
            ("DUMMY_SEC_CANARY_9911", "S1d secret 明文零泄露进 profile-* 卡"),
            ("DUMMY_PRIV_CANARY_8811", "S1e private 明文零泄露进 profile-* 卡"),
            ("DUMMY_REST_CANARY_7733", "S1f restricted 明文零泄露进 profile-* 卡"),
            ("DUMMY_UNK_CANARY_6622", "S1g 未知密级明文零泄露进 profile-* 卡"),
            ("DUMMY_FM_ENC_3322", "S1h fm.encrypted=True 节点零泄露进 profile-* 卡"),
            ("dummy_ciphertext_payload", "S1i ENC_PREFIX 密文节点零泄露进 profile-* 卡"),
            ("DUMMY_PDOM_CANARY_8822", "S2b 域:私密 节点零泄露进 profile-* 卡"),
            ("DUMMY_PDOM_DIARY_CANARY_5544", "S2c 域:私密 diary 节点零泄露进 profile-* 卡"),
            ("DUMMY_STALE_PDOM_4433", "S2d 索引陈旧但 fm 带 域:私密 的节点零泄露进 profile-* 卡"),
            ("DUMMY_ARCH_CANARY_2211", "S3b archived 退役节点不进入 profile-* 卡"),
            ("DUMMY_REJ_CANARY_1100", "S3c rejected 负路由层节点不进入 profile-* 卡"),
        ):
            _chk(canary not in all_card_text, label, all_card_text[:180])

        # 确认纯敏感/私密人物未生成任何 profile-* 卡
        for forbidden_name in ("周明朗", "顾明轩", "韩青岚", "林远舟", "许安然", "程星野", "叶知秋", "谢归尘", "段云深"):
            _chk(not any(forbidden_name in pid for pid in pids),
                 "S1j 未为纯敏感/私密/退役源人物 %s 创建资料卡" % forbidden_name, pids)

        # 确认公开节点正常成卡，且同名人物沈知夏的卡仅含公开句
        _chk(profiles.card_id("person", "秦渡") in pids,
             "S1k 合法公开人物 秦渡 正常建卡", pids)
        szx_card = (cg_owner.get(profiles.card_id("person", "沈知夏")) or {}).get("content") or ""
        _chk("展馆看画展" in szx_card and "DUMMY_SEC_CANARY_9911" not in szx_card and "保密单位" not in szx_card,
             "S1l 同名人物卡只含公开句、绝不混入 secret 片段", szx_card[:180])

        # 端到端 guest 视图与 mdcg_recall(include_private=False) 验证
        cg_owner.flush()
        cg_guest = MdCGSecure(root, principal=guest)
        guest_cards_dump = json.dumps([
            cg_guest.get(pid) for pid in _profile_ids(cg_guest)
        ], ensure_ascii=False)
        _chk(
            all(c not in guest_cards_dump for c in (
                "DUMMY_SEC_CANARY_9911", "DUMMY_PRIV_CANARY_8811",
                "DUMMY_REST_CANARY_7733", "DUMMY_PDOM_CANARY_8822",
                "DUMMY_STALE_PDOM_4433",
            )),
            "S1m guest 读取所有 profile-* 卡均无任何敏感/私密域片段",
        )
        rec = M.call_tool(cg_guest, "mdcg_recall", {
            "query": "林远舟 沈知夏 顾明轩",
            "include_private": False,
            "budget_tokens": 1500,
        })
        pack_dump = json.dumps(rec.get("pack") or [], ensure_ascii=False)
        _chk(
            all(c not in pack_dump for c in (
                "DUMMY_SEC_CANARY_9911", "DUMMY_PRIV_CANARY_8811",
                "DUMMY_REST_CANARY_7733", "DUMMY_PDOM_CANARY_8822",
                "DUMMY_PDOM_DIARY_CANARY_5544", "DUMMY_STALE_PDOM_4433",
            )),
            "S2e guest mdcg_recall(include_private=False) pack 零泄露敏感与私密域片段（无 profile-* 脱密洗白卡）",
            pack_dump[:200],
        )

        # 无加密层的 MdCGOS 直接返回裸 ENC_PREFIX 正文时，profiles.build 自身仍必须 fail-closed 跳过
        raw_os_root = os.path.join(tmp, "raw_enc_os_root")
        cg_os = MdCGOS(raw_os_root, actor="test")
        cg_os.add(
            "n_os_enc",
            crypto.ENC_PREFIX + "0123456789abcdef:我叫赵潜影_DUMMY_RAW_ENC_1234" + crypto.ENC_SUFFIX,
            layer="contextual", tags=["person:赵潜影"], consistency=False,
        )
        cg_os.add(
            "n_os_ok",
            "我叫周清扬，在南宁做设计",
            layer="contextual", consistency=False,
        )
        os_res = profiles.build(cg_os, dry_run=False)
        os_pids = _profile_ids(cg_os)
        _chk(os_res.get("excluded_sensitive", 0) == 1
             and not any("赵潜影" in p for p in os_pids)
             and profiles.card_id("person", "周清扬") in os_pids,
             "S1o 裸 MdCGOS 上 ENC_PREFIX 正文同样被 profiles.build 拦截并计入 excluded_sensitive",
             (os_res, os_pids))

        # 额外验 _is_sensitive_for_profiles 写法变体（大小写/空白/非字符串）
        _chk(
            profiles._is_sensitive_for_profiles(" Private ")
            and profiles._is_sensitive_for_profiles("SECRET\n")
            and profiles._is_sensitive_for_profiles("restricted")
            and profiles._is_sensitive_for_profiles("unknown_tier")
            and profiles._is_sensitive_for_profiles(123)
            and not profiles._is_sensitive_for_profiles("internal")
            and not profiles._is_sensitive_for_profiles("PUBLIC")
            and not profiles._is_sensitive_for_profiles(None)
            and not profiles._is_sensitive_for_profiles(""),
            "S1n _is_sensitive_for_profiles 写法变体与非法值均 fail-closed",
        )
    finally:
        cg_owner.close()
        if cg_guest is not None:
            cg_guest.close()


def _test_non_destructive_limit(tmp: str) -> None:
    print("\n== [L1] profiles.build limit=1 非破坏性守卫 ==")
    root = os.path.join(tmp, "limit_root")
    cg = MdCGOS(root, actor="test")
    t1 = time.mktime(time.strptime("2026-04-01", "%Y-%m-%d"))
    t2 = time.mktime(time.strptime("2026-05-01", "%Y-%m-%d"))
    t3 = time.mktime(time.strptime("2026-06-01", "%Y-%m-%d"))
    cg.add("n1", "我叫沈知夏，24岁，刚来这边发展", created_at=t1, consistency=False)
    cg.add("n2", "沈知夏说她住在南京，周末常去玄武湖", created_at=t2, tags=["person:沈知夏"], consistency=False)
    cg.add("n3", "沈知夏说她在星海工坊做木工设计", created_at=t3, tags=["person:沈知夏"], consistency=False)

    full = profiles.build(cg, dry_run=False)
    pid = profiles.card_id("person", "沈知夏")
    before = (cg.get(pid) or {}).get("content") or ""
    _chk(full["written"] >= 1 and "南京" in before and "星海" in before and before.count("（来源 ") == 3,
         "L1a 全量构建后 沈知夏 卡含全部 3 条事实（南京+星海）", before[:160])

    # 以 limit=1 再次构建：绝不可用局部扫描覆盖既有完整卡
    lim1 = profiles.build(cg, dry_run=False, limit=1)
    after = (cg.get(pid) or {}).get("content") or ""
    _chk(after == before and "南京" in after and "星海" in after and after.count("（来源 ") == 3,
         "L1b limit=1 不破坏既有完整卡（3 条事实与档案完整保留）", (lim1, after[:160]))

    # 新增第 2 个实体 + 给沈知夏追加 1 条新事实，测试 limit=1 批写上限与收敛性
    cg.add("n4", "沈知夏说九月开始学陶艺", created_at=t3 + 86400, tags=["person:沈知夏"], consistency=False)
    cg.add("n5", "我叫陆明川，在杭州西湖茶馆工作", created_at=t3 + 172800, consistency=False)
    cg.add("n6", "陆明川说周末在杭州教书法", created_at=t3 + 259200, tags=["person:陆明川"], consistency=False)

    step1 = profiles.build(cg, dry_run=False, limit=1)
    _chk(step1["written"] == 1 and step1.get("truncated") is True and step1.get("skipped_limit", 0) >= 1,
         "L1c 多张待更新卡时 limit=1 仅写 1 张且显式标记 truncated/skipped_limit", step1)
    # 已被写入的那张卡必须是完整卡（不能缺源节点）
    szx_mid = (cg.get(pid) or {}).get("content") or ""
    lmc_mid = (cg.get(profiles.card_id("person", "陆明川")) or {}).get("content") or ""
    _chk("南京" in szx_mid and "星海" in szx_mid,
         "L1d 批写第一步期间 沈知夏 既有事实未丢失", szx_mid[:140])
    if lmc_mid:
        _chk("茶馆" in lmc_mid and "书法" in lmc_mid,
             "L1e 若先写 陆明川 则该卡已含全部 2 条源事实（非截断卡）", lmc_mid[:140])

    # 连续以 limit=1 跑完，最终所有卡均完整收敛
    for _ in range(10):
        st = profiles.build(cg, dry_run=False, limit=1)
        if not st.get("truncated"):
            break
    szx_end = (cg.get(pid) or {}).get("content") or ""
    lmc_end = (cg.get(profiles.card_id("person", "陆明川")) or {}).get("content") or ""
    _chk("南京" in szx_end and "星海" in szx_end and "陶艺" in szx_end and szx_end.count("（来源 ") == 4,
         "L1f 批写收敛后 沈知夏 含全部 4 条事实", szx_end[:180])
    _chk("茶馆" in lmc_end and "书法" in lmc_end and lmc_end.count("（来源 ") == 2,
         "L1g 批写收敛后 陆明川 含全部 2 条事实", lmc_end[:180])

    # dry_run=True + limit=1 同样有界且不落盘
    dry_lim = profiles.build(cg, dry_run=True, limit=1)
    _chk(dry_lim["written"] == 0 and dry_lim["cards"] == 1 and dry_lim.get("truncated") is True,
         "L1h dry_run=True limit=1 预览有界且不写盘", dry_lim)


def _test_dossier_merge_defensive(tmp: str) -> None:
    print("\n== [D1] dossier.merge 防御式 schema 容错与端到端建卡 ==")
    # 1) list[str] 经历合并（去重且不报 AttributeError）
    m1 = dossier.merge({}, {"经历": {"value": ["在南京做结构设计"], "w": 2}})
    m1 = dossier.merge(m1, {"经历": {"value": ["在南京做结构设计", "在星海工坊做学徒"], "w": 3}})
    items1 = (m1.get("经历") or {}).get("value") or []
    _chk(items1 == ["在南京做结构设计", "在星海工坊做学徒"] and m1["经历"].get("w") == 3,
         "D1a list[str] 经历合并去重、不崩且抬高权重", m1)

    # 2) 裸 str 与 list[dict] 混合合入（不拆单字符、不丢任一方）
    m2 = dossier.merge({"经历": "曾在南宁实习"}, {"经历": [{"单位": "星海工坊", "职位": "学徒", "_raw": "原文1"}]})
    m2 = dossier.merge(m2, {"经历": {"value": [{"单位": "星海工坊", "职位": "学徒", "_raw": "原文2"}, "曾在南宁实习"]}})
    items2 = (m2.get("经历") or {}).get("value") or []
    _chk(len(items2) == 2 and "曾在南宁实习" in items2 and isinstance(items2[1], dict) and items2[1].get("_raw") == "原文1",
         "D1b 裸 str 与 list[dict] 混合合并：不拆字符、不丢数据、保留首条 _raw", items2)

    # 3) 年龄.t 为 ISO 日期字符串（降序补录不回退，升序正常更新）
    m3 = dossier.merge({}, {"年龄": {"value": 28, "t": "2026-06-01", "w": 2}})
    m3 = dossier.merge(m3, {"年龄": {"value": 27, "t": "2025-05-15", "w": 2}})
    _chk(m3["年龄"]["value"] == 28
         and any(x.get("value") == 27 for x in (m3.get("_history") or {}).get("年龄", [])),
         "D1c ISO 字符串 t 补录更早陈述（2025-05-15 < 2026-06-01）不回退且进 _history", m3)
    m3 = dossier.merge(m3, {"年龄": {"value": 29, "t": "2026-09-01T10:30:00Z", "w": 2}})
    _chk(m3["年龄"]["value"] == 29
         and any(x.get("value") == 28 for x in (m3.get("_history") or {}).get("年龄", [])),
         "D1d ISO 字符串 t 更晚陈述（2026-09-01T10:30:00Z）正常更新且旧值进 _history", m3)

    # 4) 畸形时间戳（非日期串 / NaN / inf / bool）绝不抛 ValueError/TypeError
    m4 = dossier.merge({"年龄": {"value": 30, "t": "invalid-date", "w": 2}},
                       {"年龄": {"value": 31, "t": float("nan"), "w": 2}})
    m4 = dossier.merge(m4, {"年龄": {"value": 32, "t": True, "w": 2}})
    _chk(m4["年龄"]["value"] == 32, "D1e 非法日期/NaN/bool 时间戳安全合入不崩溃", m4)

    # 5) 不就地修改调用方 old dict
    orig_old = {"姓名": {"value": "沈知夏", "w": 1}, "经历": {"value": ["A"]}}
    merged = dossier.merge(orig_old, {"姓名": {"value": "沈知夏", "w": 3}, "经历": {"value": ["B"]}})
    _chk(orig_old["姓名"]["w"] == 1 and orig_old["经历"]["value"] == ["A"]
         and merged["姓名"]["w"] == 3 and merged["经历"]["value"] == ["A", "B"],
         "D1f merge 不就地污染调用方 old 字典", (orig_old, merged))

    # 6) 端到端 profiles.build + render 消费 list[str] 经历与 ISO 年龄.t
    root = os.path.join(tmp, "dos_e2e_root")
    cg = MdCGOS(root, actor="test")
    cg.add(
        "d1", "在南京建筑所做绘图，也在星海工坊做兼职",
        diary={"date": "2026-06-01", "speaker": "苏晚晴"},
        extra={"dossier": {
            "姓名": "苏晚晴",
            "年龄": {"value": 28, "t": "2026-06-01"},
            "经历": ["在南京建筑所做绘图", "在星海工坊做兼职"],
        }},
        consistency=False,
    )
    cg.add(
        "d2", "曾在南京建筑所做绘图，也在城北书店帮忙",
        diary={"date": "2025-05-01", "speaker": "苏晚晴"},
        extra={"dossier": {
            "年龄": {"value": 27, "t": "2025-05-01"},
            "经历": ["在南京建筑所做绘图", "在城北书店帮忙"],
        }},
        consistency=False,
    )
    st = profiles.build(cg, dry_run=False)
    card = (cg.get(profiles.card_id("role", "苏晚晴")) or {}).get("content") or ""
    _chk(st["written"] >= 1
         and "年龄：28（2026-06）" in card
         and "在南京建筑所做绘图" in card
         and "在星海工坊做兼职" in card
         and "在城北书店帮忙" in card
         and card.count("- 在南京建筑所做绘图") == 1,
         "D1g 端到端 profiles.build 正确合入 list[str] 经历（去重）与 ISO 年龄.t（渲染年月且不回退）",
         card[:260])


def main() -> int:
    try:
        _test_security_and_private_domain(_TMP)
        _test_non_destructive_limit(_TMP)
        _test_dossier_merge_defensive(_TMP)
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    print("\nprofiles 安全与 dossier 守卫：%d 通过 / %d 失败" % (_PASS, len(_FAIL)))
    if _FAIL:
        print("失败项：", _FAIL)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
