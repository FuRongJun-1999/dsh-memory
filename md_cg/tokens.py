# -*- coding: utf-8 -*-
"""md_cg · 令牌与角色权职分离（记忆 OS #3）

动机：管理权限原先来自环境变量 `MDCG_CAN_ADMIN` —— 任何能设置该进程环境的
调用方都能自授权限，且无法表达「谁可以做什么」。本模块把权限收敛为三层：

  ① 令牌（token）—— 身份与权限的唯一凭据。明文只在签发时返回一次，落盘只存
     sha256 摘要；校验失败即 fail-closed（MCP 侧拒绝启动，不降级为可用）。
  ② 角色（role）—— 职责矩阵：设计者 / 反思单元 / 验证单元 / 记录单元 /
     输出单元 / 维生系统。每个角色有各自的可写层、可执行 op、密级上限。
  ③ 派生（derive）—— 设计者令牌可派生**受限子令牌**，权限只能收窄不能放大，
     子令牌默认不可再派生。单智能体环境下用它把子代理隔离成不同单元：
     验证单元拿不到事实层写权，记录单元无法自我验证，输出单元只读。

核心私有内容保护（对应「其他单元不应越权修改」）：
  · 密级 private / secret 的内容，只有 clearance 达标的角色可写；
  · 非设计者角色的密级上限一律 internal，因此**天然无法写入核心私有内容**；
  · anchor / self 保护层只对 layers_allow 含对应层（或 "*"）的角色开放。

存储：默认 `~/.mdcg/_tokens.json`（仓库外，0600），可用 `MDCG_TOKEN_FILE`
或 `--token-file` 覆盖。与 `_tenants.json` / `master.key` 同目录约定。

零第三方依赖。
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from collections import OrderedDict
from contextlib import contextmanager

from .datapath import aux_root
from .fsutil import FileLock, atomic_write
from .security import Principal, TenantRegistry, _rank

TOKEN_ENV = "MDCG_TOKEN"
TOKEN_FILE_ENV = "MDCG_TOKEN_FILE"
DEFAULT_TOKEN_DIR = aux_root()
DEFAULT_TOKEN_FILE = os.path.join(DEFAULT_TOKEN_DIR, "_tokens.json")
PREFIX = "mdcg1"
SCHEMA = 1

# 核心私有内容：这些密级的内容不允许非设计者角色越权修改
CORE_PRIVATE_SENSITIVITIES = ("private", "secret")
# 保护层：身份锚点与自我层，只有显式授权的角色可写
CORE_LAYERS = ("anchor", "self")

# 全部可写层（与 mdcg.LAYERS 对齐）
ALL_LAYERS = ("anchor", "structural", "knowledge", "contextual", "self",
              "rejected", "unresolved", "goals")

# 认知图 op 全集（与 mcp_server._cg_call 对齐，供 ops_allow 收窄）
#   help  按需披露入口：工具面投影（见 md_cg/tool_face.py）后，被外置的完整
#         op/参数语义在此从真源取回；只读元信息，不经角色闸（不属于写/裁决面）
ALL_OPS = ("help", "info", "route", "read", "write", "goal", "task", "recent", "verify",
           "review", "forget", "protect", "identity", "consistency",
           "metacognition", "self_state", "evolution", "sustain", "scrub",
           "predict", "causal", "whitebox", "index_code", "index_doc", "ref",
           "theory", "link",
           # P0 新增（见 docs/灵枢82工具 §五工程缺口）：
           #   session  会话三件套（note/recall/compact）—— 会话中断可续接
           #   ingest   文件摄取分派（file/dir/jsonl/stat）—— 单一入口吃多种文件
           #   export   全库导出（graph/nodes/slice/stat）—— 可搬运、可灾备
           # P1 新增（见 docs/灵枢82工具 §五工程缺口）：
           #   maintain     记忆维护（importance/longterm/prefeed/separate）
           #                —— stat/prefeed 开放给写层，apply 类批量改写走 require_admin
           #   consolidate  离线固化面（promote/run）—— 批量提升走 require_admin
           # P2 新增（见 docs/灵枢82工具 §五工程缺口）：
           #   insight      洞察条件层（window/record/verify/list/report）+
           #                情景重构（reconstruct）+ 盲区学习（learn）+
           #                结构洞察（outlook）；写入 action 按 can_write 收窄，
           #                learn/apply 与批量落库走 require_admin
           "session", "ingest", "export", "maintain", "consolidate", "insight",
           # P3 新增（记忆可靠性闸，见 docs 讨论）：
           #   ccg  CCG 六要素编译器（compile/review/attest/link/recalibrate/units）
           #        —— 对话记录→六要素候选→**编外复核**→落库；裁定 A：编译者不得自证
           #        （E041 机械拒绝 verifier == compiled_by）。复核通道优先蜂巢
           #        reflect/verify 单元，不可用则提示配置或降级 harness 端子代理。
           # P4 新增（可验证记忆单元，2026-09-19）：
           #   status  验证态 / 依赖 / 双时间轴 / 履历查询（只读）
           #        —— 「它还成不成立」的读面；真源 md_cg/trust.py
           # P4 新增（三元组反查原语，阶段二 4.2，2026-09-20）：
           #   edges  按任意端 / 谓词 / 时间 + 排序分页聚合反查派生边（只读）
           #        —— 「这条记忆从哪来 / 谁由它派生」的读面；真源
           #        md_cg/provenance.py（find_edges）。**只读 op**：不含任何
           #        写入 path，故读面角色一律放行（与 status 同档）
           "ccg", "status", "edges")


class TokenError(Exception):
    """令牌无效 / 过期 / 越权派生。"""


# --------------------------------------------------------------------------
# 角色职责矩阵
# --------------------------------------------------------------------------

# 五大单元（record/reflect/verify/output/sustain）的 unit/effect/duty 与
# `identity.POSITIONS`（智能论 v3.4 §十三）同源；test_p21 有断言防漂移。
# designer / guest 是**权限角色**而非位置效应，故不参与位置推断。
ROLE_SPECS = OrderedDict([
    ("designer", {
        "label": "设计者权限载体", "unit": "设计者", "effect": "主",
        "duty": "外部用户指定的唯一主智能体：全局观测 + 管理操作 + 派生受限子令牌",
        "can_write": True, "can_admin": True, "clearance_cap": "secret",
        "layers_allow": ["*"], "ops_allow": ["*"], "delegable": True,
        "forbidden": ["无（唯一可管理与可派生角色）"],
    }),
    ("orchestr", {
        "label": "仲裁实例（蜂巢编排者）", "unit": "仲裁实例", "effect": "裁",
        "duty": "智能论 3.9 仲裁实例的令牌投影：拆解派发、裁决子代理冲突、收口归档；"
                "存在级管理权（forget/protect/anchor 写）归设计者专属，本角色不可触碰",
        "can_write": True, "can_admin": False, "clearance_cap": "internal",
        "layers_allow": ["contextual", "unresolved", "rejected"],
        "ops_allow": ["info", "route", "read", "write", "review", "recent",
                     "consistency"],
        "delegable": False,
        "forbidden": ["anchor/self/goals/knowledge 层", "private/secret 密级",
                      "forget/protect 等存在级管理操作", "继续派生子令牌"],
    }),
    ("record", {
        "label": "记录单元", "unit": "记录单元", "effect": "全",
        "duty": "保存观测、过程、结果和误差；不得自证、不得改保护层",
        "can_write": True, "can_admin": False, "clearance_cap": "internal",
        "layers_allow": ["knowledge", "contextual", "structural", "unresolved",
                         "rejected", "goals"],
        # session=记会话要点；ingest=摄取外部文件流（记录单元本职）
        # maintain=写入前馈 prefeed（apply 类批量改写仍被 require_admin 拦截）
        # insight=记录洞见事件（record）；verify/learn 在分发层按单位职责收窄
        # ccg=CCG 六要素编译器（记录单元本职：保存观测/过程/结果与误差）；
        #     其准入不靠 admin 闸而靠签章机械闸（E040/E041/E042）——编译者不得自证
        # task=结构层任务台账（工程做到哪一步/结果是什么）——记录单元本职：
        #     保存过程与结果；「不得自证」由 done 时的结果必填闸承接
        "ops_allow": ["info", "route", "read", "write", "goal", "task", "recent",
                      "session", "ingest", "maintain", "insight", "ccg", "status",
                      "edges"],
        "delegable": False,
        "forbidden": ["self/anchor 层", "private/secret 密级", "裁决与删除"],
    }),
    ("reflect", {
        "label": "反思单元", "unit": "反思单元", "effect": "新",
        "duty": "发现差异、遗漏条件和新的路径；只写反思/情境层",
        "can_write": True, "can_admin": False, "clearance_cap": "internal",
        "layers_allow": ["contextual"],
        # session=反思需读会话（recall 只读）；写 action 另受 can_write 约束
        # maintain=反思后的前馈/模式分离候选（apply 类改写走 require_admin）
        # insight=发现差异/新路径：开窗 window + 情景重构 reconstruct + 盲区学习 learn
        "ops_allow": ["info", "route", "read", "write", "recent", "metacognition",
                      "session", "maintain", "insight", "status", "edges"],
        "delegable": False,
        "forbidden": ["knowledge/self/anchor 层", "private/secret 密级", "裁决与删除"],
    }),
    ("verify", {
        "label": "验证单元", "unit": "验证单元", "effect": "稳",
        "duty": "判断规则、执行结果和结构是否有效；只写验证证据与负记忆",
        # 批次 28 分型：verify 读错误标记节点走 restricted 链路角色集
        # （security.can_read_restricted——restricted=错误处置标记，
        # private 回归纯隐私/会话绑定语义），cap 维持 internal——
        # 验证单元不读真隐私（private 加密档）。批次 28 初版的 cap=private
        # 豁免被分型取代（同日裁定迭代）。
        "can_write": True, "can_admin": False, "clearance_cap": "internal",
        "layers_allow": ["rejected", "contextual"],
        "ops_allow": ["info", "route", "read", "write", "verify", "insight",
                      "status", "edges"],
        "delegable": False,
        "forbidden": ["knowledge/self/anchor 层（不得改被验证内容）",
                      "private/secret 密级（restricted 错误处置标记属本职，"
                      "经链路角色集可见）", "裁决与删除"],
    }),
    ("output", {
        "label": "输出单元", "unit": "输出单元", "effect": "通",
        "duty": "与外部系统协作并表达边界；只读呈现，任何写入一律拒绝",
        "can_write": False, "can_admin": False, "clearance_cap": "internal",
        "layers_allow": [],
        # session 仅开放只读 recall；note/compact 在分发层按 can_write 拦截
        # insight 仅开放只读呈现（list/report/outlook/reconstruct）；写入被 can_write 拦截
        "ops_allow": ["info", "route", "read", "recent", "whitebox", "session",
                      "insight", "status", "edges"],
        "delegable": False,
        "forbidden": ["全部写入", "private/secret 密级", "管理操作"],
    }),
    ("sustain", {
        "label": "维生系统", "unit": "维生系统", "effect": "存",
        "duty": "维护存在、预算、回滚和整体结构；只写 self 层运维域",
        "can_write": True, "can_admin": False, "clearance_cap": "internal",
        "layers_allow": ["self"],
        # session=会话续接（sustain 的 resume 语义延伸）
        # maintain=整体结构维护（长期快照 longterm / 结构重要性盘点 stat）
        # insight=整体结构洞察 outlook（趋势/盲区/建议）+ 条件层报告 report
        "ops_allow": ["info", "read", "write", "sustain", "scrub", "evolution",
                      "self_state", "metacognition", "link", "session",
                      "maintain", "insight", "status", "edges"],
        "delegable": False,
        "forbidden": ["knowledge/anchor 层", "private/secret 密级", "裁决与删除"],
    }),
    ("guest", {
        "label": "未认证访客", "unit": "访客", "effect": "—",
        "duty": "无令牌时的降级身份：只读、最低密级",
        "can_write": False, "can_admin": False, "clearance_cap": "internal",
        "layers_allow": [],
        "ops_allow": ["info", "route", "read", "recent", "whitebox", "status",
                      "edges"],
        "delegable": False,
        "forbidden": ["全部写入", "private/secret 密级", "管理操作"],
    }),
])

# 别名：兼容旧写法与自然语言（verifier→verify / recorder→record …）
ROLE_ALIASES = {"recorder": "record", "reflection": "reflect",
                "verifier": "verify", "viewer": "output", "admin": "designer",
                "root": "designer", "anon": "guest", "anonymous": "guest"}

# 与 identity.POSITIONS 对齐的五个位置效应角色
POSITION_ROLES = ("record", "reflect", "verify", "output", "sustain")

DELEGABLE_ROLES = tuple(r for r, s in ROLE_SPECS.items() if s["delegable"])

# --------------------------------------------------------------------------
# 蜂巢编排器（hive/orch.py）派生收窄面 · 单一真源
# --------------------------------------------------------------------------
# 设计依据（取证 2026-09-16，源码级：本文件 derive() + md_cg/mdcos.py 的
# require_admin 闸门）：
#   ① 编排器要「能裁决子代理冲突」→ 必须过 `MdCGSecure.review_decide` 的库层
#      `require_admin`。而 `derive()` 的 `can_admin = spec.can_admin and
#      parent.can_admin`（**不可收窄**）→ 唯一可行 role 是 designer。
#      （`narrowed_principal()` 的 can_admin 恒 False，裁决会被库层拒 —— 这是被
#      代码证据排除的路径，不是偏好取舍。）
#   ② 因此「不给 delete / 不给 anchor / 不给 delegate」**不能依赖 admin 闸**
#      （can_admin=True 时该闸不拦清单内的 op），而由三重结构保证：
#        · ops_allow 白名单（ALL_OPS 的**子集**）—— 不在清单的 op 被
#          `_cg_dispatch` 前置 `require_op` 直接拒：forget=删除、identity=动地基、
#          protect=固化、maintain/consolidate 的 apply 类批量改写，全在清单外；
#        · layers_allow 白名单（排除 CORE_LAYERS=anchor/self）—— 写不进地基；
#        · `derive()` 硬编码 `delegable=False` —— 派生令牌结构上不可再派生。
#      白名单方向 fail-closed：ALL_OPS 将来新增 op，默认不在清单内 = 不给。
#   ③ 残余面（诚实标注，未收窄）：can_admin=True 使清单内 op 的 admin 分支仍可
#      通过 —— `recent` 的 clear、`consistency` 的 auto_flywheel 写、`review` 的
#      裁决（功能所求）。改本常量即改编排器权限：签发（CLI `orch`）与
#      hive/orch.py 同引此处，防两处硬编码漂移。
ORCH_ROLE = "orchestr"
ORCH_OPS_ALLOW = ("route", "read", "write", "review", "recent", "consistency")
# layers 单一真源 = ROLE_SPECS[orchestr].layers_allow（安全收紧后 derive() 会与
# role spec 求交，旧「ALL-CORE 六层」是死配置——传入即被收窄为三域，徒增漂移面）
ORCH_LAYERS_ALLOW = tuple(ROLE_SPECS[ORCH_ROLE]["layers_allow"])


# 生效条件：role 为假值（None/空串）时按 "" 处理，经 strip().lower() 得 r，r 命中 ROLE_ALIASES 键时返回别名，否则返回 r 本身。
def normalize_role(role: str) -> str:
    r = (role or "").strip().lower()
    return ROLE_ALIASES.get(r, r)


# 生效条件：normalize_role(role) 得 r，r 不在 ROLE_SPECS 中即抛 TokenError，否则返回 dict(ROLE_SPECS[r]) 的浅拷贝。
def role_spec(role: str):
    r = normalize_role(role)
    if r not in ROLE_SPECS:
        raise TokenError(f"未知角色：{role!r}（可选 {sorted(ROLE_SPECS)}）")
    return dict(ROLE_SPECS[r])


# 生效条件：无 required 形参，调用即返回含 SCHEMA、token_file()、CORE_PRIVATE_SENSITIVITIES/CORE_LAYERS/ALL_LAYERS/POSITION_ROLES/DELEGABLE_ROLES/ROLE_ALIASES/ROLE_SPECS 各自 list/dict 拷贝的字典。
def catalog():
    """角色职责矩阵（供 whoami / service_info / 文档自描述）。"""
    return {"schema": SCHEMA, "token_file": token_file(),
            "core_private_sensitivities": list(CORE_PRIVATE_SENSITIVITIES),
            "core_layers": list(CORE_LAYERS), "all_layers": list(ALL_LAYERS),
            "position_roles": list(POSITION_ROLES),
            "delegable_roles": list(DELEGABLE_ROLES),
            "aliases": dict(ROLE_ALIASES),
            "roles": {r: dict(s) for r, s in ROLE_SPECS.items()}}


# --------------------------------------------------------------------------
# 存储（仓库外，0600）
# --------------------------------------------------------------------------

# 生效条件：path 为真值时返回 path，否则回落 os.environ.get(TOKEN_FILE_ENV)（取到空串同为假值），仍为假值时返回 DEFAULT_TOKEN_FILE。
def token_file(path: str = None) -> str:
    return path or os.environ.get(TOKEN_FILE_ENV) or DEFAULT_TOKEN_FILE


# 令牌库跨进程写锁的等待上限（秒）；超时即 fail-closed（见 _store_lock）。
TOKEN_LOCK_TIMEOUT = 10.0


# 生效条件：yield token_file(path) 的归一结果 p 之前，以 FileLock(p, timeout=TOKEN_LOCK_TIMEOUT, strict=True) 取跨进程排它锁；__enter__ 超时（TimeoutError）时转抛 TokenError（fail-closed），其余异常原样传播。
@contextmanager
def _store_lock(path: str = None):
    """令牌库「读-改-写」的**单一临界区**（N199）。

    三条写路径（issue / derive / revoke）原先是「_load → 改 → _save」无锁三步：
    两进程交错时，后写者拿陈旧快照整份覆盖盘面——并发新增的凭据无痕消失
    （调用方拿到明文却永远验不过），且固定共享临时名 `p + ".tmp"` 让两个写者
    互截内容、把库撕成不可解析（叠加 N198 写前对账后即永久不可写，全库令牌
    失效）。这里把三步收进同一把 OS 级锁，并镜像 crypto.provision_dek 的
    N184 口径：strict=True 超时抛错，绝不静默放行退化成无锁并发。

    FileLock **非重入**（同进程对同一锁文件的二次加锁同样拿不到），故递归调用
    者（revoke 级联）走 `_revoke_locked` 复用同一临界区，不得再取锁。
    """
    p = token_file(path)
    try:
        with FileLock(p, timeout=TOKEN_LOCK_TIMEOUT, strict=True):
            yield p
    except TimeoutError as e:
        raise TokenError(
            f"令牌库写锁（{p}.lock）竞争超时：并发签发/派生/吊销未在 "
            f"{TOKEN_LOCK_TIMEOUT:.0f}s 内获得互斥——fail-closed 拒绝写入"
            f"（无锁整份写回会无痕抹除并发新增的凭据，N199）。请稍后重试。"
        ) from e


# 生效条件：p 不存在时返回 ({"schema": SCHEMA, "tokens": {}}, None)；否则 json.load 结果为 dict 且其 "tokens"（缺键先 setdefault 为 {}）是映射时返回 (该 dict, None)；解析抛 OSError/ValueError、顶层非 dict、或 "tokens" 非映射时返回 (空骨架, 损坏描述字符串)。
def _load_raw(p: str):
    """(令牌库快照, 损坏描述)——「可解析性」判据的**唯一**生产者。

    N198：此前 `_load` 只有「解析失败 → 回落空表」这一半，没有「解析失败」
    这个判据本身，于是写面无法区分「空库」与「损坏库」，一路「读空表 →
    改 → 整份写回」把盘上全部令牌记录无痕抹除（同型 crypto/_keys.json 的
    N139 已 fail-closed）。写面（`_save`）按下述 err 拒写，读面（`_load`）
    仍按原口径回落空表——两态由此可区分。
    """
    if not os.path.exists(p):
        return {"schema": SCHEMA, "tokens": {}}, None
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            t = d.setdefault("tokens", {})
            if isinstance(t, dict):
                return d, None
            return ({"schema": SCHEMA, "tokens": {}},
                    "顶层 tokens 不是映射（版本漂移？）")
        return ({"schema": SCHEMA, "tokens": {}},
                "顶层不是对象（版本漂移？）")
    except (OSError, ValueError) as e:
        return {"schema": SCHEMA, "tokens": {}}, f"{type(e).__name__}: {e}"


# 生效条件：p=token_file(path)。_load_raw(p) 无损坏描述时原样返回其快照；有损坏描述（不可解析/顶层非对象/tokens 非映射）时向 stderr 写「令牌库损坏/不可读」告警（N198，2026-09-28：静默回落会让 issue/derive/revoke 据空表整份写回，既有令牌记录被无痕抹除、旧令牌一律验签失败，使用者只见「令牌不存在」——告警必须开口）并返回带 load_error 标记的空结构；_save 见 load_error 即拒绝写回。
def _load(path: str = None) -> dict:
    p = token_file(path)
    data, err = _load_raw(p)
    if err is None:
        return data
    sys.stderr.write(
        f"[mdcg-tokens] ⚠ 令牌库损坏/不可读（{err}）：{p}"
        f"——按回落口径返回空表并置损坏标记（load_error）；签发/派生/吊销在"
        f"标记下拒绝写回（静默写回会把空表覆盖落盘、无痕抹除全部既有令牌"
        f"记录，N198）。请修复或恢复该文件后重试。\n")
    return {"schema": SCHEMA, "tokens": {}, "load_error": err}


# 生效条件：p=token_file(path)，先以 _load_raw(p) 做写前对账——盘面有损坏描述、或本次 data 带 load_error 标记（载入时损坏而写前被人为修复的窗口）时抛 TokenError 拒绝整份写回；data["tokens"] 非映射时同样抛 TokenError（拒写类型混淆的快照）；否则把盘面**独有**的令牌记录逐键并入 data["tokens"]（同名键以本次为准），再经 fsutil.atomic_write 整文件替换 p（同目录唯一临时名 mkstemp + 带 Windows 短重试的 replace，失败即清理临时文件），最后尝试 chmod 0600（仅吞 OSError）。调用方一般须已持有 _store_lock(path)（issue/derive/_revoke_locked 持锁调用）。
def _save(data: dict, path: str = None):
    p = token_file(path)
    # N198 写前对账（镜像 crypto._save_keys 的 N139/N184 口径）：issue/derive/
    # revoke 三条写路径共用本单点，闸在这里等于三面同时收口——解析不出来的
    # 既有记录一概不能被写掉（旧令牌一旦被抹除即永久失效，且原实现零告警）。
    _disk, err = _load_raw(p)
    if err is None and data.get("load_error"):
        err = data["load_error"]
    if err is not None:
        raise TokenError(
            f"令牌库损坏/不可读（{err}）：{p}"
            f"——拒绝整份写回（静默写回会无痕抹除全部既有令牌记录，N198）。"
            f"请先手工处理该文件（备份/修复/移除）再重试。")
    _tk = data.setdefault("tokens", {})
    if not isinstance(_tk, dict):
        raise TokenError(
            f"令牌库快照类型异常（tokens 非映射：{type(_tk).__name__}）：{p}"
            f"——拒绝写回（N199）。请检查调用方传入的快照。")
    # N199 纵深防御（镜像 crypto._save_keys 的 N184 写前合并）：本次快照里没有、
    # 盘面上有的记录一律带回。正常路径下锁已保证快照不陈旧，此处的意义是兜住
    # 「未持锁的直接 _save 调用」以及锁语义将来被误用时的整份覆盖——原子替换
    # 只防撕裂不防丢失更新。令牌记录只增不改（无删除路径），故带回恒为安全。
    for _tid, _rec in ((_disk or {}).get("tokens") or {}).items():
        if _tid not in _tk:
            _tk[_tid] = _rec
    atomic_write(p, json.dumps(data, ensure_ascii=False, indent=1))
    try:
        os.chmod(p, 0o600)          # 令牌摘要文件不可被其他用户读
    except OSError:
        pass


# 生效条件：secret 经 encode("utf-8") 后取 sha256 的 hexdigest；secret 非 str 时按其 encode 失败抛出。
def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


# 生效条件：_rank(want) <= _rank(cap) 时返回 want，否则返回 cap。
def _clamp_level(want: str, cap: str) -> str:
    return want if _rank(want) <= _rank(cap) else cap


# 生效条件：allow 为 None 时按 parent_allow 是否为 None 返回 None 或 list(parent_allow)；否则 parent_allow 为 None 或含 "*" 时返回 list(allow)；否则 allow 含 "*" 时返回 list(parent_allow)；否则返回 [x for x in allow if x in parent_allow]。
def _narrow(allow, parent_allow):
    """求交：子权限只能收窄。父为 None（不限制）时取子；子为 None 时取父。"""
    if allow is None:
        return None if parent_allow is None else list(parent_allow)
    if parent_allow is None or "*" in parent_allow:
        return list(allow)
    if "*" in allow:
        return list(parent_allow)
    return [x for x in allow if x in parent_allow]


# 生效条件：role/token_id/secret 即使为假值也照拼，返回 f"{PREFIX}.{role}.{token_id}.{secret}"。
def make_token(role: str, token_id: str, secret: str) -> str:
    return f"{PREFIX}.{role}.{token_id}.{secret}"


# 生效条件：token 为假值时按 "" 处理，split(".") 后长度不为 4 或 parts[0] != PREFIX 即抛 TokenError（前缀只认小写，故 `MDCG1.*` 在这一步就已拒）；role/token_id 含大写即抛 TokenError（**只认小写**，2026-09-28 使用者裁定：不再把小写化当归一，变形一律拒收），secret 不受此限（`secrets.token_urlsafe` 产 base64url、必含大写）；长度与前缀合规后 role/token_id/secret 任一为空再抛 TokenError；否则返回 (role, token_id, secret)。
def parse_token(token: str):
    parts = (token or "").strip().split(".")
    if len(parts) != 4 or parts[0] != PREFIX:
        raise TokenError("令牌格式非法（应为 mdcg1.<role>.<token_id>.<secret>）")
    _, role, token_id, secret = parts
    if not role or not token_id or not secret:
        raise TokenError("令牌字段缺失")
    # 识别面宽、受理面窄：检测表（policy.forbidden / hooks.SENSITIVE_PATTERNS）认全形态
    # 是为了「拦得住」，此处只认小写是为了「说得准」——签发面（issue 经 normalize_role +
    # secrets.token_hex(6)）只产小写 role/token_id，大写形态没有任何合法来源，故一律视为
    # 伪造或手抄变形，不再静默小写化后放行。（旧实现返回 role.lower() 恰是「受理面比识别面
    # 更宽」的反例：大写十六进制 id 在 hooks.ts 的 `[0-9a-f]` 检测面上漏过、却被受理面接受。）
    if role != role.lower() or token_id != token_id.lower():
        raise TokenError("令牌形态非法：role/token_id 只认小写，含大写即拒（不做小写化归一）")
    return role, token_id, secret


# --------------------------------------------------------------------------
# 签发 / 校验 / 派生 / 吊销
# --------------------------------------------------------------------------

# 生效条件：role 经 normalize_role+role_spec（未知角色抛 TokenError），clearance 为假值时取 spec["clearance_cap"] 再经 _clamp_level 收窄到该 cap，layers_allow/ops_allow 经 _narrow 与 spec 默认求交，actor 为假值时取 role，delegable is None 时取 spec["delegable"]、否则按所传值取 bool，ttl 为真值时 expires_at=now+float(ttl)、为假值（None/0）时 None，随后在 _store_lock(path) 临界区内把记录写入 token_file(path)（N199：读-改-写无锁会被并发写者用陈旧快照整份覆盖）并返回含明文 token 的字典。
def issue(role: str, actor: str = None, clearance: str = None,
          tenant: str = "default", ttl: float = None, label: str = "",
          issued_by: str = "root", parent: str = None, delegable: bool = None,
          layers_allow=None, ops_allow=None, path: str = None):
    """签发一枚令牌。明文 token 只在返回值里出现一次，不落盘。"""
    role = normalize_role(role)
    spec = role_spec(role)
    clearance = _clamp_level(clearance or spec["clearance_cap"],
                             spec["clearance_cap"])
    layers = _narrow(layers_allow, spec["layers_allow"])
    ops = _narrow(ops_allow, spec["ops_allow"])
    token_id, secret = "tk_" + secrets.token_hex(6), secrets.token_urlsafe(32)
    now = time.time()
    rec = {
        "role": role, "actor": actor or role, "tenant": tenant,
        "clearance": clearance,
        "can_write": bool(spec["can_write"]),
        "can_admin": bool(spec["can_admin"]),
        "layers_allow": layers, "ops_allow": ops,
        "delegable": bool(spec["delegable"] if delegable is None else delegable),
        "parent": parent, "issued_by": issued_by, "issued_at": now,
        "expires_at": (now + float(ttl)) if ttl else None,
        "revoked_at": None, "label": label, "hash": _hash(secret),
    }
    # N199：读-改-写整段收进令牌库跨进程临界区——无锁时后写者用陈旧快照整份
    # 覆盖，并发签发的新凭据无痕消失（调用方拿到明文却永远验不过）。
    with _store_lock(path):
        data = _load(path)
        data["tokens"][token_id] = rec
        data["schema"] = SCHEMA
        _save(data, path)
    return {"ok": True, "token": make_token(role, token_id, secret),
            "token_id": token_id, "role": role, "actor": rec["actor"],
            "clearance": clearance, "layers_allow": layers, "ops_allow": ops,
            "expires_at": rec["expires_at"], "token_file": token_file(path)}


# 生效条件：token 先经 parse_token（格式非法即抛 TokenError），其后 _load(path) 的 tokens 中该 token_id 无记录、rec 的 role 与解析出的 role 不等、revoked_at 为真、hash 与 _hash(secret) 经 hmac.compare_digest 不等、expires_at 为真且小于当前时间、或沿 parent 链上溯（seen 集合防环；链上父记录缺失时仅向 stderr 告警不阻断——吊销已由 revoke 级联物化，此处只补过期维度，文件写权不在令牌威胁模型内）任一祖先 expires_at 为真且小于当前时间中任一成立即抛 TokenError；否则返回 Principal，tenant=tenant or rec.get("tenant") or "default"、actor=rec.get("actor") or role、clearance=rec.get("clearance") or "internal"、can_write/can_admin 取对应 rec 值的 bool；返回前 rec["tenant"] 与非空形参 tenant 去空白后不等时先向 stderr 写「租户绑定被入参覆盖」告警；rec["tenant"] 与非空形参 tenant 去空白后不等时抛 TokenError 拒绝（N62②，2026-09-27 第 5 轮：告警改 fail-closed——原告警文案已定性「若非有意迁移请校正 MDCG_TENANT」），clearance 先取 rec 值再按登记租户上限夹紧（N62①：MDCG_TENANT_REGISTRY 登记表（与 _resolve_root 同源）在册租户 _rank(clearance) 高于其 clearance_cap 时夹紧为 cap；未登记租户/登记表缺失或损坏零闸变）。
def verify_token(token: str, tenant: str = None, path: str = None) -> Principal:
    """校验令牌 → Principal。任何异常都抛 TokenError（fail-closed）。"""
    role, token_id, secret = parse_token(token)
    tokens_map = _load(path).get("tokens") or {}
    rec = tokens_map.get(token_id)
    if not rec:
        raise TokenError("令牌不存在（可能已吊销或来自其他令牌文件）")
    if rec.get("role") != role:
        raise TokenError("令牌角色与记录不一致（可能被篡改）")
    if rec.get("revoked_at"):
        raise TokenError("令牌已吊销")
    if not hmac.compare_digest(str(rec.get("hash") or ""), _hash(secret)):
        raise TokenError("令牌密钥不匹配")
    now = time.time()
    exp = rec.get("expires_at")
    if exp and now > float(exp):
        raise TokenError("令牌已过期")
    # N123（2026-09-25 止血）：过期沿派生链传播——父令牌过期后，其派生子令牌
    # 一并失效（与 revoke 级联 tokens.revoke 的语义对齐；存量库中修复前派生的
    # 未夹紧子令牌由此兜底）。delegable=False 封口使链深常态为 2，开销可忽略。
    pid, seen = rec.get("parent"), {token_id}
    while pid:
        if pid in seen:                     # 防环：损坏记录不得挂死校验
            sys.stderr.write(
                f"[mdcg-tokens] ⚠ 令牌 {token_id} 派生链存在环（parent={pid}），"
                f"沿链过期校验在此截断，请修复令牌文件。\n")
            break
        seen.add(pid)
        ancestor = tokens_map.get(pid)
        if not ancestor:
            sys.stderr.write(
                f"[mdcg-tokens] ⚠ 令牌 {token_id} 的祖先 {pid} 记录缺失，"
                f"该祖先的过期校验被跳过（吊销不受影响——revoke 已级联物化）。\n")
            break
        a_exp = ancestor.get("expires_at")
        if a_exp and now > float(a_exp):
            raise TokenError(
                f"令牌已失效：派生链祖先 {pid} 已过期（过期沿派生链传播）")
        pid = ancestor.get("parent")
    # ② N62（第 5 轮成立，2026-09-27）：租户绑定被入参覆盖由告警改 fail-closed
    # 拒绝——形参 tenant（MCP 侧来自 MDCG_TENANT）非空且与令牌记录
    # rec["tenant"] 不同时抛 TokenError（v8 N62 首报→v9/v15/v16 历轮成立，
    # warn-only 五轮证明告警不构成闸门；原告警文案已定性「若非有意迁移请
    # 校正」）。有意迁移的正道：校正 MDCG_TENANT 或为该租户重新签发令牌。
    _rec_tenant = str(rec.get("tenant") or "").strip()
    _arg_tenant = str(tenant or "").strip()
    if _arg_tenant and _rec_tenant and _arg_tenant != _rec_tenant:
        raise TokenError(
            f"[mdcg-tokens] 租户绑定被入参覆盖，拒绝校验（fail-closed，"
            f"N62 第 5 轮）：令牌按 {_rec_tenant} 签发，但入参 "
            f"tenant={_arg_tenant}（MCP 侧来自 MDCG_TENANT）——令牌不得以原 "
            f"clearance/can_admin 对 {_arg_tenant} 运行。若非有意迁移，请校正 "
            f"MDCG_TENANT；若为有意迁移，请为该租户重新签发令牌"
            f"（python -m md_cg.tokens issue …）。\n")
    # ① N62 接线：令牌路径 clearance 按登记租户上限夹紧（principal_for/cap_of
    # 现成，纯收紧不改宽）——仅登记租户收紧；未登记租户/登记表缺失或损坏
    # 零闸变（fresh install 无 _tenants.json 行为不变，守卫 R3 钉住；登记表
    # 损坏回落与 _resolve_root 的 N124 先例同口径）。登记表路径经
    # MDCG_TENANT_REGISTRY（与 mcp_server._resolve_root 同源）。
    _eff_tenant = tenant or rec.get("tenant") or "default"
    _clearance = rec.get("clearance") or "internal"
    try:
        _reg = TenantRegistry(os.environ.get("MDCG_TENANT_REGISTRY") or None)
        if _reg.get(_eff_tenant):
            _cap = _reg.cap_of(_eff_tenant)
            if _rank(_clearance) > _rank(_cap):
                _clearance = _cap
    except Exception:                     # noqa: BLE001 —— 登记表缺失/损坏按未登记（零闸变）
        pass
    return Principal(
        tenant=_eff_tenant,
        actor=rec.get("actor") or role,
        clearance=_clearance,
        can_write=bool(rec.get("can_write")),
        can_admin=bool(rec.get("can_admin")),
        role=role, token_id=token_id, parent=rec.get("parent"),
        expires_at=exp, layers_allow=rec.get("layers_allow"),
        ops_allow=rec.get("ops_allow"), auth_mode="token")


# 生效条件：parent_token 经 verify_token(parent_token, path=path) 成功，随后在 _store_lock(path) 临界区内复核父令牌**落盘态**：父记录 delegable 为假抛 TokenError，父记录已并发吊销（revoked_at 为真，N199）同样抛 TokenError；role 经 normalize_role+role_spec，clearance 为假值时取 spec["clearance_cap"] 再 _clamp_level，若仍高于 parent.clearance 则降为 parent.clearance 并向 clamped 追加 "clearance"；layers/ops 先与 spec 求交再与父记录求交；can_write/can_admin 取 spec 与父对应值的与；ttl 为真值时过期候选=now+float(ttl)、为假值（None/0）时沿用父记录 expires_at，候选与父记录 expires_at 均非空时取 min（N123：派生在时间维度同样只能收窄，父无界时取候选），被父夹紧时向 clamped 追加 "expires_at"；新记录 delegable 恒 False、parent/issued_by 为 parent.token_id，_save 后返回含明文 token 与 clamped 的字典。
def derive(parent_token: str, role: str, actor: str = None, ttl: float = None,
           label: str = "", path: str = None, clearance: str = None,
           layers_allow=None, ops_allow=None):
    """设计者令牌派生受限子令牌：权限只能收窄，子令牌默认不可再派生。"""
    parent = verify_token(parent_token, path=path)
    # N199：本函数的「读-改-写」必须与父令牌的**落盘态复核**同处一个临界区
    # （原先无锁，并发 revoke 与之交错时会产出「父已吊销、子仍有效」的凭据：
    # 吊销级联只覆盖它落锁那一刻盘上已存在的子令牌）。持锁后 revoke 只能落在
    # 本函数之前（则下方 prec["revoked_at"] 判据拒绝派生）或之后（则级联能看见
    # 这枚新子令牌并一并吊销）——两向都收口。
    with _store_lock(path):
        data = _load(path)
        prec = (data.get("tokens") or {}).get(parent.token_id) or {}
        if not prec.get("delegable"):
            raise TokenError(
                f"令牌 {parent.token_id} 不可派生（role={parent.role}）")
        if prec.get("revoked_at"):
            raise TokenError(
                f"父令牌 {parent.token_id} 已被并发吊销，拒绝派生（N199）")
        role = normalize_role(role)
        spec = role_spec(role)
        clamped = []
        want_clear = clearance or spec["clearance_cap"]
        final_clear = _clamp_level(want_clear, spec["clearance_cap"])
        if _rank(parent.clearance) < _rank(final_clear):
            final_clear = parent.clearance
            clamped.append("clearance")
        layers = _narrow(_narrow(layers_allow, spec["layers_allow"]),
                         prec.get("layers_allow"))
        ops = _narrow(_narrow(ops_allow, spec["ops_allow"]),
                      prec.get("ops_allow"))
        can_write = bool(spec["can_write"]) and bool(parent.can_write)
        can_admin = bool(spec["can_admin"]) and bool(parent.can_admin)
        # N123（2026-09-25 止血）：「派生只能收窄」补上时间维度——子令牌有效期
        # 不得超过父令牌（revoke 有级联，过期原先没有：父过期后子令牌仍以原密级
        # 通过 verify_token，授权回收被长 TTL 子令牌旁路）。父无界（expires_at
        # 为 None）时不夹紧，取请求值；子未指定 ttl 时沿用父界（含无界）。
        now = time.time()
        pexp = prec.get("expires_at")
        want_exp = (now + float(ttl)) if ttl else pexp
        final_exp = want_exp
        if want_exp is not None and pexp is not None \
                and float(want_exp) > float(pexp):
            final_exp = pexp
            clamped.append("expires_at")
        token_id, secret = ("tk_" + secrets.token_hex(6),
                            secrets.token_urlsafe(32))
        rec = {
            "role": role, "actor": actor or role, "tenant": parent.tenant,
            "clearance": final_clear, "can_write": can_write,
            "can_admin": can_admin,
            "layers_allow": layers, "ops_allow": ops,
            "delegable": False, "parent": parent.token_id,
            "issued_by": parent.token_id, "issued_at": now,
            "expires_at": final_exp,
            "revoked_at": None, "label": label, "hash": _hash(secret),
        }
        data["tokens"][token_id] = rec
        _save(data, path)
    return {"ok": True, "token": make_token(role, token_id, secret),
            "token_id": token_id, "role": role, "actor": rec["actor"],
            "clearance": final_clear, "layers_allow": layers, "ops_allow": ops,
            "can_write": can_write, "can_admin": can_admin,
            "parent": parent.token_id, "clamped": clamped,
            "expires_at": rec["expires_at"]}


# 生效条件：normalize_role(unit) 结果不在 POSITION_ROLES 时抛 TokenError；否则返回 Principal：unit/role=u、can_admin 恒 False、clearance=_clamp_level(spec["clearance_cap"], p.clearance)、can_write=bool(spec["can_write"]) and bool(p.can_write)、layers_allow/ops_allow=_narrow(spec 对应值, p 对应值)，tenant/actor/session/harness/token_id/parent/expires_at/auth_mode/theory 等沿用 p。
def narrowed_principal(p: Principal, unit: str) -> Principal:
    """按「单元」收窄 principal 权限（**请求级**身份，只能变小不能变大）。

    与 `derive()` 同源——复用 `_narrow()` 求交语义——但**不签发令牌**，只在
    单次 MCP 调用内生效（见 `mcp_server.call_tool` 的 `as_unit` 参数）。
    动机：单进程多身份。MCP 子进程的 env 身份（令牌）只回答「谁装了这个
    大脑」；而**这一次调用**该以哪个单元执行，由请求参数决定。

    硬约束（调用方无法绕过）：
      · `can_admin` 恒为 False —— 任何单元都拿不到管理权（改不了大脑结构）；
      · clearance / layers / ops 一律与 owner **求交** → 结果 ≤ owner 权限；
      · `can_write` 与 owner 取「与」 —— owner 只读时单元不可能变可写。

    因为收窄是单调的，调用方伪造 `as_unit` 的最坏结果等于不传（owner 全权），
    **不可能提权** —— 这是本机制不需要对 `as_unit` 额外鉴权的根据。

    unit 不在 `POSITION_ROLES`（五单元）内 → `TokenError`（fail-closed：
    拼错单元名必须报错，绝不静默退回 owner 全权）。
    """
    u = normalize_role(unit)
    if u not in POSITION_ROLES:
        raise TokenError(f"未知单元：{unit!r}（可选 {list(POSITION_ROLES)}）")
    spec = role_spec(u)
    return Principal(
        tenant=p.tenant, actor=p.actor, session=p.session, harness=p.harness,
        unit=u, role=u,
        clearance=_clamp_level(spec["clearance_cap"], p.clearance),
        can_write=bool(spec["can_write"]) and bool(p.can_write),
        can_admin=False,
        layers_allow=_narrow(spec["layers_allow"], p.layers_allow),
        ops_allow=_narrow(spec["ops_allow"], p.ops_allow),
        token_id=p.token_id, parent=p.parent, expires_at=p.expires_at,
        auth_mode=p.auth_mode,
        theory_ok=p.theory_ok, theory_version=p.theory_version)


# 生效条件：先以 _store_lock(path) 取令牌库跨进程写锁（超时抛 TokenError），再在临界区内执行 _revoke_locked(token_id, path) 并返回其结果。
def revoke(token_id: str, path: str = None):
    """吊销令牌（级联派生链）。整个「读-改-写 + 级联」在同一临界区内完成。"""
    with _store_lock(path):
        return _revoke_locked(token_id, path)


# 生效条件：调用方**已持** _store_lock(path)（FileLock 非重入，递归不得再取锁）；token_id 在 _load(path) 的 tokens 中无记录时抛 TokenError；有记录则将其 revoked_at 置为 time.time() 并 _save，再对 tokens 中 parent 等于 token_id 的每个子令牌递归 _revoke_locked(c, path)，返回 {"ok": True, "token_id": token_id, "revoked_children": children}。
def _revoke_locked(token_id: str, path: str = None):
    data = _load(path)
    rec = (data.get("tokens") or {}).get(token_id)
    if not rec:
        raise TokenError(f"令牌不存在：{token_id}")
    rec["revoked_at"] = time.time()
    _save(data, path)
    # 级联吊销派生链（同一临界区内递归：N199 保证「落锁期间不会有新子令牌
    # 悄悄挂到本令牌下」，否则那枚子令牌会绕过级联、在父已吊销后仍有效）
    children = [t for t, r in data["tokens"].items() if r.get("parent") == token_id]
    for c in children:
        _revoke_locked(c, path)
    return {"ok": True, "token_id": token_id, "revoked_children": children}


# 生效条件：从 _load(path)（path 为 None 时取默认令牌文件）的 tokens 取值；条目的 revoked_at 为真且 include_revoked 为假时跳过；返回不含密钥材料与摘要的清单；
def list_tokens(path: str = None, include_revoked: bool = False):
    """令牌清单（不含密钥材料与摘要）。"""
    out = []
    for tid, r in (_load(path).get("tokens") or {}).items():
        if r.get("revoked_at") and not include_revoked:
            continue
        out.append({"token_id": tid, "role": r.get("role"),
                    "actor": r.get("actor"), "tenant": r.get("tenant"),
                    "clearance": r.get("clearance"),
                    "can_write": r.get("can_write"),
                    "can_admin": r.get("can_admin"),
                    "layers_allow": r.get("layers_allow"),
                    "ops_allow": r.get("ops_allow"),
                    "delegable": r.get("delegable"), "parent": r.get("parent"),
                    "label": r.get("label"), "issued_at": r.get("issued_at"),
                    "expires_at": r.get("expires_at"),
                    "revoked_at": r.get("revoked_at")})
    return sorted(out, key=lambda x: x.get("issued_at") or 0)


# --------------------------------------------------------------------------
# CLI：签发 / 派生 / 清单 / 吊销 / 角色矩阵
# --------------------------------------------------------------------------

# 生效条件：obj 一律经 json.dumps(obj, ensure_ascii=False, indent=1) 加换行写入 sys.stdout；obj 不可 JSON 序列化时抛出 TypeError。
def _print(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")


# 生效条件：v 为假值（None/空串）时返回 None；否则按 "," 切分、strip 后丢弃空项，结果为空列表时同样返回 None。
def _csv_list(v):
    """CLI 的逗号分隔白名单 → list；空值返回 None（= 不额外收窄）。

    仅做语法解析：越界项由 `issue()` 的 `_narrow()` 兜底（只能小于角色默认）。
    """
    if not v:
        return None
    return [x.strip() for x in str(v).split(",") if x.strip()] or None


# 生效条件：path 经 os.path.abspath 得 p（不含共享固定临时名），text 经 fsutil.atomic_write 整体替换写入 p（同目录唯一临时名 mkstemp + 带 Windows 短重试的 replace，失败即清理），再尝试 chmod 0600（仅吞 OSError）。
def _write_secret(path: str, text: str) -> None:
    """把令牌明文写入文件（0600，原子替换）——供 HIVE_ORCH_TOKEN_FILE 读取。"""
    p = os.path.abspath(path)
    # N199：原先写 p + ".tmp"（固定共享名）再 publish——两进程同写一个目标时
    # 互截内容（半截文件可能被 rename 到位）。atomic_write 用唯一临时名。
    atomic_write(p, text)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


# 生效条件：argv 为 None 时取 sys.argv[1:]；经 argparse 解析（--token-file 与必填子命令 issue/verify/revoke/list/roles 等）；参数非法时经 argparse 退出，写盘失败抛 OSError；
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m md_cg.tokens",
        description="灵枢令牌管理：角色权职分离的凭据签发与校验")
    ap.add_argument("--token-file", default=None, help="令牌文件路径（默认 ~/.mdcg/_tokens.json）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_i = sub.add_parser("issue", help="签发令牌（外部用户为设计者载体签发）")
    p_i.add_argument("--role", required=True, help="designer|reflection|verifier|recorder|output|sustain")
    p_i.add_argument("--actor", default=None)
    p_i.add_argument("--tenant", default="default")
    p_i.add_argument("--clearance", default=None)
    p_i.add_argument("--ttl", type=float, default=None, help="有效期（秒）")
    p_i.add_argument("--label", default="")
    p_i.add_argument("--ops-allow", dest="ops_allow", default=None,
                     help="收窄 op 白名单（逗号分隔；越界项被忽略，只能小于角色默认，"
                          "见 `roles` 子命令）")
    p_i.add_argument("--layers-allow", dest="layers_allow", default=None,
                     help="收窄可写层白名单（逗号分隔；越界项被忽略）")

    p_d = sub.add_parser("derive", help="设计者令牌派生子令牌（权限只能收窄）")
    p_d.add_argument("--token", default=None, help="父令牌明文")
    p_d.add_argument("--token-file-in", dest="token_file_in", default=None, help="从文件读父令牌")
    p_d.add_argument("--role", required=True)
    p_d.add_argument("--actor", default=None)
    p_d.add_argument("--ttl", type=float, default=None)
    p_d.add_argument("--label", default="")
    p_d.add_argument("--ops-allow", dest="ops_allow", default=None,
                     help="收窄 op 白名单（逗号分隔；越界项被忽略，只能小于角色默认）")
    p_d.add_argument("--layers-allow", dest="layers_allow", default=None,
                     help="收窄可写层白名单（逗号分隔；越界项被忽略）")
    p_d.add_argument("--clearance", default=None,
                     help="收窄密级（默认取角色上限，且不超过父令牌）")

    p_o = sub.add_parser(
        "orch",
        help="签发蜂巢编排器令牌（收窄面取自本模块 ORCH_* 真源，一步到位）")
    p_o.add_argument("--token", default=None, help="父令牌明文（须为 designer 且可派生）")
    p_o.add_argument("--token-file-in", dest="token_file_in", default=None,
                     help="从文件读父令牌")
    p_o.add_argument("--ttl", type=float, default=None, help="有效期（秒）")
    p_o.add_argument("--label", default="hive-orchestrator")
    p_o.add_argument("--out", default=None,
                     help="把令牌明文写入该文件（0600；供 HIVE_ORCH_TOKEN_FILE 读取）")

    p_v = sub.add_parser("verify", help="校验令牌并打印身份")
    p_v.add_argument("--token", default=None)
    p_v.add_argument("--token-file-in", dest="token_file_in", default=None)

    p_r = sub.add_parser("revoke", help="吊销令牌（级联吊销派生链）")
    p_r.add_argument("--token-id", required=True)

    sub.add_parser("list", help="列出令牌（不含密钥材料）")
    sub.add_parser("roles", help="打印角色职责矩阵")

    a = ap.parse_args(argv)
    try:
        if a.cmd == "issue":
            _print(issue(a.role, actor=a.actor, clearance=a.clearance,
                         tenant=a.tenant, ttl=a.ttl, label=a.label,
                         layers_allow=_csv_list(a.layers_allow),
                         ops_allow=_csv_list(a.ops_allow),
                         path=a.token_file))
        elif a.cmd == "derive":
            tok = a.token
            if a.token_file_in:
                with open(a.token_file_in, encoding="utf-8") as f:
                    tok = f.read().strip()
            _print(derive(tok, a.role, actor=a.actor, ttl=a.ttl,
                          label=a.label, path=a.token_file,
                          clearance=a.clearance,
                          layers_allow=_csv_list(a.layers_allow),
                          ops_allow=_csv_list(a.ops_allow)))
        elif a.cmd == "orch":
            tok = a.token
            if a.token_file_in:
                with open(a.token_file_in, encoding="utf-8") as f:
                    tok = f.read().strip()
            r = derive(tok, ORCH_ROLE, actor="hive-orchestrator", ttl=a.ttl,
                       label=a.label, path=a.token_file,
                       layers_allow=list(ORCH_LAYERS_ALLOW),
                       ops_allow=list(ORCH_OPS_ALLOW))
            if a.out:
                _write_secret(a.out, r["token"])
                r = {k: v for k, v in r.items() if k != "token"}
                r["token_written_to"] = os.path.abspath(a.out)
            r["usage"] = ("把令牌明文放入 hive serve 的环境变量 HIVE_ORCH_TOKEN"
                          "（或写文件后设 HIVE_ORCH_TOKEN_FILE）再重启 serve")
            _print(r)
        elif a.cmd == "verify":
            tok = a.token
            if a.token_file_in:
                with open(a.token_file_in, encoding="utf-8") as f:
                    tok = f.read().strip()
            p = verify_token(tok, path=a.token_file)
            _print({"ok": True, "principal": p.as_dict(),
                    "role_label": role_spec(p.role)["label"]})
        elif a.cmd == "revoke":
            _print(revoke(a.token_id, path=a.token_file))
        elif a.cmd == "list":
            _print({"tokens": list_tokens(path=a.token_file),
                    "token_file": token_file(a.token_file)})
        elif a.cmd == "roles":
            _print(catalog())
    except TokenError as e:
        sys.stderr.write(f"[tokens] {e}\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())