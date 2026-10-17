# -*- coding: utf-8 -*-
"""A2 共享件守卫：审计轮转「改前/改后逐位不变」+ 两侧同源（md_cg.rotate.Rotator）。

背景（2026-10-10 设计者裁定 A2）：把 `mdcos` 的审计分片轮转抽成**参数化共享件**
`md_cg/rotate.Rotator`，让 `mdcos` 的 `_audit.jsonl` 轮转与 `crypto.audit` 的
`_crypto.jsonl` 轮转**同时改调它**。硬要求是**审计侧行为逐位不变**。

本守卫的证据形态（可复现、非自证）：
  ① 固定序列 + **冻结时钟** ⇒ `_audit.jsonl` / 归档分片 / 归档索引 字节确定；
     与**改动前**（同一序列真跑）捕获的 sha256 常量逐位比对——任何漂移即红。
  ② 两侧同源：`MdCGOS._audit_rot` 与 `crypto._rotator(root)` 是**同一个类对象**
     （`md_cg.rotate.Rotator`）。
  ③ 源面：轮转实现体已从 `mdcos.py` 抽出（旧 `publish(self.audit_log, dst)` 不再
     出现在 mdcos），`crypto.audit` 已接共享件（`maybe_rotate()` 在位）。
  ③d **独立实现扫描（2026-10-10 DSH 端独立复核补）**：全仓 .py 里构造分片名
     （basename 加 6 位零填充序号 + `.jsonl`）的文件集合必须**恰好**等于已声明集
     `{md_cg/rotate.py, md_cg/sustain.py}`——`rotate.py` 自述此前写「轮转机制唯一
     实现点」，与 `sustain.py::rotate_heartbeat` 自带第三份独立轮转的事实不符；
     现订正措辞，并让本断言在「他处存在/新增独立实现」时**点名到具体文件**。

运行：python -m md_cg.test_audit_rotate_parity
"""
# ============================ issue #472 · 判据形态变更登记（**必读**）============================
# 【登记 1 · 契约/基准形态变更】**本守卫的判据形态已于 2026-10-15 因 #472 变更**：
#   原因：#472 给每条审计记录加了 `prev`/`sig`（审计追加段哈希链），使**每行字节变长**
#         => `AUDIT_ROTATE_BYTES=2048` 是**按字节**触发轮转 => **轮转切分点提前** =>
#         实测分片编号由 golden 表的 **000002/000003/000004** 变为 **000005/000006/000007**。
#   => 因此「**除 `prev`/`sig` 外其余字节逐位不变**」这条收窄**实测不可达**：剥离链字段能还原**行内**
#      字节，**还原不了「哪一段落在哪个分片」**——那是**结构**，由**未剥离时的字节长度**决定。
#   => **变更方向（Lead 裁定走 A′）**：把「与某时点的整字节快照逐位相同」降级为「**结构不变量**」，即
#      判据落在**轮转语义本身**（分片数 = ceil(总字节/阈值) · 索引与分片一致 · `keep_shards` 生效），
#      而**不再与任何 golden 比字节**。理由：**契约不随行长度变化，故不陈化**；而时点快照**必然陈化**，
#      本件就是它的第一个反例。
#   ★ **本变更源于一次实测推翻，不是设计偏好**（Lead 原话：这是第三条被实测推翻的判据形态，前两条是
#      `O_APPEND` 单次写原子性 与 `VERB_SPECS` 当写面轴；三次都是被「**先报覆盖域/先报机制**」这条要求拦下的）。
#
# 【登记 2 · 新形态「**差集 ≠ 新增**」】**「不在清单里」不等于「不存在」；做差集前必须先判「清单是否穷举」。**
#   本次实例：我把 `os.walk` 全量枚举（**7 个文件**）与 golden 表（**5 格**）做差集，得到 2 个「新增」，
#   其中**只有 1 个是本件真产物**（`_audit_archive/_prune_ledger.jsonl`，站点 3 的对账单），
#   另 1 个（`_audit.rotate.lock.lock`）**是既有物**—— golden 表本就是**选择性清单**，不是「root 下全部文件」。
#   ★ 与本会话已有两条相邻形态：「**字面/名字 ≠ 语义**」·「**上游读数照抄**」。
#
# 【登记 3 · 已发现的既有缺陷（**不在本件范围**）】**`_audit.rotate.lock.lock` = 后缀拼接职责重叠**：
#   · `md_cg/rotate.py:98` 生效条件：`lock_name` 缺省 **`basename + ".rotate.lock"`**；
#   · `md_cg/rotate.py` 的 `self.lock_path`（**修前** `(basename + ".rotate.lock")` => 已含 `.lock`；
#     **#521 已修**：现为 `(basename + ".rotate")`，由 `FileLock` 补 `.lock` ⇒ 单后缀）；← 此行号锚已改为语义锚（#521 改动使其平移）
#   · `md_cg/fsutil.py:124`  `self.path = path + ".lock"`  => **FileLock 又加一次** => `.rotate.lock.lock`。
#   · 取证：`rotate.py:269` 的 `FileLock(self.lock_path)` 在**既有** `rotate()/maybe_rotate()` 里；
#     golden 那次运行**确实发生过轮转**（表里有 000002/3/4）=> **那次必然走过 `:269`** =>
#     **该锁文件是既有现象，不是 #472 引入的**。
#   · 处置：**本件不修**（改 `lock_name` 是改既有行为、有既有消费者，属扩面；且本件是 SEC·P1 审计链，
#     并进来会把两件事混在一批）=> **单开独立 issue**；本件只**显式登记**，不删、不绕过（删/绕过会掩盖问题）。
#   · **为何本守卫不列它**：它是**运行期残留**（判据面不稳定）；本守卫沿用**选择性清单**口径，
#     并在本登记里显式说明「为何不列」—— 否则下一个人会再问「这两个文件哪去了」，而那正是登记 2 的成因。
# =================================================================================================
from __future__ import annotations
import json

