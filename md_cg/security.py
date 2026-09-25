# -*- coding: utf-8 -*-
"""md_cg · 进程/权限模型（记忆 OS #2）

关键动机：**灵枢是开源仓库，而记忆很大一部分是私有内容**。因此权限模型必须
支持「公开知识」与「私有记忆」的物理与逻辑隔离：

  ① 物理隔离：租户（tenant）各自一个根目录。public 租户的根可落在开源仓库内，
     private 租户的根必须落在仓库外（如 ~/.mdcg/private/）。
  ② 逻辑隔离：每个节点带 sensitivity（public < internal < private < secret）；
     每个调用方（Principal）带 clearance，只能读写 ≤ clearance 的节点。
  ③ 硬规则：secret 节点对 clearance < secret 的调用方**写入即拒**（对齐 noema
     「secret 候选自动拒绝」）；写入高于自身 clearance 的敏感度 → 拒绝。

零第三方依赖。
"""
from __future__ import annotations

import json
import os
import time
import uuid

from .datapath import aux_root
from .fsutil import publish

# 密级阶梯的体系语义（批次 27 表述正名，使用者 2026-09-24 澄清）：
#   private ≠ 个人隐私保密，而是**错误处置标记**——工作区内容因错误相关、
#   验证未过、待排查而被标记私有，目的是**限制向平级/下级扩散**（防止未
#   证实或已知有误的内容被下游消费），不是对错误处置链路保密。
#   可见性是**故意的冲突设计**：平级/下级限读，但错误处置链路必须可读——
#   设计者（designer，secret 上限）、上级节点、验证单元（verify）三者
#   必读。当前令牌矩阵中 record/reflect/verify/sustain/orchestr 的
#   clearance_cap 均为 internal（forbidden 含 private）——验证单元读错误
#   标记节点是本职却受限于 cap，属**已登记的分级缺口**（见安全审计实锚
#   文档「读权限分级」节），未来专项：verify 面提 cap 或走设计者代查通道。
# 密级阶梯的体系语义（批次 27 正名 / 批次 28 分型落地，使用者 2026-09-24）：
#   **restricted = 错误处置标记（新增档）**——内容因错误相关、验证未过、
#   待排查被标记，目的是限制向平级/下级扩散；可见性按**错误处置链路角色**
#   判定（designer/orchestr/verify 必读，record/worker/output/guest 限读），
#   不走纯密级 rank（链路角色与平级同为 internal，rank 无法区分）；
#   **不加密**（不在 crypto.ENCRYPTED_LEVELS——链路要明文读）。
#   private = 隐私/会话绑定档（语义不变：仅归属会话 + 设计者豁免可见，
#   落盘加密）；secret = 最高密级。
#   可见性的故意冲突设计就此消解：错误标记限扩散但处置链路必读，
#   隐私内容写者私有——两种语义不再共用一个密级档。
SENSITIVITY_ORDER = ("public", "internal", "restricted", "private", "secret")
DEFAULT_SENSITIVITY = "internal"


class AccessDenied(Exception):
    """权限拒绝（读/写/管理）。

    hint（可选）：与本仓 70 处失败路径 hint 同口径的「为什么 + 怎么办」可操作
    指引（issue #34：新用户首个错误无可操作指引——guest 只读写入被拒恰是
    三步接入后必然撞上的第一条失败，不得只说「不行」不说「怎么办」）。
    """

    def __init__(self, msg: str, hint: str = None):
        super().__init__(msg)
        self.hint = hint


# 生效条件：形参 level 为模块级常量 SENSITIVITY_ORDER 中的元素时返回其下标，否则抛 AccessDenied。
def _rank(level: str) -> int:
    try:
        return SENSITIVITY_ORDER.index(level)
    except ValueError:
        raise AccessDenied(f"未知敏感度/密级：{level}") from None


