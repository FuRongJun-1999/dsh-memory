# -*- coding: utf-8 -*-
"""带权限的记忆 OS（`MdCGSecure`）+ 审计追加段哈希链工具。

纯搬家（2026-11-11 深度重构·任务 3）：本模块内容此前内联在 `md_cg/mdcos.py`
末尾（原 :6749-:7893，49 个方法 / 1054 行）。搬出的理由只有一条——`mdcos.py`
已是 7.3k 行的巨型模块，而 `MdCGSecure` 是**其上独立的一层**（`MdCGOS` 的子类），
与 `MdCGOS` 的方法体零交织：它只经 `super()` 调用父类，另有 7 处**钩子式
override**（`_scan_nodes` / `_candidates` / `_neg_coverage` / `search_rrf` /
`health_os` / `verify` …），这些 override **必须留在类体内**——它们靠虚分派
生效（`md_cg/mdcg.py:4825` 一类鸭子判据比对 `type(self)._seal_content`），
外置成模块函数或多重继承都会静默失效。故本次是**整类搬运**，不是拆类。

对外契约不变：`md_cg.mdcos.MdCGSecure` 仍是**同一个类对象**（`mdcos.py` 保留
`from .mdcos_secure import ...` 的 re-export shim，标注 DEPRECATED(shim)），
`isinstance` / `__mro__` / 方法解析顺序与搬家前逐位一致。

审计链常量与四个模块函数（`AUDIT_CHAIN_*` / `_audit_sign_body` /
`_audit_last_sig` / `_audit_chain_link` / `_audit_chain_verify`）随类一起搬：
它们本来就是 `MdCGSecure._audit` 与 `MdCGOS.append_audit` 的共同体，且被
`md_cg/test_issue472_audit_chain.py` 以 `mdcos.<名>` 访问——shim 一并覆盖。
"""
import hashlib
import io
import json
import os
import sys
import time

from . import crypto, sustain, subgraph, protect, consistency, trust, roleviews
from .fsutil import node_write_lock
from .mdcos import MdCGOS, UNATTRIBUTED_SESSION, _read_foreign_sampled
from .security import (Principal, AccessDenied, SENSITIVITY_ORDER,
                       DEFAULT_SENSITIVITY, _rank)

# 生效条件：以 root 构造并把 **kw 透传父类，principal 为假值（None）时回落新建 Principal()、否则用传入的 principal，其 actor 作为 actor 传给父类，master_key 原样交给 _init_crypto；
class MdCGSecure(MdCGOS):
    """带权限的记忆 OS：租户 + 密级（clearance）× 节点敏感度（sensitivity）。

    动机：灵枢是开源仓库，私有记忆不能混进公开根。本类保证：
      · 读隔离：clearance 之下的节点对调用方不可见（search/recall/get 一致过滤）
      · 写隔离：写入高于 clearance 的敏感度 → AccessDenied
      · 管理隔离：forget/restore/review_decide 需 can_admin
      · 审计带 tenant/actor/session（可追溯到哪个会话做了什么）
    """

# 生效条件：传入 root 时 principal 为假值（None 等）则新建 Principal()，以 self.principal.actor 作 actor 调父类 MdCGOS.__init__(root, actor=..., **kw)，再设 self.session = self.principal.session 并执行 self._init_crypto(master_key)（master_key 缺省 None）。
    def __init__(self, root: str, principal: Principal = None,
                 master_key=None, **kw):
        self.principal = principal or Principal()
        self.kek = None
        self.dek = None
        self._crypto_error = None
        #: #152③（2026-10-12 DSH 端）：解密产物缓存（键见 `_plain_key`）。
        #: 显式初始化（而非惰性）：lock/unlock 的清缓存路径要能无条件命中它。
        self._plain_cache = {}
        #: 缺陷二（2026-10-10 DSH 端独立复核）：跨身份读**计数恒完整**（与采样
        #: 开关无关）——原实现把自增放在「采样开启」之后 ⇒ 默认配置下该属性从不
        #: 被创建、越权探测信号完全丢失。此处显式初始化，使 `crypto_status()` 的
        #: `read_foreign_seen` 恒可读、实例上稳定存在。
        self._read_foreign_seen = 0
        super().__init__(root, actor=self.principal.actor, **kw)
        self.session = self.principal.session
        self._init_crypto(master_key)

    # ---------- 私有内容加密（密钥即访问权 + 身份一致性识别）----------

# 生效条件：master_key 非 None 时取 self._resolve_master_key(master_key)、为 None 时取 crypto.load_master_key()；kek 为假值时置 _crypto_error="no_master_key" 且 self.kek=self.dek=None 并返回；否则置 self.kek 并调 crypto.provision_dek(self.root, kek, tenant, actor, clearance=...) 得 dek；捕获 crypto.CryptoError 或 OSError 时置 _crypto_error=str(e) 且 self.kek=self.dek=None。
    def _init_crypto(self, master_key=None):
        """解析 KEK（显式 → 环境变量 → 仓库外主密钥文件），签发本身份 DEK。

        主密钥缺失时自动生成于仓库外 `~/.mdcg/master.key`（0600）；
        仍取不到才 `dek=None`，写 private/secret 时 fail-closed。
        """
        try:
            kek = (self._resolve_master_key(master_key)
                   if master_key is not None
                   else crypto.load_master_key())
            if not kek:
                self._crypto_error = "no_master_key"
                self.kek = self.dek = None
                return
            self.kek = kek
            self.dek = crypto.provision_dek(
                self.root, kek, self.principal.tenant, self.principal.actor,
                clearance=self.principal.clearance)
            self._crypto_error = None
        except (crypto.CryptoError, OSError) as e:
            self._crypto_error = str(e)
            self.kek = self.dek = None

    @staticmethod
# 生效条件：master_key 为 bytes/bytearray 时直接取字节，否则转 str 去空白后若该串是存在路径则读文件内容，len==64 走 bytes.fromhex、否则走 base64 解码，所得长度不等于 crypto.KEY_LEN 时抛 CryptoError；
    def _resolve_master_key(master_key):
        """接受 32B bytes / 64 位 hex / base64 / 密钥文件路径。"""
        if isinstance(master_key, (bytes, bytearray)):
            k = bytes(master_key)
        else:
            s = str(master_key).strip()
            if os.path.exists(s):
                with open(s, encoding="utf-8") as f:
                    s = f.read().strip()
            try:
                k = bytes.fromhex(s) if len(s) == 64 else crypto._b64d(s)
            except ValueError as e:
                raise crypto.CryptoError(
                    "主密钥须为 32 字节 / 64 位 hex / base64 / 密钥文件") from e
        if len(k) != crypto.KEY_LEN:
            raise crypto.CryptoError("主密钥须为 32 字节")
        return k

# 生效条件：调用 self._init_crypto(master_key)；master_key 为 None 时回落环境变量与主密钥文件，密钥缺失或长度非 32 字节抛 crypto.CryptoError；成功后返回 crypto_status()；
    def unlock(self, master_key=None):
        """运行时解锁（显式密钥 / 重新加载环境变量或主密钥文件）。

        #152（2026-10-12 DSH 端，缓存面并入本件以免与他组同文件互踩）：解锁是
        **密钥面突变**——读缓存（readcache）与查询热缓存（hotcache）里可能留着
        上一密钥态生成的读数 ⇒ 一并失效，避免跨密钥态串结果。
        """
        self._init_crypto(master_key)
        self._invalidate_caches_on_key_change()
        return self.crypto_status()

# 生效条件：无前置；丢弃内存中的 self.kek / self.dek 并置 _crypto_error="locked"（已落盘密文不受影响）；返回 crypto_status()；
    def lock(self):
        """锁定：丢弃内存中的密钥（已落盘密文不受影响）。

        #152（同上）：锁定同样改密钥面 ⇒ 清 readcache + 失效 hotcache。
        """
        self.kek = self.dek = None
        self._crypto_error = "locked"
        self._invalidate_caches_on_key_change()
        return self.crypto_status()

# 生效条件：无条件尝试清 readcache 并失效 hotcache；任一模块不可用/抛异常时静默跳过（缓存面清理不得阻断锁/解锁这一主路径）；
    def _invalidate_caches_on_key_change(self):
        """密钥面突变后清缓存（#152）。失败不阻断锁/解锁。"""
        # #152③：解密产物缓存**整清**——锁后内存里不留任何明文（fail-closed
        # 与 `get()` 的 lock 语义一致：`self.dek` 为假时 `_open_content` 恒
        # 返 None，缓存里若还留着明文，任何绕过 `_open_content` 的读面都成了
        # 泄漏面）。放在最前：即使下面的模块 import 失败也必须清掉明文。
        try:
            _pc = getattr(self, "_plain_cache", None)
            if _pc is not None:
                _pc.clear()
        except Exception:                                      # noqa: BLE001
            pass
        try:
            from . import readcache as _rc
            _rc.clear(self)
        except Exception:                                      # noqa: BLE001
            pass
        try:
            from . import hotcache as _hc
            _hc.invalidate(self)
        except Exception:                                      # noqa: BLE001
            pass

# 生效条件：调用 crypto_status 时，返回当前加密状态字典；unlocked 取决于 self.dek is not None，kek_fp 在 self.kek 为假值时取 None，否则取 crypto.kek_fingerprint(self.kek)；read_foreign_seen 取进程内跨身份失败解密计数（缺陷二：计数恒完整、与采样开关无关，可被体检面读到）。
    def crypto_status(self):
        """当前加密状态（不含密钥材料）。"""
        return {
            "unlocked": self.dek is not None,
            "tenant": self.principal.tenant,
            "actor": self.principal.actor,
            "id_fp": crypto.identity_fingerprint(self.principal.tenant,
                                                 self.principal.actor),
            "kek_fp": crypto.kek_fingerprint(self.kek) if self.kek else None,
            "encrypted_levels": list(crypto.ENCRYPTED_LEVELS),
            "error": self._crypto_error,
            "keys_file": crypto.keys_path(self.root),
            "envelopes": crypto.envelopes(self.root),
            # 缺陷二：跨身份读计数**恒完整**（默认采样关闭时也增长），透出到
            # 既有体检面（health_os / profile 都含 crypto_status）——越权探测
            # 信号不再因默认不落审计而彻底不可观测。
            "read_foreign_seen": getattr(self, "_read_foreign_seen", 0),
        }