import hashlib
import os
import shutil
import tempfile

from . import crypto
from . import mdcos as mdcos_mod
from . import rotate as rotate_mod
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []

#: 改动前（抽出共享件之前，同一序列真跑）捕获的字节指纹。**判据常量**——
#: 改后任一处字节漂移 ⇒ 逐位比对失败（这就是「审计侧逐位不变」的可执行断言）。
#:
#: **平台维度（2026-10-10 DSH 端复核，根因判定）**：golden 必须按平台区分——
#: 同一序列在 Windows 与 Linux 上**改动前**就产出不同字节。根因：`fsutil.append_jsonl`
#: 以 `os.open`/`os.write` 写日志，Windows 的 fd 默认文本模式把 `\n` 翻成 `\r\n`
#: （Linux 为二进制、保持 `\n`），每条记录多 1 字节；分片/索引里记录的 `bytes`
#: 尺寸随之差 9（= 每片行数）。**这不是共享件引入的行为改变**：改动前的代码在真
#: Linux 容器里跑同一序列，产出与改动后**逐位相同**（即 CI 报出的 got 值就是
#: 改动前的 Linux 值）⇒ 判定为「golden 未声明平台」，非 `rotate.py` 真改行为。
#: 故两张表各自锁「本平台改动前后逐位不变」，判别力不削。
_GOLDEN_FROZEN_TS = 1700000000.0
_GOLDEN_WIN = {
    "_audit.jsonl":
        "ada0801b4e5764723b896df75500474879a7118010514ebac19912fdfbe4367c",
    "_audit_archive/_audit.000002.jsonl":
        "777d0008d21e8f6d044a26a1aef92c8e2b58f76084c0047c6585891dafc2066c",
    "_audit_archive/_audit.000003.jsonl":
        "4bdb34c7b9d227a8959b21c81b2b45afcb0460ece2431043ba1e2b207620319f",
    "_audit_archive/_audit.000004.jsonl":
        "7044512d3b3a95b4db039bbc18f94196e59ed9acb7f9ac7e22633ca5aede28a6",
    "_audit_archive/_index.json":
        "186ff64d9f51a0183528e2f2d57da74997d6a15ee560bfbc08d6660d1ad42fc6",
}
_GOLDEN_LIN = {
    "_audit.jsonl":
        "91dcc9231e2b0992df91fcece56546eaf7dbe5353e4fb43f7d4914b7b925f676",
    "_audit_archive/_audit.000002.jsonl":
        "268e7e36f93c7db3b52c279aae0407496efbcb021f37c8d0e5ab3053a69a2501",
    "_audit_archive/_audit.000003.jsonl":
        "82e6a57db8ccb9ed82ddaef5cb2c475b224aba1998f2dbb119a6e2a54790fd7b",
    "_audit_archive/_audit.000004.jsonl":
        "d2d72a856e4421a3c336607466c124cfc5bd0929eee45727efd98fcfd882b8f8",
    "_audit_archive/_index.json":
        "643deb64679cfbeeada4e55902e7bb8c731ad4877654e8a3d2c2848429ea82da",
}
#: 按运行平台选表（Windows fd 文本模式 ⇒ CRLF；Linux 二进制 ⇒ LF）。
_GOLDEN = _GOLDEN_WIN if os.name == "nt" else _GOLDEN_LIN
_PLATFORM = "win" if os.name == "nt" else "lin"


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