# 生效条件：全部形参均可省略、clearance 默认取模块常量 DEFAULT_SENSITIVITY，构造时先经 _rank(clearance) 校验，随后 session 为假值（含空串）回落为 sess_+uuid 十二位、role 假值回落 "system"、expires_at 为假值（含 0）置 None、layers_allow/ops_allow 为 None 时保持 None 否则转 tuple、theory_ok 经 bool() 转换。
class Principal:
    """调用方身份（一次会话一个）。

    tenant        —— 租户（决定根目录）
    actor         —— 调用者标识（写入审计）
    clearance     —— 最高可读/可写敏感度
    can_write     —— 是否允许写
    can_admin     —— 是否允许管理操作（forget/restore/review_decide）
    session       —— 会话 id（进程/会话模型：每次连接一个）
    harness       —— 承载端标识（dsh/zcode/codebuddy…；仅归因，不参与授权）
    unit          —— 单元分工（record/reflect/verify/output/sustain；仅归因）
                     注：MCP 请求级参数 `as_unit` 会经 `tokens.narrowed_principal`
                     产出一次性 Principal——其 role/layers/ops 取自该单元 spec、unit
                     记为执行单元。那是**单次调用的临时身份**，不改变本字段的归因
                     定位（见 `mcp_server.call_tool`）。

    令牌扩展（由 `tokens.verify_token` 填充；直接构造时为 None = 不限制）：
    role          —— 角色（designer/reflection/verifier/recorder/output/sustain/guest）
    token_id      —— 令牌 id（可追溯到签发记录）
    parent        —— 派生来源令牌 id（权职分离的委派链）
    expires_at    —— 过期时间戳（None = 不过期）
    layers_allow  —— 可写层白名单（None = 不限制；"*" = 全部）
    ops_allow     —— 可执行 op 白名单（同上）
    auth_mode     —— direct（直接构造）/ token / legacy_env / anonymous

    版本层扩展（蜂群互联层0，由 `theory.check` 填充）：
    theory_ok      —— 版本声明是否合法；False 时**全部写/管理操作被拒**（只读降级）
    theory_version —— 当前声明的协议版本（审计与 whoami 用）
    """

# 生效条件：clearance 须为模块级常量 SENSITIVITY_ORDER 成员（否则 _rank 抛 AccessDenied），session 为假值（含 None/空串）时生成 sess_ 随机串，expires_at 为假值（含 None/0）时存 None 否则 float(expires_at)，layers_allow/ops_allow 为 None 时存 None 否则 tuple 化。
    def __init__(self, tenant: str = "default", actor: str = "system",
                 clearance: str = DEFAULT_SENSITIVITY, can_write: bool = True,
                 can_admin: bool = False, session: str = None,
                 harness: str = None, unit: str = None,
                 role: str = None, token_id: str = None, parent: str = None,
                 expires_at: float = None, layers_allow=None, ops_allow=None,
                 auth_mode: str = "direct", theory_ok: bool = True,
                 theory_version: str = None):
        _rank(clearance)                      # 校验
        self.tenant = tenant
        self.actor = actor
        self.clearance = clearance
        self.can_write = can_write
        self.can_admin = can_admin
        self.session = session or ("sess_" + uuid.uuid4().hex[:12])
        # 归因维度（嵌套身份）：只入审计（_audit/_recent），不参与权限判定。
        # 权限域仍由令牌记录决定（tokens.ROLE_SPECS），与 harness/unit 无关。
        # 受控例外：MCP 请求级 `as_unit` 收窄（tokens.narrowed_principal）产出的是
        # 一次性 Principal，其 role/allow 取自单元 spec——**只做减法**（与 owner
        # 求交 + 管理权恒 False），故不构成本字段「参与授权」的先例。
        self.harness = harness
        self.unit = unit
        self.role = (role or "system")
        self.token_id = token_id
        self.parent = parent
        self.expires_at = float(expires_at) if expires_at else None
        self.layers_allow = None if layers_allow is None else tuple(layers_allow)
        self.ops_allow = None if ops_allow is None else tuple(ops_allow)
        self.auth_mode = auth_mode
        self.theory_ok = bool(theory_ok)
        self.theory_version = theory_version

    # ---------- 基础判定 ----------