# 生效条件：sens 取 sensitivity or DEFAULT_SENSITIVITY，若 sens 不在 crypto.ENCRYPTED_LEVELS 或 content 已加密则原样返回 content；否则 self.dek 为假值时写 seal_denied 审计并抛 crypto.LockedError，有 dek 时 seal_node 并写 seal 审计后返回密文。
    def _seal_content(self, node_id, content, sensitivity=None):
        """私有内容（private / secret）写入前加密；无密钥 → fail-closed。"""
        sens = sensitivity or DEFAULT_SENSITIVITY
        if not crypto.is_encrypted_level(sens) or crypto.is_encrypted(content):
            return content
        if not self.dek:
            crypto.audit(self.root, {"op": "seal_denied", "node_id": node_id,
                                     "tenant": self.principal.tenant,
                                     "actor": self.principal.actor,
                                     "reason": self._crypto_error or "no_dek"})
            raise crypto.LockedError(
                f"{sens} 内容需加密，但当前无可用密钥（{self._crypto_error}）")
        # issue #165：裁决落盘时按**提案原始写入者**封装（override 由裁决分支置入，
        # 仅对本次目标节点生效；不动读面、不新建信封、不改磁盘格式）。
        actor, dek = self.principal.actor, self.dek
        ov = getattr(self, "_seal_override", None)
        if ov and ov[0] == node_id:      # 仅目标节点（防串到旁节点）
            actor, dek = ov[1], ov[2]
        sealed = crypto.seal_node(content, dek, node_id,
                                  self.principal.tenant, actor)
        rec = {"op": "seal", "node_id": node_id, "sensitivity": sens,
               "tenant": self.principal.tenant,
               "actor": self.principal.actor}
        if actor != self.principal.actor:
            rec["sealed_as"] = actor
        crypto.audit(self.root, rec)
        return sealed

    def _proposer_seal_identity(self, owner, sensitivity=None):
        """裁决落盘时加密级正文应使用的封装身份（原写入者）；只用于封装，不用于读。

        非加密级 / 无写入者 → None（走原路径，既有 public/internal 行为逐位不变）；
        取不到写入者已登记的信封 → crypto.LockedError（由调用方 fail-closed 不落盘）。
        """
        owner = str(owner or "").strip()
        if not owner or not crypto.is_encrypted_level(sensitivity or DEFAULT_SENSITIVITY):
            return None
        return owner, crypto.unwrap_dek(self.root, self.kek,
                                        self.principal.tenant, owner)

# 生效条件：content 为 None 或非加密时原样返回 content；加密时先用**本次读取所得的 frontmatter**（sensitivity/session）复核读可见性，不可见即写 read_denied 审计并返回 None；可见但 self.dek 为假值时写 read_locked 审计并返回 None；随后**无条件**调 crypto.open_node（唯一的完整性校验处）——成功即返回明文（指纹fp 是什么都不影响解密）；仅当抛 CryptoError 时才用**密文自带**的非敏感指纹 enc_id_fp 给这次失败分类：指纹有值且 ≠ 本方指纹 ⇒ 按采样写 read_foreign 审计（预期隔离）；否则写 open_failed 审计（真异常，含旧格式无指纹）。
    def _open_content(self, node_id, fm, content):
        """密文解封；无密钥 / 身份不符 / **读不可见** → None（不可读），失败留审计。"""
        if content is None or not crypto.is_encrypted(content):
            return content
        # issue #146③-a：**密级与封装形态一致性闸**（fail-closed，不抛）。
        # 现场：`crypto._node_aad` 只绑 node_id/tenant/actor，**不绑 sensitivity**
        # （见下方 B1 注释）——故 fm.sensitivity 是**未认证明文段**，手改密级行
        # 即改读可见性判据：把 `sensitivity: private` 改成 `internal` 后，
        # `_readable` 放行、密文照解 ⇒ **他人会话读到密文正文的明文**。
        # 判据（fail-closed 不可读，而非抛异常）：密文（is_encrypted 为真）必须
        # 配**加密档**密级（crypto.ENCRYPTED_LEVELS）；声明值缺失/非法/非加密档
        # 一律判不可读并留审计。**不做**「把 sensitivity 绑进 AAD」——那需要
        # 密文格式迁移，属待裁项（本批显式不做）。
        _sens = (fm or {}).get("sensitivity")
        if not crypto.is_encrypted_level(_sens, strict=True):
            crypto.audit(self.root, {"op": "read_denied", "node_id": node_id,
                                     "tenant": self.principal.tenant,
                                     "actor": self.principal.actor,
                                     "reason": "密级与封装形态不一致：密文配非加密档"
                                               "（声明=%r）" % (_sens,)})
            return None
        # N213（2026-09-28）：绑定档（private/secret）正文只有加密后才可能落盘，
        # 故所有解密出口都汇到本函数——把「读可见性」闸设在这里 = 一次接线覆盖
        # 全部读面（get / search 的 _read_many 正文水合 / reach / recent_events）。
        # 判据用**与正文同一次读取所得的 fm**（同源 ⇒ 无 TOCTOU、无额外 IO），
        # 而不是任何内存索引条目：索引可能是上一代快照（陈旧条目说 internal、
        # 盘上已是他进程写的 private/S2），据此放行会把密文解成明文返回。
        # 与 _readable 同口径（clearance × sensitivity ∧ 会话绑定，设计者豁免）。
        try:
            _vis = self._readable({"sensitivity": (fm or {}).get("sensitivity"),
                                   "session": (fm or {}).get("session")})
        except Exception:                     # noqa: BLE001 —— 判据载体异常按不可读
            _vis = False
        if not _vis:
            crypto.audit(self.root, {"op": "read_denied", "node_id": node_id,
                                     "tenant": self.principal.tenant,
                                     "actor": self.principal.actor,
                                     "reason": "读隔离：密文不可见"})
            return None
        if not self.dek:
            crypto.audit(self.root, {"op": "read_locked", "node_id": node_id,
                                     "tenant": self.principal.tenant,
                                     "actor": self.principal.actor,
                                     "reason": self._crypto_error or "no_dek"})
            return None
        # B1（2026-10-10 设计者裁定）＋ **同日 DSH 端独立复核纠正**：
        # **完整性校验（MAC）是唯一判据**——先无条件试解密。`open_node` 是唯一做
        # 认证标签校验的地方；只有它**失败**（CryptoError）时，才用密文自带的
        # **非敏感**指纹 `enc_id_fp` 给这次失败**分类**：
        #   · 指纹有值且 ≠ 本方指纹 ⇒ 预期隔离（`read_foreign`，按采样落审计）；
        #   · 其余（含旧格式无该段）⇒ 真异常（`open_failed`）。
        #
        # 为何**不再**用指纹**短路**解密：`enc_id_fp` 是密文块内的**未认证明文段**
        # （`crypto._node_aad` 只绑 node_id/tenant/actor，不含它；`open_node` 解密前
        # 丢弃它）——让一个可被篡改的字段决定「是否执行唯一的完整性校验」，会派生
        # 两个可操纵后果：
        #   ① 假阴性：只改指纹段（密文本体完好）⇒ 真密文被**静默拒读**、审计零留痕；
        #   ② 假阳性：谎报指纹＝读方自己（或写 `fm.enc_id_fp`）⇒ 走到解密 ⇒ 失败记
        #      `open_failed`（本该是「预期隔离」）⇒ 误报口径又回来了。
        # 判据一律取**密文自带**指纹（与正文同源），不再回落可写 frontmatter
        # `fm.enc_id_fp`——那与「判据取密文自带指纹…无 TOCTOU」自述不符。
        # #152③（2026-10-12 DSH 端）：**解密产物缓存**。实测每查询逐节点
        # AEAD 解密：`_read` 命中缓存后 0.25 µs/节点，而 `_read + 解密` 为
        # 160.18 µs/节点（解密占 99.8%）——3000 节点一次查询外推 480 ms，
        # 而 `internal` 库仅 0.14 µs/节点（密文库检索的**全部**额外成本几乎
        # 都在这里）。缓存键取 `(node_id, 密文摘要, dek 指纹)`：
        #   · 明文是 `(密文, dek, node_id, tenant, actor)` 的**纯函数**——
        #     键含密文摘要 ⇒ 任何写盘（AEAD 随机 nonce 使密文逐次不同）**自动
        #     失效**，无需另接 path_gen 哨兵（#153① 的容器别名污染另由
        #     hotcache 出口拷贝收口，两者互补）；
        #   · 键含 dek 指纹 ⇒ lock/unlock 换密钥态自然失配（与 `bm25.access_key`
        #     的 `sha256(dek)` 同款范式）；**另**在 lock/unlock 整清（见
        #     `_invalidate_caches_on_key_change`），保证锁后内存里不留明文。
        # 只缓存**成功**的解密结果（失败/隔离不缓存，与 readcache 的 C-3 同向）。
        _ck = self._plain_key(node_id, content)
        _hit = self._plain_get(_ck)
        if _hit is not None:
            return _hit
        try:
            _plain = crypto.open_node(content, self.dek, node_id,
                                      self.principal.tenant, self.principal.actor)
        except crypto.CryptoError as e:
            declared = crypto.enc_id_fp(content)
            mine = crypto.identity_fingerprint(self.principal.tenant,
                                               self.principal.actor)
            if declared and declared != mine:
                if _read_foreign_sampled(self):
                    crypto.audit(self.root, {
                        "op": "read_foreign", "node_id": node_id,
                        "tenant": self.principal.tenant,
                        "actor": self.principal.actor,
                        "reason": "读隔离：密文属他身份（预期，非篡改）"})
                return None
            crypto.audit(self.root, {"op": "open_failed", "node_id": node_id,
                                     "tenant": self.principal.tenant,
                                     "actor": self.principal.actor,
                                     "reason": str(e)[:120]})
            return None
        self._plain_put(_ck, _plain)
        return _plain

