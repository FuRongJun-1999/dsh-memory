# -*- coding: utf-8 -*-
"""注入用例登记表（registry）：case_id → 期望 verdict 与缺口留档编号。

EXPECTED_GAP 机制：expected_verdict="gap" 的用例是**登记在册的已知缺口基线**
（对应 docs/eval/缺陷挖掘_自主迭代_v15/v16/v17.md 留档池编号或 v0.3 落地清单
条目）——套件实跑确认缺口仍在 → 与登记一致 → 全绿退出 0（不红 CI）；
一旦缺口被修复（防线落地 → 观测 verdict 转 pass），与登记不一致 → 套件亮红，
提示把该 case 的登记改写为 pass（缺口结案留痕）。

expected_verdict="pass" 的用例构成回归守卫：未来防线弱化 → 观测转 gap/fail
→ 套件亮红（新 gap 未登记或 pass 用例回归，退出 1）。
"""

REGISTRY = {
    # S9 时钟回拨：新鲜度层单层可被洗白（A2 无单调锚），端到端被 P5 三层判据兜住
    # → 防线按预期 → pass；残余风险（pid 复用+同映像=三层全过假活）为 P1-6 待建面输入
    "FI-R01": {"expected_verdict": "pass", "gap_tag": None,
               "title": "时钟回拨：serve 心跳新鲜度层拆层观测"},
    # S1 杀 serve：T0 崩溃类可观测→可恢复（recover_orphans 诚实标 error，A4）
    "FI-R02": {"expected_verdict": "pass", "gap_tag": None,
               "title": "杀 serve 后重启：recover_orphans 崩溃恢复"},
    # T4/T12 静默改写：伪造 result.json ok=true 被采信（classify_result 只读盘面）
    # → 判据面可被能写盘面的组件伪造 = P11 完整性锚待建面基线（无 v15-v17 留档
    #   编号；与 verify_runner passed>0 门互不覆盖，读码在案）
    "FI-R03": {"expected_verdict": "gap", "gap_tag": "NEW(P11-待建)",
               "title": "伪造 result.json ok=true：终态判据被静默改写"},
    # P11 完整性锚：payload 单字节翻转必被端到端 HMAC 捕获且能定位行
    "FI-R04": {"expected_verdict": "pass", "gap_tag": None,
               "title": "WAL payload 字节翻转：HMAC 验签捕获与定位"},
    # P11 覆盖篡改不覆盖遗漏：整行删除对单条 HMAC 验签器不可检 = 缺口基线
    # （对应 v0.3 落地清单 P0-2 幂等键/seq 连续性判据、矩阵 T2/T7 幂等🟡格）
    "FI-R05": {"expected_verdict": "gap", "gap_tag": "NEW(P0-2/seq连续性)",
               "title": "WAL 整行删除：验签器丢失不可检"},
    # swarm 半边同 R05（无次序判据，gap）；hive submit 侧依赖 fail-fast 有效拦截（红）
    "FI-R06": {"expected_verdict": "gap", "gap_tag": "NEW(P0-2/seq连续性)",
               "title": "WAL 行乱序不可检 + submit 依赖 fail-fast 拦截"},
    # 领取面 claim=create_new 原子锁吸收重复投递（N 投递=1 执行）；次观测
    # （提交面无 content-hash 幂等键）为 P0-2 已知基线记录，不计入本格 verdict
    "FI-R07": {"expected_verdict": "pass", "gap_tag": None,
               "title": "双 serve 竞争领取：claim 原子锁恰好一次"},
    # S8 平台默认值：DEFAULT_SECRET 公开常量可伪造合法签名 = N143（v17.md:85
    # 留档，owner=rust，密钥生命周期决策 deferred）
    "FI-R08": {"expected_verdict": "gap", "gap_tag": "N143",
               "title": "公开缺省密钥伪造合法签名 WAL"},
    # P2 原子写：读者瞬态句柄对撞 os.replace → 重试窗内读者恒读完整态
    "FI-R09": {"expected_verdict": "pass", "gap_tag": None,
               "title": "写面对撞：读者独占句柄撞 os.replace 重试窗"},

    # ==================== mdcg 面（md_cg 记忆本体） ====================
    # S9 时钟回拨：TTL 以壁钟为唯一时基、无单调锚（tokens.py:371/:407-411）——
    # 回拨 1h 应逐出令牌仍通过 verify；对照格正确时钟拦截有效。v0.1:62 公理7/
    # §2.9 承重面（预防性建模，无缺陷池编号），单调锚/外部时间锚属待建面输入
    "FI-M01": {"expected_verdict": "gap", "gap_tag": "v0.1§2.9承重面(A2单调锚待建)",
               "title": "时钟回拨：TTL 壁钟唯一时基被洗白"},
    # S1 瞬态读失败被固化入检索缓存（N134，v16.md:86）——一次 OSError 固化为
    # 「节点从检索面消失」，get 能读/search 搜不到撕裂；P1 fail-closed 缺席
    "FI-M02": {"expected_verdict": "gap", "gap_tag": "N134",
               "title": "瞬态读失败固化为检索面永久消失"},
    # S2 写面漏标脏（N133，v16.md:85）——reinforce 写盘成功仅改内存 entry，
    # 默认开读缓存把旧 fm 永久判新鲜；修复先例 mdcg.py:3242 在案
    "FI-M03": {"expected_verdict": "gap", "gap_tag": "N133",
               "title": "reinforce 写盘成功检索面读旧值"},
    # S3 并发对撞（N138，v16.md:90）——_lock 仅覆盖 4 处记账清单，diagnose
    # 裸迭代共享面（sustain.py:484）无锁；读码断言为确定性基线，动态捕获
    # RuntimeError 为时序敏感加分证据（未命中降级 NOTE 不虚判绿）
    "FI-M04": {"expected_verdict": "gap", "gap_tag": "N138",
               "title": "beat/heal/add 同实例并发对撞裸迭代崩溃面"},
    # S3 半程死亡：两段式对账把 kill(intent 与 outcome 之间) 收敛到如实标记
    # interrupted（A4 不假装成功）+ 对照格补 committed（R_NODE_OK）+ 幂等
    "FI-M05": {"expected_verdict": "pass", "gap_tag": None,
               "title": "杀进程于 intent 与 outcome 之间：对账如实标记"},
    # S6 伪造「已验证成功」回答：L2 hits 门拦截（done≠verified，P4/T8）
    "FI-M06": {"expected_verdict": "pass", "gap_tag": None,
               "title": "LLM 伪造已验证成功回答：L2 判据拦截"},
    # S7 空串误配静默回落（N91 同型，v17.md:102）——MDCG_TOKEN_FILE="" 与未设
    # 解析到同一路径、零告警零留痕；P1 fail-closed 缺席（令牌面落点清单输入）
    "FI-M07": {"expected_verdict": "gap", "gap_tag": "N91同型",
               "title": "空串 MDCG_TOKEN_FILE 静默回落默认路径"},
    # S4 改自身判据面：冻结凭证 digest 翻转 → A3 承重墙比对失败（P4/T5/T3，
    # verdict 作废路径成立＝防线有效）
    "FI-M08": {"expected_verdict": "pass", "gap_tag": None,
               "title": "冻结凭证 digest 翻转：A3 承重墙比对失败"},
    # S5 调用方越权：guest 无写权限直写被 AccessDenied 显式拒绝、零半成品
    # （T8/P8；对照 designer 放行——闸只拦资格不拦功能）
    "FI-M09": {"expected_verdict": "pass", "gap_tag": None,
               "title": "guest 越权写入：层写权限闸显式拒绝"},
}