# 生效条件：形参 sensitivity 与 self.clearance 均可被 _rank 映射到模块级常量 SENSITIVITY_ORDER 中时，返回前者排名是否不高于后者；任一不在其中则 _rank 抛 AccessDenied。
    def allows(self, sensitivity: str) -> bool:
        """clearance 是否覆盖该敏感度（可读/可写）。"""
        return _rank(sensitivity) <= _rank(self.clearance)

# 生效条件：无 required 形参或模块级常量前置，仅当 self.expires_at（来自 __init__ 的 expires_at）不为 None 且 time.time() 大于它时返回 True，否则返回 False。
    def expired(self) -> bool:
        return self.expires_at is not None and time.time() > self.expires_at

    @staticmethod
# 生效条件：allow 为 None 时返回 True（未声明=不限制），allow 非 None 时返回 "'*' in allow 或 name in allow" 的布尔结果。
    def _in_scope(allow, name: str) -> bool:
        if allow is None:                     # 未声明 = 不限制（兼容直接构造）
            return True
        return "*" in allow or name in allow

# 生效条件：layer 为假值（None/空串）时以 "knowledge" 参与判定，返回 self._in_scope(self.layers_allow, layer or "knowledge") 的结果。
    def allows_layer(self, layer: str) -> bool:
        return self._in_scope(self.layers_allow, layer or "knowledge")

# 生效条件：op 为假值（None/空串）时以 "" 参与，先经 strip().lower() 归一化，返回 self._in_scope(self.ops_allow, (op or "").strip().lower()) 的结果。
    def allows_op(self, op: str) -> bool:
        return self._in_scope(self.ops_allow, (op or "").strip().lower())

    # ---------- 强制校验（越权即 AccessDenied） ----------

# 生效条件：无 required 形参或模块级常量前置，当 self.expired()（来自 __init__ 的 expires_at 与当前时间比较）为 True 时抛 AccessDenied（带重新签发 hint），否则无操作返回 None。
    def _require_live(self):
        if self.expired():
            raise AccessDenied(
                f"actor={self.actor} 令牌已过期",
                hint="令牌过期不是故障：重新签发并更新 MDCG_TOKEN 后重启宿主"
                     "（python -m md_cg.tokens issue …，README「写入凭据」一节）。")

    # issue #34：op 拒绝按成因分指引——guest（无令牌只读访客）引导配凭据；
    # 有令牌但白名单不含该 op 引导换角色/补授权。「不是故障」安抚语气与
    # 本仓其它 70 处 hint 同口径。
    _GUEST_OP_HINT = (
        "当前为只读访客模式（未检测到写入凭据 MDCG_TOKEN）：读/召回/时间线可用，"
        "写入与管理操作不落盘。这不是故障，配置凭据后即恢复。"
        "要真正落盘请签发并配置写入凭据（README「写入凭据」一节）：\n"
        "  python -m md_cg.tokens issue --role recorder --actor <名> "
        "--clearance internal\n"
        "  setx MDCG_TOKEN \"<token>\"   # 然后重启宿主（DSH/IDE）\n"
        "最小权限可用 --role recorder；op 用法可查 cg(op=\"help\", query=\"write\")。")

# 生效条件：先调用 self._require_live()（过期则抛 AccessDenied）；再要求 self.allows_op(op) 为 True，否则抛 AccessDenied（role=guest 带配凭据 hint，其它角色带补授权 hint）。
    def require_op(self, op: str):
        self._require_live()
        if not self.allows_op(op):
            msg = (f"角色 {self.role} 无权执行 op={op}（作用域 "
                   f"{list(self.ops_allow) if self.ops_allow is not None else '不限'}）")
            if self.role == "guest":
                raise AccessDenied(msg, hint=self._GUEST_OP_HINT)
            raise AccessDenied(
                msg,
                hint=f"当前令牌（actor={self.actor}，角色 {self.role}）的 ops "
                     f"白名单不含 {op}，属正常闸门不是故障。可：①换用含该 op "
                     f"的角色令牌；②由签发者以 --ops-allow 补授权后重新签发"
                     f"（python -m md_cg.tokens issue …，README「写入凭据」一节）。")