# 生效条件：node_id 与密文 content 给定；返回 (node_id, sha256(content) 前 16 位, dek 指纹或 None) 三元组——明文缓存的唯一键（#152③）。
    def _plain_key(self, node_id, content):
        """解密产物缓存的键（#152③）——纯函数输入的完备刻画。"""
        _d = hashlib.sha256(content.encode("utf-8", "replace")).hexdigest()[:16]
        _dek = self.dek
        _fp = hashlib.sha256(_dek).hexdigest()[:16] if _dek else None
        return (node_id, _d, _fp)

# 生效条件：key 在 self._plain_cache 中时把该条目移到末尾并返回其明文；不在则返回 None；缓存未初始化时惰性建空。
    def _plain_get(self, key):
        c = getattr(self, "_plain_cache", None)
        if c is None:
            c = self._plain_cache = {}
            return None
        if key in c:
            v = c.pop(key)
            c[key] = v
            return v
        return None

# 生效条件：无条件把 key→plain 写入 self._plain_cache 并按上限（MDCG_PLAIN_CACHE_MAX，缺省 256）淘汰最旧条目；写入失败不影响返回。
    def _plain_put(self, key, plain):
        c = getattr(self, "_plain_cache", None)
        if c is None:
            c = self._plain_cache = {}
        c[key] = plain
        try:
            _cap = int(os.environ.get("MDCG_PLAIN_CACHE_MAX") or 256)
        except ValueError:
            _cap = 256
        while len(c) > max(1, _cap):
            c.pop(next(iter(c)), None)

    # ---------- 索引：把 role / sensitivity / 写入归属一并索引 ----------

# 生效条件：self.session 与 self.principal.session 不同（请求级/库层显式覆盖的声明值）时返回 self.session；principal 未带 session_auto 标记或该标记为 False（env/显式构造的声明来源）时返回 self.session；标记为 True 且两值相同（未获声明的进程自动随机）且 sens 经 _rank 判定达到 private 档（含 secret；非法密级回落视为未达到、不抛）时返回 self.session（授权绑定档豁免）；其余（自动随机 × 非绑定档）返回模块常量 UNATTRIBUTED_SESSION。
    def _attributed_session(self, sens=None):
        """**写归因的会话三态解析（单一真源，2026-10-07 设计者裁定）**。

        态① env：部署侧注入（MDCG_SESSION / DSH_SESSION_ID；`_apply_attribution`
        与 serve 注入时已清 session_auto）→ 原值；
        态② 请求声明：call_tool 请求级覆盖（cg.session ≠ principal.session）
        或库层显式构造 session → 原值；
        态③ 都无：Principal 构造时的**进程自动随机**（session_auto=True 且
        未被覆盖）→ `UNATTRIBUTED_SESSION`（显式、跨进程可辨认、可审计）
        ——不再把不可辨认的随机 hex 写进任何写归因面。

        例外（**授权绑定档豁免**）：sens 达到 private 档时保持进程随机——
        绑定档的落盘值参与读回判据（`_readable` 的 `nsess ==
        principal.session`），改写成 unattributed 会让写者读不回自己刚写的
        private/secret 节点（既有语义破坏）。该豁免面由
        test_session_identity_tristate 的 D 组钉死。
        """
        sess = self.session
        if not getattr(self.principal, "session_auto", False):
            return sess                  # env / 显式构造：声明来源，原值
        if sess != self.principal.session:
            return sess                  # 请求级/库层显式覆盖：声明有效
        try:
            bound = sens is not None and _rank(sens) >= _rank("private")
        except AccessDenied:
            bound = False                # 非法密级不在此抛（写侧 _rank 校验在先）
        if bound:
            return sess                  # 授权绑定档：保持随机（读回判据锚定它）
        return UNATTRIBUTED_SESSION

# 生效条件：对传入的 kw 生效——writer/session 缺键时分别落 self.principal.actor 与 _attributed_session(sens)（写归因三态：env/请求声明→原值；未声明的进程自动随机→unattributed，私有档豁免见该函数），self.principal.harness 为真值时 harness 缺键才落该值，已存在的键一律不覆盖。
    def _attribution(self, kw, sens=None):
        """写入归属注入（归因维度，不参与授权）。

        writer/session/harness 缺省取当前身份（session 经 `_attributed_session`
        三态解析，2026-10-07）；库层调用方可显式传值覆盖（如会话台账写入），
        MCP 面不透传该入参——客户端不得伪造归属。
        writer 语义=最后写入者（更新路径自然刷新），created_at 记首写。
        """
        kw.setdefault("writer", self.principal.actor)
        kw.setdefault("session", self._attributed_session(sens))
        if self.principal.harness:
            kw.setdefault("harness", self.principal.harness)
        return kw

# 生效条件：在 super()._scan_nodes() 结果上逐节点重新 _read，仅当读出的 fm 为真值时把 role、sensitivity（假值回落 DEFAULT_SENSITIVITY）、writer、session、content_kind（角色化读取视图的候选资格维度，第四阶段 6.1）写回该条目。
    def _scan_nodes(self):
        nodes = super()._scan_nodes()
        for nid, e in nodes.items():
            fm, _c = self._read(e)
            if fm:
                e["role"] = fm.get("role")
                e["sensitivity"] = fm.get("sensitivity") or DEFAULT_SENSITIVITY
                e["writer"] = fm.get("writer")
                e["session"] = fm.get("session")
                e["content_kind"] = fm.get("content_kind")
        return nodes

# 生效条件：仅当 self.index["nodes"] 中已存在 nid 时，把该条目的 sensitivity 置为 sens 并标记进 self._dirty；nid 不存在则不做任何事、无返回。
    def _index_sensitivity(self, nid, sens):
        e = self.index["nodes"].get(nid)
        if e is not None:
            e["sensitivity"] = sens
            self._dirty[nid] = e

    # ---------- 写：权限校验 ----------

# 生效条件：declared 为真值时原样返回（显式声明优先，仍由库层落盘闸判「声明↔落盘」一致性）；declared 为假值且 node_id 有既有节点时返回其密级（索引快照优先、缺条目回读节点文件）；declared 为假值且无既有节点、也未被判为坏节点隔离（self._quarantined）时返回 DEFAULT_SENSITIVITY；既有节点存在而密级判不了（损坏/非法/读不出）或被隔离时抛 AccessDenied（fail-closed，不回落缺省档）。
    def _write_sensitivity(self, node_id, declared):
        """写面密级解析单点（issue #297）：未声明则**继承既有节点密级**。

        病象：`add`/`propose` 此前一律 `sensitivity or DEFAULT_SENSITIVITY`。
        而 `MdCG.add` 是**全量重建 fm**——层位（N221）、生命周期状态、检验强度、
        验证态、依赖、双时间轴都逐列显式继承了，密级却是唯一没接继承的那一列。
        于是同 id 改写既有 private 节点、调用方不重传 sensitivity（LLM 代理更新
        记忆时通常不带）时，节点被重建为 `internal` **明文**落盘，无令牌访客
        `cg(op=read)` 即可读到新正文；缺省 `MDCG_AUTONOMY=confirm` 档下变更单
        记录与 accept 回执里的 sensitivity 也已是 internal，**全程无降密级提示**。

        口径（与仓内既有继承语义同向，「显式传入优先；否则取旧值」）：
          · 显式声明 → 原样返回。主动改密级是合法动作，仍走
            `_check_sensitivity_landing` 的「声明↔落盘」一致性闸；
          · 未声明 + **无既有节点** → `DEFAULT_SENSITIVITY`（新写入面零变化）；
          · 未声明 + **有既有节点** → 继承其密级；
          · 未声明 + 有既有节点而密级**判不了**（值非法 / 读不出）→ fail-closed
            抛 `AccessDenied`，不静默回落明文档（与 #164「判不了不生成」同口径）。

        取既有密级优先**索引快照**（元数据明文，免读盘/免解密），索引无条目才回读
        节点文件——与 `MdCG.add` 取 prev_entry/prev_state 的同一顺序（索引陈旧
        时靠回读兜底，不把「本进程没这条」当成「库里没这条」）。

        判据面只读密级、**不改**任何状态：本方法不落盘、不动索引、不建目录。
        """
        if declared:
            return declared
        # issue #322（复核补）：**继承读必须看到他进程已落盘的密级**。
        # 病象：`subgraph.node_sensitivity` 优先取**本进程内存索引**的
        # `sensitivity` 键（subgraph.py:383），而跨进程代际感知
        # （`_maybe_reload_index`）此前只在读面/部分写面接线——同 id 两进程
        # 「A 声明 internal 覆写、B 未声明继承」时，B 按**陈旧索引**（seed 的
        # public）落盘，把 A 刚写的 internal 静默降级（探针
        # `.tmp/u06/probe_secure_add.py` 实测：无锁 6/6 轮降级；只加 add 锁
        # 仍 3/6 轮，因为锁只保证互斥、不保证读到新值）。
        # 故在**锁内、读之前**做一次代际探活（本仓既有单点惯例，见
        # forgetting.py:195）：签名未变时零成本返回 False；变了才重载。
        _probe = getattr(self, "_maybe_reload_index", None)
        if callable(_probe):
            _probe()
        try:
            prev = subgraph.node_sensitivity(self, node_id)
        except AccessDenied:
            raise
        except Exception as exc:                       # noqa: BLE001
            raise AccessDenied(
                "写入 %r 未声明 sensitivity，而既有节点密级读不出来（%s）——"
                "fail-closed 拒绝，不回落缺省档（issue #297）"
                % (node_id, exc)) from exc
        if prev:
            return prev
        # prev 为假有三种成因、后果相反，必须区分（不区分就是本件的病象）：
        #   ① 真无此节点 → 新写，回落缺省档（新写入面零变化）；
        #   ② 有节点但密级非法/读不出 → fail-closed；
        #   ③ 该 id 已被判为**坏节点隔离**（#146）→ 盘面有文件、索引与读面都没有
        #      → 密级判不了 → fail-closed（隔离它的理由正是「密级坏掉的节点若被
        #      当默认档消费，等于静默降级为明文」，写面按缺省档写就是同一件事）。
        try:
            exists = bool(self.get(node_id))
        except Exception:                              # noqa: BLE001
            exists = True                              # 读不出来＝判不了 ⇒ fail-closed
        if not exists:
            _q = (getattr(self, "_quarantined", None) or {}).get(node_id)
            if not _q:
                return DEFAULT_SENSITIVITY
            raise AccessDenied(
                "写入 %r 未声明 sensitivity，而该 id 已被判为坏节点隔离"
                "（%s：%s）——密级判不了，fail-closed 拒绝；若确认要按某档"
                "写入，请显式声明 sensitivity（issue #297）"
                % (node_id, _q.get("path"), _q.get("reason")))
        raise AccessDenied(
            "写入 %r 未声明 sensitivity，而既有节点密级判不了（缺/非法）——"
            "fail-closed 拒绝，不回落缺省档（issue #297）" % (node_id,))