class _Frozen(object):
    """冻结时源：轮转自述与索引时间戳据此确定（否则哈希不可复现）。"""

    @staticmethod
    def time():
        return _GOLDEN_FROZEN_TS


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_src(name):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), name),
              "r", encoding="utf-8") as f:
        return f.read()


#: 分片名构造式（防本守卫自命中：写成拼接式，文件内不出现完整字面量）。
_SHARD_MARK = "%0" + "6d.jsonl"
#: 已声明的独立轮转实现（`rotate.Rotator` 之外）：心跳台账自带一份。
# issue #472：md_cg/test_issue472_prune_ledger.py 是站点 3 的测试夹具（真造分片），非独立轮转实现；
#   它必然引用分片名构造式，故按 3d 的设计意图显式声明（3d 抓的正是新出现的构造式必须被声明）。
_DECLARED_ROTATORS = {"md_cg/rotate.py", "md_cg/sustain.py"}
_DECLARED_ROTATORS = _DECLARED_ROTATORS | {"md_cg/test_issue472_prune_ledger.py"}


def _scan_shard_builders():
    """全仓 .py 里构造零填充分片名（basename + 6 位序号 + `.jsonl`）的文件。

    归一化为仓内相对路径；跳过 `.git` 等点目录与构建产物目录，并排除本守卫
    自身（它必须引用该构造式做扫描）。
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    me = os.path.relpath(os.path.abspath(__file__), root).replace("\\", "/")
    hits = set()
    skip = {"node_modules", "target", "__pycache__", "venv", "build", "dist"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in skip and not d.startswith(".")]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root).replace("\\", "/")
            if rel == me:
                continue
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    txt = f.read()
            except OSError:
                continue
            if _SHARD_MARK in txt:
                hits.add(rel)
    return hits


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_a2_parity_")
    orig_time = mdcos_mod.time
    try:
        # ---------- ① 逐位不变：固定序列 + 冻结时钟 ----------
        mdcos_mod.time = _Frozen
        root = os.path.join(tmp, "root")
        os.makedirs(root)
        cg = MdCGOS(root)
        cg.AUDIT_ROTATE_BYTES = 2048
        cg.AUDIT_KEEP_SHARDS = 3
        cg.AUDIT_PROBE_EVERY = 1
        for i in range(40):
            cg._audit("add", "node_%d" % i, pad="z" * 160)
        cg.close()
        mdcos_mod.time = orig_time

        # #472 A-prime：旧整字节 golden 比对已按裁定停用（见文件头登记 1）；判据改由下方结构不变量承载。
        for rel, want in []:
            got = _sha(os.path.join(root, rel))
            ok(got == want,
               "①逐位不变[%s] %s（%s == %s）" % (_PLATFORM, rel, got[:16],
                                                want[:16]))

        # ---------- ①'（issue #472 A'）结构不变量：判据落在轮转语义，不再比 golden 字节 ----------
        _arch = os.path.join(root, '_audit_archive')
        _sh = sorted(n for n in os.listdir(_arch) if n.startswith('_audit.') and n.endswith('.jsonl'))
        _cnt = {}
        for _n in _sh:
            _cnt[_n] = sum(1 for _l in open(os.path.join(_arch, _n), encoding='utf-8') if _l.strip())
        print('       [读数·结构] 分片=%s 每片条数=%s' % (_sh, _cnt))
        ok(all(int(_sh[i][7:13]) + 1 == int(_sh[i + 1][7:13]) for i in range(len(_sh) - 1)), 'S1 分片名升序且序号连续')
        ok(all(v > 0 for v in _cnt.values()), 'S2 每片条数均 > 0（无空分片）')
        _idx = json.load(open(os.path.join(_arch, '_index.json'), encoding='utf-8'))
        ok(set(_idx.keys()) == set(_sh), 'S3 索引与分片集合一致（键集 == 分片名集合）')
        ok(len(_sh) == 3, 'S4 AUDIT_KEEP_SHARDS 生效（保留数 == 3）')
        _root2 = os.path.join(tmp, 'root_mut')
        os.makedirs(_root2)
        mdcos_mod.time = _Frozen
        cg_m = MdCGOS(_root2)
        cg_m.AUDIT_ROTATE_BYTES = 4096
        cg_m.AUDIT_KEEP_SHARDS = 3
        cg_m.AUDIT_PROBE_EVERY = 1
        for i in range(40):
            cg_m._audit('add', 'node_%d' % i, pad='z' * 160)
        cg_m.close()
        mdcos_mod.time = orig_time
        _arch2 = os.path.join(_root2, '_audit_archive')
        _sh2 = sorted(n for n in os.listdir(_arch2) if n.startswith('_audit.') and n.endswith('.jsonl'))
        print('       [读数·对照] 改阈值 4096 后分片=%s' % _sh2)
        ok(_sh2 != _sh, 'S5 件 5 对照断言：故意改一处轮转结构 => 分片集合必变（结构判据会红）')
        # ---------- ② 两侧同源：同一个 Rotator 类对象 ----------
        cg2 = MdCGOS(os.path.join(tmp, "root2"))
        crypto.CRYPTO_ROTATE_BYTES = 1 << 30
        try:
            r_crypto = crypto._rotator(cg2.root)
            ok(type(cg2._audit_rot) is rotate_mod.Rotator
               and type(r_crypto) is rotate_mod.Rotator
               and type(cg2._audit_rot) is type(r_crypto),
               "②两侧同源：mdcos._audit_rot 与 crypto._rotator 均为同一个 "
               "md_cg.rotate.Rotator 类")
        finally:
            crypto.CRYPTO_ROTATE_BYTES = 64 << 20
            cg2.close()

        # ---------- ③ 源面：实现体已抽出、crypto 已接线 ----------
        s_mdcos = _read_src("mdcos.py")
        s_crypto = _read_src("crypto.py")
        s_rotate = _read_src("rotate.py")
        ok("publish(self.audit_log, dst)" not in s_mdcos
           and "self._audit_rot" in s_mdcos,
           "③a mdcos 轮转实现体已抽出（旧 publish 体不在 mdcos，改走 _audit_rot）")
        ok("class Rotator" in s_rotate and "def maybe_rotate" in s_rotate,
           "③b md_cg/rotate.py 是审计/密文两路共用实现（class Rotator）；"
           "心跳另有独立轮转见 ③d")
        ok("_rotator(root).maybe_rotate()" in s_crypto,
           "③c crypto.audit 已接共享件（写前轮转闸门在位）")
        # ③d 独立实现扫描：分片名构造者集合必须恰好等于已声明集。
        hits = _scan_shard_builders()
        extra = sorted(hits - _DECLARED_ROTATORS)
        ok(hits == _DECLARED_ROTATORS,
           "③d 独立轮转实现扫描：构造零填充分片名的文件集 = %s（应为 %s；"
           "未声明/新增的独立实现 = %s）"
           % (sorted(hits), sorted(_DECLARED_ROTATORS), extra or "无"))
    finally:
        mdcos_mod.time = orig_time
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\naudit_rotate_parity: {PASS} pass / {FAIL} fail")
    if FAILS:
        for f in FAILS:
            print(f" - {f}")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()