# 生效条件：依次要求 self._require_live() 未抛异常、self.theory_ok 为 True、self.can_write 为 True、self.allows(sensitivity) 为 True；任一不满足则抛 AccessDenied。
    def require_write(self, sensitivity: str):
        self._require_live()
        if not self.theory_ok:
            raise AccessDenied(
                "版本层校验未通过（theory_ok=False）：全部写操作被拒，"
                "仅保留 theory 修复入口")
        if not self.can_write:
            raise AccessDenied(
                f"actor={self.actor} 无写权限",
                hint=(self._GUEST_OP_HINT if self.role == "guest" else
                      f"当前令牌（角色 {self.role}）未授予写权限（can_write="
                      f"False），属正常闸门不是故障。请换用可写角色令牌或由"
                      f"签发者重新签发（README「写入凭据」一节）。"))
        if not self.allows(sensitivity):
            raise AccessDenied(
                f"写入敏感度 {sensitivity} 超出 clearance {self.clearance}")

# 生效条件：先要求 self.require_write(sensitivity) 未抛异常；随后将形参 layer 为假值（None/空串）时按 "knowledge" 处理，并要求 self.allows_layer(layer) 为 True，否则抛 AccessDenied。
    def require_layer_write(self, layer: str, sensitivity: str):
        """写层校验：密级 + 层白名单双闸门（核心私有内容不可越权修改）。"""
        self.require_write(sensitivity)
        layer = layer or "knowledge"
        if not self.allows_layer(layer):
            raise AccessDenied(
                f"角色 {self.role} 无权写入 {layer} 层"
                f"（可写层 {list(self.layers_allow) if self.layers_allow is not None else '不限'}）")

# 生效条件：要求 self._require_live() 未抛异常、self.theory_ok 为 True、self.can_admin 为 True 时通过；否则抛 AccessDenied（消息用形参 op 标记操作）。
    def require_admin(self, op: str):
        self._require_live()
        if not self.theory_ok:
            raise AccessDenied(
                f"版本层校验未通过（theory_ok=False）：管理操作 {op} 被拒")
        if not self.can_admin:
            raise AccessDenied(f"actor={self.actor} 无管理权限（{op}）")

# 生效条件：无 required 形参或模块级常量前置，返回包含 self 各属性（tenant/actor/clearance/can_write/can_admin/session/harness/unit/role/token_id/parent/auth_mode/expires_at/theory_ok/theory_version 及 layers_allow/ops_allow）的 dict；其中 layers_allow/ops_allow 为 None 时值为 None，否则 list 化。
    def as_dict(self):
        return {"tenant": self.tenant, "actor": self.actor,
                "clearance": self.clearance, "can_write": self.can_write,
                "can_admin": self.can_admin, "session": self.session,
                "harness": self.harness, "unit": self.unit,
                "role": self.role, "token_id": self.token_id,
                "parent": self.parent, "auth_mode": self.auth_mode,
                "expires_at": self.expires_at,
                "theory_ok": self.theory_ok,
                "theory_version": self.theory_version,
                "layers_allow": (None if self.layers_allow is None
                                 else list(self.layers_allow)),
                "ops_allow": (None if self.ops_allow is None
                              else list(self.ops_allow))}

# 生效条件：无前置；仅返回 tenant/actor/role/clearance/write/admin 的短摘要用于日志与排障，不含 token、密钥材料与能力白名单明细；
    def __repr__(self):
        return (f"Principal(tenant={self.tenant!r}, actor={self.actor!r}, "
                f"role={self.role!r}, clearance={self.clearance!r}, "
                f"write={self.can_write}, admin={self.can_admin})")