# 生效条件：调用方未声明 sensitivity 时先经 _write_sensitivity 解析出 sens（issue #297：既有节点**继承旧密级**、新节点回落 DEFAULT_SENSITIVITY、既有节点密级判不了则 fail-closed 抛 AccessDenied），再 _rank(sens) 并 principal.require_layer_write(layer, sens)，再 _attribution(kw, sens)（会话归因走三态解析）后转 super().add（并把**原始声明** sensitivity 以 declared_sensitivity 键并传，供库层落盘闸判「声明↔落盘」一致性；未声明时为 None），最后按下发的 nid 调 _index_sensitivity 并返回 nid。
    def add(self, node_id: str, content: str, layer: str = "knowledge",
            sensitivity: str = None, **kw) -> str:
        # issue #322（复核补）：本层在 super().add 之前就要**读既有节点**做密级继承
        # （_write_sensitivity 内部 get() + subgraph.node_sensitivity），是典型的
        # 「读旧值 → 据此落盘」；锁若只在 MdCGOS.add 里，这段读改写仍在锁外
        # （并发下按陈旧密级落盘）。故本层整段持同一把 node 锁——同线程重入由
        # fsutil._ReentrantFileLock 按深度计数，super().add 再取不会自锁。
        with node_write_lock(self, node_id):
            sens = self._write_sensitivity(node_id, sensitivity)
            _rank(sens)
            # issue #708/#709（2026-10-28）：把调用方已经取得的复核单元透传给闸。
            # 此前这里只传 (layer, sens)，`reviewed_by` 虽在 **kw 里却从未被消费 ⇒
            # 审计节点与 accept 落盘都被同一个闸挡住。
            #
            # **必须 pop 而不是 kw.get**：`reviewed_by` 是**写入闸的输入参数**，不是记忆
            # 的元数据。若留在 kw 里，它会经 super().add(**kw) 落进 frontmatter
            # （实测：`test_i50c` 的 B1 逐键对拍报出 `reviewed_by: null` 的白名单外差异）。
            _reviewers = kw.pop("reviewed_by", None)
            self.principal.require_layer_write(layer, sens, reviewers=_reviewers)
            self._attribution(kw, sens)
            # B2（2026-09-30）：`sens` 是归一后的落盘值，`sensitivity` 才是调用方
            # 的**原始声明**（None=未声明）。两者必须分别下传——库层 `_write_node`
            # 的密级闸据此判「声明 private 而落 internal」这类静默降级；把归一值
            # 当声明传会让闸永远看不出差异（它比的就是同一个值）。
            nid = super().add(node_id, content, layer=layer, sensitivity=sens,
                              declared_sensitivity=sensitivity, **kw)
            self._index_sensitivity(nid, sens)
            return nid

# 生效条件：sens 经 _write_sensitivity（id 走基类单点 _rejected_nid）解析——#439：未声明且有既有节点 ⇒ 继承其密级、显式声明原样优先、既有密级判不了则 fail-closed 抛 AccessDenied；先 principal.require_layer_write("rejected", sens) 与 _attribution(kw, sens)（会话归因走三态解析）后转 super().add_rejected，最后按下发的 nid 调 _index_sensitivity 并返回 nid。
    def add_rejected(self, hypothesis: str, reason: str, sensitivity: str = None, **kw) -> str:
        # issue #439（2026-10-17 U05b）：`sensitivity or DEFAULT_SENSITIVITY` 在**继承
        # 判定之前**把「未声明 + 有既有节点」钉死成 internal ⇒ `_write_sensitivity`
        # 的继承分支永不触发（#297 单点此前只接了 add/propose 两个入口）。id 口径走
        # 基类单点 `_rejected_nid`，不在本层复制 sha1 写法。
        nid = self._rejected_nid(hypothesis)
        sens = self._write_sensitivity(nid, sensitivity)
        self.principal.require_layer_write("rejected", sens)
        self._attribution(kw, sens)
        # 幂等语义（Lead 裁定）：基类命中既有 id 时**不重写**（直接 return），
        # 重入路径上不该产生任何副作用 ⇒ 只在**实际落盘**分支写索引。
        _wrote = not self._node_exists(nid)
        out = super().add_rejected(hypothesis, reason, sensitivity=sens, **kw)
        if _wrote:
            self._index_sensitivity(out, sens)
        return out

# 生效条件：sens 经 _write_sensitivity（id 走基类单点 _unresolved_nid）解析——#439：未声明且有既有工单 ⇒ 继承其密级、显式声明原样优先、判不了 fail-closed；先 principal.require_layer_write("unresolved", sens) 与 _attribution(kw, sens)（会话归因走三态解析）后转 super().add_unresolved(question, known_clues, goal)，最后调 _index_sensitivity 并返回 nid。
    def add_unresolved(self, question: str, known_clues: str = "", goal: str = "",
                       sensitivity: str = None, **kw) -> str:
        # issue #439：同 add_rejected —— id 口径走基类单点 _unresolved_nid（身份文本
        # topic 优先、缺省 question，与基类幂等键逐字一致），密级走 _write_sensitivity。
        nid = self._unresolved_nid(question, kw.get("topic"))
        sens = self._write_sensitivity(nid, sensitivity)
        self.principal.require_layer_write("unresolved", sens)
        self._attribution(kw, sens)
        # 既有 id ⇒ 基类走 _refresh_unresolved（只重渲染正文、fm/密级不动）⇒ 非
        # 实际落盘分支，不写索引（幂等收窄，同 add_rejected）。
        _wrote = not self._node_exists(nid)
        out = super().add_unresolved(question, known_clues, goal, sensitivity=sens, **kw)
        if _wrote:
            self._index_sensitivity(out, sens)
        return out

# 生效条件：调用方未声明 sensitivity 时先经 _write_sensitivity 解析出 sens（issue #297：既有节点**继承旧密级**——缺省 confirm 档下提案记录若在入队时就已降成 internal，accept 只会照抄该值，故继承必须发生在这里、不能只补落盘面），再 principal.require_layer_write(kw.get("layer", "knowledge"), sens)（缺省与基类 MdCGOS.propose 的 layer="knowledge" 一致——此前误用 or "contextual" 导致校验层与落盘层错位：knowledge-only 身份被误拒 / contextual-only 身份入队成死提案，2026-09-25 缺陷 #5），再按**既有节点真层真密级**调 protect.require_layer（#346：提案者自己落不了盘的覆写不入队），最后转 super().propose(node_id, content, sensitivity=sens) 并返回其结果。
    def propose(self, node_id: str, content: str, sensitivity: str = None, **kw):
        sens = self._write_sensitivity(node_id, sensitivity)
        # issue #709 连带发现（2026-10-28）：propose **不落记忆盘**（只把候选写进 inbox），
        # 却按目标层要求复核单元 ⇒ enforce 下死锁：要写 knowledge 需 reflect、要 reflect
        # 需裁决、要裁决需有提案、提案又要 reflect。故此处跳过 write_gate。
        # 注意：层白名单与密级检查照常；accept 落盘时仍走 add() 的同一道闸，复核不被削弱。
        self.principal.require_layer_write(kw.get("layer", "knowledge"), sens,
                                         skip_gate=True)
        # issue #346（2026-10-17 U05a）：入队面此前只比**声明值**（上面那行是拿
        # `sens`——显式声明时原样返回——去比写入者自己的 clearance），不比对既有
        # 节点的真层真密级 ⇒ 低权身份能把「自己落不了盘的覆写」塞进审核队列，再由
        # 自己/属主 accept 落盘（缺陷形态：orchestr 入队 + orchestr 自批）。
        # 与直写面 `write_qualify`、merge 支 N131、`MdCG.add` 的新闸同口径：
        # 判据单点 `protect.require_layer`（取既有节点真层真密级），提案者落不了
        # 盘的覆写**不入队**。覆盖 cg(op=write) 审核闸 / 一致性闸 / mdcg_propose /
        # gated DEFER 几个入队点（它们都经本函数）。
        if isinstance(node_id, str) and node_id:
            self._maybe_reload_index()
            _ex = (self.index.get("nodes") or {}).get(node_id)
            if _ex is not None:
                protect.require_layer(self, node_id,
                                      layer=_ex.get("layer") or None,
                                      sensitivity=_ex.get("sensitivity") or None)
        return super().propose(node_id, content, sensitivity=sens, **kw)

# 生效条件：sens 经 _write_sensitivity（id 走基类单点 _goal_nid）解析——#439：未声明且有既有目标 ⇒ 继承其密级、显式声明原样优先、判不了 fail-closed；先 _rank(sens) 并 principal.require_layer_write("goals", sens)，再转 super().add_goal，最后按 gid 调 _index_sensitivity 并返回 gid。
    def add_goal(self, goal: str, sensitivity: str = None, **kw) -> str:
        # issue #439：目标同 id 覆盖（基类 add_goal 恒走 add、无幂等短路）⇒ 密级
        # 也必须继承——id 口径走基类单点 _goal_nid，密级走 _write_sensitivity。
        # #426-H 的另一半（分派层转发 sensitivity）随本批同修。
        gid = self._goal_nid(goal)
        sens = self._write_sensitivity(gid, sensitivity)
        _rank(sens)
        self.principal.require_layer_write("goals", sens)
        gid = super().add_goal(goal, sensitivity=sens, **kw)
        self._index_sensitivity(gid, sens)
        return gid

# 生效条件：先 principal.require_layer_write("goals", DEFAULT_SENSITIVITY)，再转 super().set_goal_status(node_id, status)。
    def set_goal_status(self, node_id: str, status: str):
        self.principal.require_layer_write("goals", DEFAULT_SENSITIVITY)
        return super().set_goal_status(node_id, status)

# 生效条件：verdict（转 str 去空白 lower）属于 {"confirmed","weakened","falsified"} 三态**任一**时**先做索引代际探活重载**（N196：索引缺条目 ≡ 本进程陈旧，不得据以跳过层写闸），随后自索引条目（含 _dirty 未刷条目，口径同 MdCG.get）取该条目 layer 与 sensitivity（缺省回落 DEFAULT_SENSITIVITY）调 protect.require_layer→principal.require_layer_write（N209：三态全覆盖——confirmed/weakened 同样重写被验证节点本体 frontmatter，verify 角色 layers_allow 本就只含 rejected/contextual，tokens.py verify spec forbidden 显式列明「不得改被验证内容」），与 add/add_rejected 同一闸口；随后把 override 原样转 super().verify（受保护节点的 guard_forget 快照留痕在基类 falsified 分支内）。verdict 非法（如空串）时不加闸直接把原值转 super().verify（ValueError 语义由基类维持）；目标节点在重载后索引中仍无条目时同样不加闸（not_found 语义由基类维持，且基类 get 取不到即不写盘）。
    def verify(self, node_id: str, evidence: str, verdict: str,
               override: bool = False, superseded_by: str = None):
        v = str(verdict or "").strip().lower()
        # superseded 同属「对被验证内容的写」（改 fm + 推进 lifecycle），与三态
        # 共用同一道层写闸；漏进来就会重演 N209 的「零闸分支」形态。
        if v in ("confirmed", "weakened", "falsified", "superseded"):
            # N196（2026-09-28）：此前直读本进程内存索引且「缺条目 = 放行」——
            # 他进程刚写入并 compact 的节点在本进程索引中不存在时，N130 的
            # 层写闸被整段跳过：verifier（layers_allow=rejected/contextual）
            # 可 falsified 删掉 knowledge 层节点（实测：陈旧索引下删除成功且
            # 盘上原文消失；先重载则 AccessDenied、原文保留）。先探活重载，
            # 「真不存在」与「本进程陈旧」两态才可区分。
            #
            # N209（2026-09-28，同族次生缺口）：闸此前只落在 falsified 一态，
            # confirmed/weakened 分支**零闸**——同一 verifier 令牌可借
            # `mdcg.verify` 的 confirmed/weakened 分支直写被验证节点本体
            # （confidence/evidence_count/positive|negative_evidence/evidence_log）、
            # 连续 weakened 再把 knowledge 节点降级迁出到 contextual，且经
            # mark_dependents 把任意层依赖者置 doubted。三态同为「对被验证
            # 内容的写」，同一闸口一起接上。
            self._maybe_reload_index()
            e = ((self.index.get("nodes") or {}).get(node_id)
                 or (getattr(self, "_dirty", None) or {}).get(node_id))
            if e:
                protect.require_layer(
                    self, node_id, layer=e.get("layer"),
                    sensitivity=e.get("sensitivity"))
        return super().verify(node_id, evidence, verdict, override=override,
                              superseded_by=superseded_by)

# 生效条件：sens 取 sensitivity or DEFAULT_SENSITIVITY，经 _rank(sens) 与 principal.require_write(sens) 后把 m 基于 meta 复制并 setdefault tenant 与 _attributed_session(sens)（写归因三态：env/请求声明→原值；未声明的进程自动随机→unattributed，私有档豁免见该函数）、harness 与 unit 为真值时补入，再强制 m["sensitivity"]=sens，text 经 _seal_content("_recent", text, sens) 后连 tags=tags 一起转 super().remember_event（window 为 None 时不传该参，否则带上 window）。
    def remember_event(self, role: str, text: str, tags=None, meta=None,
                       window=None, sensitivity: str = None):
        sens = sensitivity or DEFAULT_SENSITIVITY
        _rank(sens)
        self.principal.require_write(sens)
        if window is not None:
            # issue #166③：收窄滚动窗口 = 变相绕过 clear 的管理闸（window<=0
            # 清空、window=1 只留一条）——与 clear_recent 的 require_admin 同构。
            from .mdcg import DEFAULT_RECENT_WINDOW as _DRW
            try:
                _w = int(window)
            except (TypeError, ValueError):
                _w = None
            if _w is not None and _w < _DRW:
                self.principal.require_admin("shrink_recent_window")
        m = dict(meta or {})
        m.setdefault("tenant", self.principal.tenant)
        # 写归因三态（2026-10-07）：此前恒取 principal.session（自动随机时事件
        # 归因不可辨认；且请求声明对事件面静默失效）；现与节点/入队同一单点
        # 解析——事件面与写面同口径（显式 meta["session"] 仍不可覆盖）。
        m.setdefault("session", self._attributed_session(sens))
        # issue #712（2026-10-30 验证单元复核发现）：**身份归属此前漏落**——
        # 同函数里 tenant/session/harness/unit/sensitivity 都从 principal 落值，
        # 唯独 `actor`（「谁说的」）没落 ⇒ 注入面拿到的 actor 恒为 None，
        # 「哪些是自己做的、哪些是别人做的」这一要素在库层是空的。
        # 用 setdefault：调用方显式传 meta["actor"] 时不被覆盖（与上面同款口径）。
        m.setdefault("actor", self.principal.actor)
        # 2026-10-30 理论《身份与人格》七要素落地：仅补**归因必需**的三维，
        # 不给事件加权限快照（clearance/layers_allow/ops_allow 一律不写——权限是
        # 当前态不是历史事实，固化进事件会造出「假的当时有权」；权限由
        # sensitivity（数据属性）+ 读取时判据承担）。
        #   · token_id      = **编号**（同名不同人可区分）
        #   · identity_role = **职业身份**（干什么；与 role 参数的 user/assistant 不同层，
        #                     故用不同键名，避免与消息角色混淆）
        #   · parent        = **汇报线**（有上级时才落）
        m.setdefault("token_id", getattr(self.principal, "token_id", None))
        m.setdefault("identity_role", getattr(self.principal, "role", None))
        if getattr(self.principal, "parent", None):
            m.setdefault("parent", self.principal.parent)
        if getattr(self.principal, "harness", None):
            m.setdefault("harness", self.principal.harness)
        if getattr(self.principal, "unit", None):
            m.setdefault("unit", self.principal.unit)
        m["sensitivity"] = sens
        text = self._seal_content("_recent", text, sens)
        if window is None:
            return super().remember_event(role, text, tags=tags, meta=m)
        return super().remember_event(role, text, tags=tags, meta=m, window=window)

    # ---------- 读：密级过滤 ----------

# 生效条件：以 limit（默认 100）取 consistency.history 的留痕后按调用方身份过滤——principal.can_admin 原样返回；否则逐条按记录自带的 sensitivity（缺键＝升级前旧记录，密级不可判）判定，为 public/internal 且 principal.allows 命中时原样保留，其余一律 consistency.scrub_record 去原文后返回；条数与顺序不变。
    def consistency_history(self, limit=100):
        """冲突判定留痕：为什么冲突 / 为什么放行（**按密级过滤**）。

        issue #298（2026-10-14 DSH 端）：`_consistency.jsonl` 只要求 write 权限
        即可读（`mcp_server.py` 的 `"mdcg_consistency": "write"`），而各写角色
        （record/reflect/sustain/verify/orchestr）都有 write——此前本方法直接转调
        `consistency.history`，**没有任何可见性过滤**，于是 internal 级令牌能读到
        private/restricted 写入的条件原文，而同一令牌 `get` 那个节点判 not_found。
        对照：`status`、`audit` 两个读面都按可见性过滤。

        两态：
          · can_admin（设计者，需整体判断）——原样返回，与 `_readable` 的
            绑定档豁免同款；
          · 其他身份——记录自带 `sensitivity` 为 public/internal 且 clearance
            覆盖时原样保留；其余（含加密档、以及**升级前写下、没有 sensitivity
            键**的旧记录）一律去原文。旧记录密级不可判 ⇒ fail-closed 去原文
            （与 `_readable` 的「密级未知按 secret」同向：宁可少读，不可越权）。

        诚实边界：本过滤是**读面**收口，不改写历史文件——升级前已明文落盘的
        条件原文仍在 `_consistency.jsonl` 里，需轮转/清理由维护者裁定。
        """
        recs = consistency.history(self, limit=limit)
        if self.principal.can_admin:
            return recs
        out = []
        for r in recs:
            lvl = str((r or {}).get("sensitivity") or "").strip().lower()
            if lvl in ("public", "internal") and self.principal.allows(lvl):
                out.append(r)
            else:
                out.append(consistency.scrub_record(r))
        return out

    # ---------- 读：密级过滤 ----------