# 生效条件：path 为 None 时落至 datapath.aux_root()（默认 ~/.mdcg，可经 MDCG_AUX_ROOT 改）下的 _tenants.json，path 非 None（含空串）时按传入值使用，并在构造内以 self._load() 的返回填充 self.data、以 self.load_error 留存加载期损坏留痕（N124，2026-09-25：登记表损坏/不可读必须可被调用方感知，缺文件不算损坏）。
class TenantRegistry:
    """租户注册表：tenant → {root, clearance_cap, description}。

    默认位置：<registry_dir>/_tenants.json（默认 ~/.mdcg/）。
    设计意图：私有租户的 root 指向仓库外目录，开源仓库里只放 public 租户的根。

    load_error（N124，2026-09-25）：_load 遇「文件在但损坏/不可读」（JSON
    解析失败、OSError、顶层非对象）时留存原因字符串，完好/缺文件为 None——
    供 _resolve_root 等调用方把「静默回落空表」开口成 stderr 告警。
    """

# 生效条件：形参 path 为 None 时取 ~/.mdcg/_tenants.json，否则取 path；self.load_error 置 None 后 self.data 初始化为 _load() 结果（self.path 经 os.path.exists 为真且 JSON 解析为 dict 时取该 dict，否则回落 {"schema":1,"tenants":{}}；文件在但解析失败/OSError/顶层非对象时先置 self.load_error 为原因串，缺文件不置）。
    def __init__(self, path: str = None):
        if path is None:
            path = os.path.join(aux_root(), "_tenants.json")
        self.path = path
        self.load_error = None
        self.data = self._load()

# 生效条件：先置 self.load_error=None；当 self.path 经 os.path.exists 为真且内容可解析为 dict 时返回该 dict；解析失败或 OSError 时置 self.load_error=f"{类型名}: {e}"、顶层 JSON 非对象时置 self.load_error="登记表 JSON 顶层不是对象"；否则（os.path.exists 为假）不留痕；各回落分支均返回 {"schema":1,"tenants":{}}。
    def _load(self):
        self.load_error = None
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    d = json.load(f)
                if isinstance(d, dict):
                    return d
                self.load_error = "登记表 JSON 顶层不是对象"
            except (ValueError, OSError) as e:
                self.load_error = f"{type(e).__name__}: {e}"
        return {"schema": 1, "tenants": {}}

# 生效条件：无 required 形参或模块级常量前置，将 self.data 以 JSON 写入 self.path + ".tmp"，随后 publish（带 Windows 短重试的 os.replace）到 self.path；目录名称为空时用 "." 创建。
    def _save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        publish(tmp, self.path)

# 生效条件：形参 clearance_cap 须为模块级常量 SENSITIVITY_ORDER 成员（否则 _rank 抛 AccessDenied）；形参 tenant/root 提供后写入 self.data["tenants"]（要求 self.data 含 "tenants" 键，否则 KeyError），_save 成功则返回新登记项。
    def register(self, tenant: str, root: str, clearance_cap: str = DEFAULT_SENSITIVITY,
                 description: str = ""):
        _rank(clearance_cap)
        self.data["tenants"][tenant] = {
            "root": os.path.abspath(root),
            "clearance_cap": clearance_cap,
            "description": description,
            "registered_at": time.time(),
        }
        self._save()
        return self.data["tenants"][tenant]

# 生效条件：self.data 含 "tenants" 键（否则 KeyError），且该映射中存在形参 tenant 时返回其值，否则返回 None（.get 缺键回落 None，键存在值为 None 也返回 None）。
    def get(self, tenant: str):
        return self.data["tenants"].get(tenant)

# 生效条件：self.get(tenant) 返回真值（非 None/空 dict 等）时返回 t["root"]（若 t 无 "root" 键则 KeyError）；返回假值时返回 None。
    def root_of(self, tenant: str):
        t = self.get(tenant)
        return t["root"] if t else None

# 生效条件：self.get(tenant) 返回真值时返回 t["clearance_cap"]（缺键则 KeyError）；返回假值时返回模块级常量 DEFAULT_SENSITIVITY。
    def cap_of(self, tenant: str):
        t = self.get(tenant)
        return t["clearance_cap"] if t else DEFAULT_SENSITIVITY