# 生效条件：e 的 sensitivity 为假值时先 _read 回填为 fm 的 sensitivity or DEFAULT_SENSITIVITY，再以 self.principal.allows(sens) 的布尔结果为准。
    def _readable(self, e, session=None) -> bool:
        """读可见性单点判定：clearance × sensitivity（密级）∧ 会话绑定（归属）。

        会话绑定（issue #35 设计定稿 2026-09-23，使用者拍板）：
          · public / internal = 跨会话共享档——任何通过 clearance 的会话可见；
          · private / secret  = 会话绑定档——仅归属会话（frontmatter.session）
            可见；can_admin（设计者，需整体判断）豁免。
          · 绑定档无归属（存量节点）：fail-closed，仅设计者可见（宁可少读，
            不可越权——与下方 sensitivity 回填同款纪律）。
          · 查询侧 session 参数（含 "*"）不参与绑定档判定——身份不可自报；
            共享档本就跨会话可见，故该参数在 Secure 层不再改变任何可见性。
        """
        sens = e.get("sensitivity")
        if not sens:
            # 索引可能被「无密级上下文」的实例重建而丢掉该字段：按盘上真相回填。
            # V21-2（批次 34，外部报告）：`_read` 失败（返回 None 头）时**不得**
            # 回落宽松默认——那会把受保护节点判成 internal 对平级可见
            # （fail-open）。密级未知 = 按最高档 secret 处理（fail-closed：
            # 宁可误禁，不可越权）。
            fm, _c = self._read(e)
            if fm is None:
                sens = "secret"
            else:
                sens = fm.get("sensitivity") or DEFAULT_SENSITIVITY
            e["sensitivity"] = sens
        # issue #146③-b：**非法密级值按隔离处理**（fail-closed 不可读，**不抛**）。
        # 修前：`sensitivity` 被手改坏（如 `sensitivity: internl` 或漏 `}` 后
        # 变成字符串片段）时，下面 `self.principal.allows(sens)` 里的 `_rank(sens)`
        # 抛 `AccessDenied` 从 `_readable` **逃出**，炸穿 `_candidates` → 整个
        # 检索入口 500（一个坏文件炸全员检索）。此处收口为「不可见」——与
        # 「密级未知按 secret」同向的 fail-closed，且不再有异常逃逸面。
        if sens not in SENSITIVITY_ORDER:
            return False
        # restricted = 错误处置标记（批次 28 分型，使用者裁定）：不走纯密级
        # rank——密级底线 internal ∧ 错误处置链路角色（designer/orchestr/
        # verify，或 can_admin）。平级（record/worker）与下游（output/guest）
        # 限读，处置链路必读——故意的冲突设计在此消解。
        if sens == "restricted":
            from .security import can_read_restricted
            return (self.principal.allows("internal")
                    and can_read_restricted(self.principal))
        if not self.principal.allows(sens):
            return False
        if _rank(sens) >= _rank("private"):
            if self.principal.can_admin:
                return True
            # 绑定档判定**恒用 principal.session（服务端身份，不可伪造）**——
            # 查询侧 session 参数（含 "*"）不构成豁免：调用方自报的会话不能
            # 越过身份看别人的 private（与 _attribution「env 固定会话时请求
            # 声明一律忽略」同款纪律）。
            nsess = e.get("session")
            return bool(nsess) and nsess == self.principal.session
        return True

# 生效条件：nid 在 index["nodes"] 中有条目且 _readable(e) 为真时返回 True，否则（无条目/不可见）返回 False；作为 chain.adjacency 的读隔离谓词（cg._chain_visible）被消费——关系链面（causal_chain/explain_chain/causal_path/检索 chain 路 provenance 经 expand_from_seeds）由此单点隔离，不可见节点的出边、边条件文本与下游拓扑不再进入链展开；实例身份稳定（_readable 绑定档恒用 principal.session），与 adjacency 缓存无串台。
    def _chain_visible(self, nid) -> bool:
        """关系链可见性谓词（chain.adjacency 读隔离闸，2026-09-25）。"""
        e = (self.index.get("nodes") or {}).get(nid)
        return bool(e) and self._readable(e)

# 生效条件：先以 limit=None 取 super().list_goals(status=status) 的全量，再只保留 index 中 _readable(e) 为真的目标，limit 为真值时返回 keep[:limit]、否则返回全部 keep。
    def list_goals(self, status=None, limit=None):
        """读隔离：只返回当前 clearance 可见的目标（active_goals/goal_text 同源过滤）。"""
        out = super().list_goals(status=status, limit=None)
        keep = []
        for g in out:
            e = self.index["nodes"].get(g["id"])
            if e is not None and self._readable(e):
                keep.append(g)
        return keep[:limit] if limit else keep

# 生效条件：返回 m 的 sensitivity；缺键（升级前旧记录 / 非 Secure 直写）按最保守档 "secret" 兜底。
    # issue #447：与 consistency_history 的「密级不可判 ⇒ fail-closed 去原文」同向——近期事件面
    # 原按 DEFAULT_SENSITIVITY(internal) 放行，缺键旧记录的明文对 internal 读方可读、会话绑定检查
    # 也被连带跳过；本单点把缺键兜到上限档（designer/admin 仍可读，非 admin 按 secret 判）。
    def _recent_effective_sens(self, m):
        return (m or {}).get("sensitivity") or "secret"

# 生效条件：先以 limit=0 取全量，逐条跳过 meta.tenant 与 self.principal.tenant 不一致的、以及 principal.allows(self._recent_effective_sens(meta)) 为假的（缺 sensitivity 键按最保守档 "secret" fail-closed，issue #447），文本加密时解封失败（None）也跳过，最后 limit 为真值返回 keep[:limit]、否则返回全部 keep。
    def recent_events(self, limit=20, roles=None, since=None, newest_first=True):
        """读隔离：只返回本 tenant 且当前 clearance 可见的近期事件。"""
        out = super().recent_events(limit=0, roles=roles, since=since,
                                    newest_first=newest_first)
        keep = []
        for r in out:
            m = r.get("meta") or {}
            if m.get("tenant", self.principal.tenant) != self.principal.tenant:
                continue
            # issue #447：缺 sensitivity 键按最保守档 fail-closed（与 consistency_history 对齐）。
            msens = self._recent_effective_sens(m)
            if not self.principal.allows(msens):
                continue
            # 会话绑定档（private/secret）：近期事件同口径——仅归属会话，
            # 设计者豁免（issue #35 设计定稿，与 _readable 一致）。
            if (_rank(msens) >= _rank("private")
                    and not self.principal.can_admin
                    and m.get("session") != self.principal.session):
                continue
            if crypto.is_encrypted(r.get("text")):
                t = self._open_content("_recent", m, r["text"])
                if t is None:
                    continue
                r = dict(r)
                r["text"] = t
            keep.append(r)
        return keep[:limit] if limit else keep

# 生效条件：先 principal.require_admin("clear_recent")，再转 super().clear_recent()。
    def clear_recent(self):
        self.principal.require_admin("clear_recent")
        return super().clear_recent()

# 生效条件：在 super()._candidates(layer=layer, roles=roles, include_work=include_work, session=None（会话判定上收本层：基类硬等值过滤会误剔共享档的他人节点）, branch=branch, ...) 的结果上，只保留 self._readable(e, session=session) 为真的条目（clearance × sensitivity ∧ 会话绑定，见 _readable；时间算子在父类候选层单点已过滤，此处只叠加读可见性）。
    def _candidates(self, layer=None, roles=None, include_work=False,
                    session=None, branch=None, validity=None,
                    start_time=None, end_time=None, start_operator=None,
                    end_operator=None, time_axis=None, view=None):
        out = super()._candidates(layer=layer, roles=roles, include_work=include_work,
                                  session=None, branch=branch, validity=validity,
                                  start_time=start_time, end_time=end_time,
                                  start_operator=start_operator,
                                  end_operator=end_operator, time_axis=time_axis,
                                  view=view)
        return [e for e in out if self._readable(e, session=session)]

# 生效条件：在 super()._neg_coverage(terms) 的结果上，只保留 self._readable(e) 为真的条目。
    def _neg_coverage(self, terms):
        return [e for e in super()._neg_coverage(terms) if self._readable(e)]

# 生效条件：probe 为真（缺省，行为与改动前逐位一致）时，索引缺该条目才做代际探活重载（N196）且 super().get 照旧探活；probe=False 时两处探活一并跳过（N276：调用方已在本批读之前探过一次，批量循环内的逐节点读不再各自重探）；其余判据与 probe 无关：node_id 在 self.index["nodes"] 中存在且 self._readable(e) 为假时返回 None，否则转 super().get(node_id, probe=probe)；索引缺该条目时**先做代际探活重载再判可见性**（N196：索引缺条目 ≡ 本进程陈旧，不得据以跳过读隔离），重载后仍无条目才回落 super().get 的 not_found 语义；super().get 返回真值节点后用**同一次读取所得的 frontmatter**（sensitivity/session）再判一次可见性，为假即返回 None（N213：命中陈旧条目的路径不得以旧快照当判据、以新盘面当正文）；
    def get(self, node_id: str, probe: bool = True):
        e = self.index["nodes"].get(node_id)
        if e is None:
            # N196（2026-09-28）：索引缺条目**不**等于「节点不存在」——本进程
            # 可能只是代际陈旧（他进程刚写入并 compact）。直接跳过 _readable
            # 会让读隔离整段失效：跨会话 private / 超密级节点在首次 get 被
            # 放行（实测：同 actor 异 session 的 private 节点在第一读被解出，
            # 第二次读才归 None，因为那时条目已随重载进入索引）。先探活重载
            # 再判可见性；真不存在时 e 仍为 None，super().get 照旧返回 None。
            # 成本只在**未命中**路径（一次 stat），命中路径零变化。
            # N276：probe=False（批内单探针）时本探活同跳——语义窗口见
            # forgetting.redundancy 同注（本批读期间他进程写入不探知）。
            if probe:
                self._maybe_reload_index()
            e = self.index["nodes"].get(node_id)
        if e is not None and not self._readable(e):
            return None                     # 读隔离：不可见即不存在
        node = super().get(node_id, probe=probe)
        if node is None:
            return None
        # N213（2026-09-28）：命中陈旧条目的路径此前**零探活**——可见性判据取自
        # 本进程索引条目（sensitivity/session 是上一代快照），正文却解密自**当前
        # 盘上文件**：判据说 internal 且属本会话、盘面已是他进程写的 private/S2
        # 时，密文照常以明文返回（AEAD 的 AAD 只绑 node_id/tenant/actor，session
        # 是唯一隔离维度）。故返回前用**与正文同源的那次读取**所得的 frontmatter
        # 复核一次：判据与正文同时同源，既杜绝错配也无 TOCTOU 窗口。
        # 成本只在**放行**路径（一次 dict 取键 + 一次判定，无额外 IO）。
        fm = node.get("frontmatter") or {}
        _judge = {"path": node.get("path"),
                  "sensitivity": fm.get("sensitivity"),
                  "session": fm.get("session")}
        try:
            _vis = self._readable(_judge)
        except Exception:                     # noqa: BLE001 —— 判据载体异常按不可见
            _vis = False
        if not _vis:
            return None                     # 陈旧判据放行、盘上真值拒绝：以盘面为准
        return node

# 生效条件：把 *a/**kw 原样转给 super().search_rrf 后，仅保留其结果中每条以 self.index["nodes"].get(结果节点 id) 为索引（索引缺该 id 时用结果节点自身）经 self._readable 判为可见的条目，且 kw["validity"] 为真时该条目经 trust.is_expired 判为未过期者，kw["view"] 为真值时该条目经 roleviews.matches 判为满足视图资格（非法 view ValueError），再返回。
    def search_rrf(self, *a, **kw):
        """RRF 路径里的图扩展会绕过 _candidates，这里显式再过滤一次。

        时效过滤（validity）同属候选资格：图扩展会把过期节点重新带回结果，
        故必须在此与读可见性一并二次过滤，否则过期节点经扩散路径绕过 _candidates。
        角色化读取视图（第四阶段 6.1）同理：view 声明的候选资格对图扩展
        扩散路径同样生效，在此一并兜底。非法 view 由 roleviews.matches 的
        fail-closed 直接抛出（与候选层同口径，不会静默放行）。
        时间算子（阶段二 4.1）同理由此二次过滤——判据复用 `trust.filter_by_time`
        的同一实现口径（`window_matches_node`），**不另写一套轴/算子判断**。
        门控（S1/S1b/S2/S4）：**不是本层的职责**——父类 `MdCGOS.search_rrf` 与
        `search` 共用同一 `apply_retrieval_gates`（C-8），候选面在四路候选生成
        之前即收敛，`meta["gates"]` 原样透传（本层不复制、不改写）。本层只做
        「不可见 / 过期 / 视图不合」的终态剔除，与门控正交（门控=候选面收敛，
        本层=资格兜底），**不得被当作门控的替代**。
        边界：本层计数不并入 `meta["time_filter"]`（该块以父类候选层为准），
        二次过滤只做「不放进结果」的兜底，差额如实不记账。
        """
        res, meta = super().search_rrf(*a, **kw)
        validity = kw.get("validity")
        view = kw.get("view")
        session = kw.get("session")
        now = time.time() if validity else None
        _en_t, _ax_t, _why_t = trust.check_time_args(
            kw.get("start_time"), kw.get("end_time"), kw.get("start_operator"),
            kw.get("end_operator"), kw.get("time_axis"))
        keep = []
        for r in res:
            e = self.index["nodes"].get(r[0]["id"], r[0])
            if not self._readable(e, session=session):
                continue
            # 会话归属兜底已并入 _readable（session 传参）：共享档跨会话可见、
            # 绑定档（private/secret）按归属会话判定（图扩展绕过 _candidates
            # 的串台路径由它一并挡住，与 validity/view 同层兜底）。
            if view is not None and not roleviews.matches(e, view):
                continue
            if validity and trust.is_expired(e, now=now):
                continue
            if _en_t:
                _m, _miss = trust.window_matches_node(
                    e, _ax_t, trust.parse_time(kw.get("start_time")),
                    trust.parse_time(kw.get("end_time")),
                    kw.get("start_operator"), kw.get("end_operator"))
                if _miss:
                    if _ax_t == "observed":
                        continue          # 观察轴 fail-closed（与候选层同策略）
                elif not _m:
                    continue
            keep.append(r)
        return keep, meta

    # ---------- 管理：需 can_admin ----------

# 生效条件：principal 在位时调用 principal.require_admin("forget")（越权抛 AccessDenied），返回 None；
    def _forget_admin(self):
        """删除面的**管理权限闸单点**（三档自治批次②：两个入口共用一份口径）。

        为什么抽出来：`forget`（既有）与 `forget_gated`（档位路径）都必须先过
        这道闸——`MdCGSecure` 的 can_admin 要求原先只写在 `forget` 里，档位路径
        若直调 `_forget_apply` 就把它整个跳过了（实测：`MDCG_CAN_ADMIN=0` 的身份
        经 `mdcg_forget` 能把节点删掉）。判据只此一份，两个入口都走它。
        """
        self.principal.require_admin("forget")

# 生效条件：先 _forget_admin()，再转 super().forget(node_id, reason, override=override)；
    def forget(self, node_id: str, reason: str = "", override: bool = False):
        self._forget_admin()
        return super().forget(node_id, reason, override=override)

# 生效条件：先 _forget_admin()（与 forget 同序同错型——管理闸在资格闸与档位判定**之前**），再转 super().forget_gated(node_id, reason, override=override)；三档自治批次② 的 D 删除工具面路径由此把 can_admin 要求带进档位路径；
    def forget_gated(self, node_id: str, reason: str = "", override: bool = False):
        self._forget_admin()
        return super().forget_gated(node_id, reason, override=override)

# 生效条件：先 principal.require_admin("restore")，再转 super().restore(node_id, force=force, overwrite_live=overwrite_live)（#426-E：覆写在位节点需显式确认，默认 False）。
    def restore(self, node_id: str, force: bool = False,
                overwrite_live: bool = False):
        self.principal.require_admin("restore")
        return super().restore(node_id, force=force, overwrite_live=overwrite_live)

# 生效条件：先 principal.require_op("review")（与 review_decide 同款：审核队列是裁决面，不是普通读面），再转 _review_list_visible()。
    def review_list(self):
        """待审候选 + **读可见性过滤**（N201：提案面与节点正文面同口径）。

        修复前：`MdCGOS.review_list` 全函数体零可见性闸，而细粒度工具
        `mdcg_review_list` 只要求 op=read（`guest` 的 ops_allow 就含 read）⇒
        任一无令牌访客读走 designer 以 `sensitivity='private'` 提交的候选正文
        **明文**与 actor/session 归属；同库规范出口 `cg(op=review, action=list)`
        却要 `require_op("review")` —— 两条出口口径矛盾（N201）。

        本覆写把两件事收归单点：op 闸（库层自证，与 `review_decide` 同款——
        分发层映射再收窄一次，两层都不依赖对方）+ 可见性判定（`_readable`，
        与 `get`/`_candidates`/`search_rrf` 同一实现，不另写一套密级/会话口径）。
        密级未知 = 索引未记录该档 ⇒ 按最高档 fail-closed（与 `_readable` 的
        V21-2 纪律同款：宁可误禁，不可越权）；设计者（can_admin）豁免不变。

        内部计数面（health_os）不走本方法，走 `_review_list_visible`——否则
        只读身份（op=read）的体检面会被本闸打成 AccessDenied（见该方法注释）。
        """
        self.principal.require_op("review")
        return self._review_list_visible()

# 生效条件：逐条取 rec 顶层 sensitivity（N201 起写入侧落键）、缺键回退 rec.extra.sensitivity（存量提案）、仍缺按 "secret" fail-closed；以 _readable 判定（clearance × sensitivity ∧ 会话绑定，can_admin 豁免），判定抛异常按不可见；仅可见条目入结果（正文与 actor/session 归属同时不出）。
    def _review_list_visible(self):
        out = []
        for rec in super().review_list():
            sens = (rec.get("sensitivity")
                    or (rec.get("extra") or {}).get("sensitivity")
                    or "secret")            # 未知密级 fail-closed（最高档）
            try:
                vis = self._readable({"sensitivity": sens,
                                      "session": rec.get("session")})
            except Exception:               # noqa: BLE001 —— 判据不可判即不可见
                vis = False
            if vis:
                out.append(rec)
        return out