# 生效条件：self.data 含 "tenants" 键时返回其浅拷贝 dict(self.data["tenants"])；该键缺失时按 self.data["tenants"] 取值会 KeyError，无默认回落。
    def all(self):
        return dict(self.data["tenants"])

# 生效条件：cap 由 cap_of(tenant) 决定（形参 tenant 未注册时取模块级常量 DEFAULT_SENSITIVITY）；clearance 为假值（含 None/空串）时 want 取 cap，否则先取 clearance，再在 _rank(want) > _rank(cap) 时夹紧为 cap；actor 为假值时取 tenant；返回 Principal(...)。
    def principal_for(self, tenant: str, actor: str = None, clearance: str = None,
                      can_write: bool = True, can_admin: bool = False,
                      session: str = None) -> Principal:
        """按租户上限夹紧 clearance（调用方不能超过租户上限）。"""
        cap = self.cap_of(tenant)
        want = clearance or cap
        if _rank(want) > _rank(cap):
            want = cap
        return Principal(tenant=tenant, actor=actor or tenant, clearance=want,
                         can_write=can_write, can_admin=can_admin, session=session)


# P1-4（批次 26，外部审查报告）：工具路径参数的根白名单——ingest/export/link
# 的 path/out 是模型可控输入，原样透传 = 任意文件读（/etc/passwd 进图）与
# 任意文件写（evidence export 的 out）。校验语义与 HIVE_READ_ROOTS 同构：
# **env 未设置 = 放开**（默认部署零行为变更，与 2026-09-19 的读放开裁定
# 精神一致）；**设置了 = realpath 落根内否则拒**（fail-closed），`..` 与
# 绝对路径穿越在 realpath 归一后自然被涵盖。支持 os.pathsep 分隔多根。
# 生效条件：env_var 环境变量去空白后为空、或 path 为 None/空串时直接返回（不约束）；否则取 realpath(expanduser(path))，与 env 值按 os.pathsep 切分的每个根做「相等或以根+os.sep 为前缀」判定，任一命中即返回；全部未命中抛 PermissionError（含 what/原 path/realpath/roots 的拒绝说明）。
def check_path_root(path, env_var: str, what: str) -> None:
    raw = (os.environ.get(env_var) or "").strip()
    if not raw:
        return                                   # 未配置 = 放开（部署开关）
    if path is None or str(path).strip() == "":
        return                                   # 无路径参数（如 stat/action）
    roots = []
    for p in raw.split(os.pathsep):
        p = p.strip()
        if p:
            roots.append(os.path.realpath(os.path.expanduser(p)))
    real = os.path.realpath(os.path.expanduser(str(path)))
    for r in roots:
        if real == r or real.startswith(r.rstrip(os.sep) + os.sep):
            return
    raise PermissionError(
        f"{what} 路径超出 {env_var} 白名单，拒绝访问：{path} "
        f"(realpath={real}, roots={roots})——路径类工具参数的根约束"
        "（P1-4），部署用该环境变量声明可读写的根目录")


# 错误处置链路角色集（批次 28 分型）：restricted（错误处置标记）的可见性
# 不走密级 rank——链路角色与平级同为 internal，rank 无法区分「处置者」与
# 「扩散面」。designer=全局观测本职；orchestr=上级节点（拆解派发/裁决
# 收口）；verify=验证本职（错误标记节点是验证的对象）。
_RESTRICTED_READER_ROLES = ("designer", "orchestr", "verify")


# 生效条件：p 为 Principal 或 None；p 为 None 返回 False；p.can_admin 为真（设计者）或 p.role 属 _RESTRICTED_READER_ROLES 时返回 True，否则返回 False。
def can_read_restricted(p) -> bool:
    if p is None:
        return False
    if getattr(p, "can_admin", False):
        return True
    return getattr(p, "role", "") in _RESTRICTED_READER_ROLES