# 生效条件：先 principal.require_op("review")（语义修正 2026-09-22：裁决权从
#   require_admin 拆出——编排者/仲裁位持 review op 即可裁决，存在级管理权
#   （forget/protect/anchor 写）仍由 require_admin 把守、designer 专属；
#   designer ops=["*"] 天然兼容），再把 *a/**kw 原样转给 super().review_decide；
#   accept/edit 落节点时的层写仍由下游 require_layer_write 按裁决者可写层拦截。
    def review_decide(self, *a, **kw):
        self.principal.require_op("review")
        return super().review_decide(*a, **kw)

# 生效条件：先 principal.require_admin("evolution_rollback")，再转 super().evolution_rollback(entry_id, dry_run=dry_run, note=note)。
    def evolution_rollback(self, entry_id, dry_run=False, note=""):
        """回滚是管理操作：撤回结构变更 → 需 can_admin。"""
        self.principal.require_admin("evolution_rollback")
        return super().evolution_rollback(entry_id, dry_run=dry_run, note=note)

    # ---------- 身份/审计 ----------

# 生效条件：无入参，返回 principal.as_dict、root、按 SENSITIVITY_ORDER 中 p.allows 为真筛出的 readable_sensitivities、index 中 _readable 为真的 nodes_visible 与 nodes_total、encryption（crypto_status）；tokens.role_spec 可用时另补 role_label/duty/forbidden，导入或取值异常则跳过。
    def whoami(self):
        p = self.principal
        out = {"principal": p.as_dict(), "root": self.root,
               "readable_sensitivities": [s for s in SENSITIVITY_ORDER
                                          if p.allows(s)],
               "nodes_visible": sum(1 for e in list(self.index["nodes"].values())
                                    if self._readable(e)),
               "nodes_total": len(self.index["nodes"]),
               "encryption": self.crypto_status()}
        try:                                  # 角色职责自描述（未知角色不阻塞）
            from . import tokens as _tk
            spec = _tk.role_spec(p.role)
            out["role_label"] = spec["label"]
            out["duty"] = spec["duty"]
            out["forbidden"] = spec["forbidden"]
        except Exception:                     # noqa: BLE001
            pass
        return out

# 生效条件：对 meta 先 setdefault tenant/session/clearance（session 经写归因三态单点 self._attributed_session(sens) 取用，与写面同口径；env/请求声明→原值，未声明的进程自动随机→unattributed，sens 达 private 档豁免保持随机），并在 principal.harness、principal.unit 为真值时补入同名键，再转 super()._audit(op, node_id, **meta)；sens 是命名参数、不进 meta（审计记录形状不变）。
    def _audit(self, op, node_id, sens=None, **meta):
        meta.setdefault("tenant", self.principal.tenant)
        # 写归因三态（2026-10-07 设计者裁定）：审计面与写面**同一 sens** 过单点
        # ——此前恒取原始 principal.session，未声明档下审计记随机值而同次写入的
        # 节点是 'unattributed'（审计与写面字面分叉）；sens 达 private 档的绑定
        # 写入两处同为进程随机（豁免在该函数内，非此处硬编码），故不可简化为恒
        # unattributed（那会在绑定档引入**新**分叉）。
        meta.setdefault("session", self._attributed_session(sens))
        meta.setdefault("clearance", self.principal.clearance)
        # 嵌套身份归因：harness（承载端）/ unit（单元分工）只入审计，不参与授权。
        if getattr(self.principal, "harness", None):
            meta.setdefault("harness", self.principal.harness)
        if getattr(self.principal, "unit", None):
            meta.setdefault("unit", self.principal.unit)
        super()._audit(op, node_id, **meta)

# 生效条件：在 super().health_os() 结果上写入 os.sustain（sustain.summary(self)）与 security（principal 的 tenant/clearance、_sensitivity_counts、crypto_status）后返回。
    def health_os(self):
        h = super().health_os()
        # 持续性自维持（常驻 / 心跳 / 会话续接）：只读摘要，不做巡检
        h["os"]["sustain"] = sustain.summary(self)
        h["security"] = {
            "tenant": self.principal.tenant,
            "clearance": self.principal.clearance,
            "sensitivity_counts": self._sensitivity_counts(),
            "encryption": self.crypto_status(),
        }
        return h

# 生效条件：对 self.index["nodes"] 遍历生效——按每条 e 的 sensitivity（假值回落 DEFAULT_SENSITIVITY）累计计数并返回该字典。
    def _sensitivity_counts(self):
        c = {}
        for e in list(self.index["nodes"].values()):
            s = e.get("sensitivity") or DEFAULT_SENSITIVITY
            c[s] = c.get(s, 0) + 1
        return c

# ---- issue #472：审计追加段哈希链（本件载体；校验面单独抽出以便腿可独立调用）---------
# 复用 md_cg/signer.py（签名面/完整性），**不复用** crypto.py（AEAD/加密面）——
# 「先找轮子」的精化：不是「有就用」，而是「对象要对」。0 新增密钥面。
AUDIT_CHAIN_GENESIS = 'hmac1.genesis'
AUDIT_CHAIN_MARK = 'chain'                      #: 该字段=已知退化（链外，系统可预期）
AUDIT_CHAIN_BROKEN = 'AUDIT_CHAIN_BROKEN'       # 1 链内被改行（敌对，硬失败）
AUDIT_KNOWN_DEGRADED = 'AUDIT_KNOWN_DEGRADED'   # 2 已知退化链外行（可预期，软信号）
AUDIT_UNKNOWN_FOREIGN = 'AUDIT_UNKNOWN_FOREIGN' # 3 未知链外插入（可疑/敌对，硬失败）


# 生效条件：rec 为 dict 即成立；返回剔除 sig 后按 sort_keys 的 json 文本（签名与验签共用同一规范化，避免表示歧义）。
def _audit_sign_body(rec):
    body = {k: v for k, v in rec.items() if k != 'sig'}
    return json.dumps(body, ensure_ascii=False, sort_keys=True)


# 生效条件：path 不存在/无有效末行/解析失败时返回 AUDIT_CHAIN_GENESIS；否则返回末行记录的 sig（缺则 GENESIS）。
def _audit_last_sig(path):
    last = ''
    try:
        with io.open(path, encoding='utf-8') as f:
            for ln in f:
                if ln.strip():
                    last = ln
    except OSError:
        return AUDIT_CHAIN_GENESIS
    try:
        return json.loads(last).get('sig') or AUDIT_CHAIN_GENESIS
    except Exception:
        return AUDIT_CHAIN_GENESIS


# 生效条件：log_path 与 rec 传入即成立；正常时补 prev（上一行 sig）与 sig 并返回 rec；
# **签名器不可用时标记 AUDIT_CHAIN_MARK=已知退化并写 stderr（不静默）**，同样返回 rec。
def _audit_chain_link(log_path, rec):
    try:
        from . import signer as _sg
        s = _sg.get_signer()
    except Exception as e:
        rec[AUDIT_CHAIN_MARK] = AUDIT_KNOWN_DEGRADED
        sys.stderr.write('[audit] 签名不可用，本次审计行标记为链外(已知退化)：%s: %s'
                         % (type(e).__name__, e) + chr(10))
        return rec
    rec['prev'] = _audit_last_sig(log_path)
    rec['sig'] = s.sign(_sg.canonical(_audit_sign_body(rec)))
    return rec


# 生效条件：path 可读即成立；返回 (verdict, reason, detail)，verdict ∈ {ok, tampered, known_degraded, unknown_foreign}。
# ★可判性边界（如实，不许改弱）：本函数**不能判**「哈希链的信任根是否被持有者换过」——若被审计方
#   同时握有链密钥与写权限，它可以**重算整条链**使校验通过；那已越出「可判」，进入「权限模型」。
# ★三档信号**互不相同**（不同原因不得产出同一信号）：链内被改行=硬失败；已知退化链外行=**软信号**
#   （降级，运维要知道）；未知链外插入=硬失败（安全要报）。
def _audit_chain_verify(path, signer=None):
    try:
        from . import signer as _sg
        s = signer or _sg.get_signer()
    except Exception:
        s = None
    prev = AUDIT_CHAIN_GENESIS
    detail = {'lines': 0}
    try:
        fh = io.open(path, encoding='utf-8')
    except OSError:
        return 'ok', None, {'lines': 0, 'note': '文件不存在'}
    with fh:
        for i, ln in enumerate(fh, 1):
            if not ln.strip():
                continue
            detail['lines'] = i
            try:
                rec = json.loads(ln)
            except Exception:
                return 'tampered', AUDIT_CHAIN_BROKEN, {'line': i, 'why': '非 JSON'}
            if rec.get(AUDIT_CHAIN_MARK) == AUDIT_KNOWN_DEGRADED and not rec.get('sig'):
                detail.setdefault('degraded', []).append(i)
                continue
            if not rec.get('sig'):
                return 'unknown_foreign', AUDIT_UNKNOWN_FOREIGN, {'line': i, 'why': '无 sig 且无退化标记'}
            if s is None:
                return 'tampered', AUDIT_CHAIN_BROKEN, {'line': i, 'why': '无签名器'}
            if rec.get('prev') != prev:
                return 'tampered', AUDIT_CHAIN_BROKEN, {'line': i, 'why': 'prev 断链'}
            if not s.verify(_sg.canonical(_audit_sign_body(rec)), rec['sig']):
                return 'tampered', AUDIT_CHAIN_BROKEN, {'line': i, 'why': 'sig 不符'}
            prev = rec['sig']
    if detail.get('degraded'):
        return 'known_degraded', AUDIT_KNOWN_DEGRADED, detail
    return 'ok', None, detail
