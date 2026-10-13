# -*- coding: utf-8 -*-
"""test_branches_sensitivity · 分支派生写的密级继承（issue #243）

# 功能名：分支派生写（fork/rewrite/merge）的密级继承 + merge 降密级 fail-closed 闸
# 生效条件：改动 md_cg/branches.py 的 fork/rewrite/merge 落盘参数、或改动
#           subgraph.node_sensitivity / security.merge_downgrades 之后必跑
# 子功能：①fork 副本继承主支密级（private 不落明文）②rewrite 改写后仍继承
#         ③merge 回写仍 private 且内容确实合并 ④阴性对照：internal 不被提级
#         ⑤分支档更高时 merge 跳过该节点（fail-closed，主支不动）
#         ⑥extra 里传 sensitivity 被静默剥离（不报错、也不改档）
#         ⑦三处派生写共走单点（调用留痕）+ 降密级判据方向
#         ⑧判不了密级（真·非法档位 + 单点返回 None）⇒ fork/rewrite/merge 一律 fail-closed
#         ⑨4 条定点变异（force_internal / allow_downgrade / allow_unjudged / bypass_single_point）
# 执行：python -m md_cg.test_branches_sensitivity [--mutate=force_internal|allow_downgrade|allow_unjudged|bypass_single_point]
# 验证方式：末行「通过 N / 失败 M」；每条给原始读数（索引快照档位 / frontmatter /
#           全库明文命中文件清单）
# 不适用条件：只测**分支派生写**的密级面；沙箱一律 tempfile，绝不触碰在役库

## 病象（本件）
md_cg/branches.py 的 fork / rewrite / merge 三处 cg.add 都不传 sensitivity，
MdCGSecure.add 把缺省归一为 DEFAULT_SENSITIVITY（internal）；而
crypto.ENCRYPTED_LEVELS 只含 private/secret ⇒ 声明 private 的主支节点一旦
fork / 改写 / 合并，盘上正文就变成 internal **明文**（密级静默降级，
分支实验场成了降密级旁路）。

## 修法与判据
fork/rewrite/merge 共用单点 branches._inherit_sensitivity（= subgraph.
node_sensitivity，与 #164 派生节点密级同源）；merge 回写前先过
security.merge_downgrades（#148 单点，writelimit/forgetting 同源），
判为降密级即 fail-closed 跳过该节点。单点判不了（缺/非法档位）时同样
fail-closed：**不把 None 直传 add**（那会被归一成 internal 明文，等于把
「判不了」当成「internal」），与 #164「判不了不生成」同口径。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import branches, subgraph                       # noqa: E402
from md_cg.mdcos import MdCGSecure                         # noqa: E402
from md_cg.security import Principal                       # noqa: E402

PASS = 0
FAILS = []

#: 私有正文明文哨兵（落盘出现即为泄漏）
CANARY = "CANARY-BRANCH-PRIVATE-7f3a9b"


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print("  ok   %s" % name)
    else:
        FAILS.append(name)
        print("  FAIL %s  · %s" % (name, detail))


def _mk_cg(tmp, tag):
    root = os.path.join(tmp, "root_" + tag)
    p = Principal(tenant="default", actor="t_" + tag, role="designer",
                  clearance="secret", can_write=True, can_admin=True)
    return MdCGSecure(root, principal=p)


def _fm(cg, nid):
    return ((cg.get(nid) or {}).get("frontmatter") or {})


def _sens(cg, nid):
    """落盘档位：索引快照优先（元数据明文），回退 frontmatter。"""
    e = (cg.index.get("nodes") or {}).get(nid) or {}
    return e.get("sensitivity") or _fm(cg, nid).get("sensitivity")


def _plaintext(cg, needle):
    """全库（含索引/审计/冷区）扫 needle 明文，返回命中文件相对路径清单。"""
    out, n = [], needle.encode("utf-8")
    for dp, _dirs, files in os.walk(cg.root):
        for fn in files:
            fp = os.path.join(dp, fn)
            try:
                with open(fp, "rb") as fh:
                    if n in fh.read():
                        out.append(os.path.relpath(fp, cg.root).replace(os.sep, "/"))
            except OSError:
                pass
    return sorted(out)


def case_private(tmp):
    print("\n[1] private 主支：fork / rewrite / merge 三段派生")
    cg = _mk_cg(tmp, "priv")
    cg.add("mem_priv", CANARY + " 私密正文", layer="knowledge",
           sensitivity="private", verification_basis="test", consistency=False)
    check("主支落盘档位 private", _sens(cg, "mem_priv") == "private", _sens(cg, "mem_priv"))
    check("主支正文不以明文落盘", _plaintext(cg, CANARY) == [], _plaintext(cg, CANARY))

    bid = "mem_priv@exp"
    r = branches.fork(cg, ["mem_priv"], branch_id="exp", note="密级继承")
    check("fork 成功", r.get("ok") is True
          and r.get("forked") == [{"from": "mem_priv", "to": bid}], r)
    check("fork 副本索引档位继承 private", _sens(cg, bid) == "private", _sens(cg, bid))
    check("fork 副本 frontmatter 继承 private",
          _fm(cg, bid).get("sensitivity") == "private", _fm(cg, bid))
    check("fork 后全库无 private 明文", _plaintext(cg, CANARY) == [], _plaintext(cg, CANARY))

    r2 = branches.rewrite(cg, bid, CANARY + " 改写后正文")
    check("rewrite 成功", r2.get("ok") is True, r2)
    check("rewrite 后仍 private", _sens(cg, bid) == "private", _sens(cg, bid))
    check("rewrite 后全库无 private 明文", _plaintext(cg, CANARY) == [], _plaintext(cg, CANARY))

    r3 = branches.merge(cg, "exp")
    check("merge 成功回写主支（未误判降密级）",
          r3.get("ok") is True and r3.get("skipped") == [], r3)
    check("merge 后主支仍 private", _sens(cg, "mem_priv") == "private", _sens(cg, "mem_priv"))
    check("merge 后全库无 private 明文", _plaintext(cg, CANARY) == [], _plaintext(cg, CANARY))
    check("merge 内容确实合并（解密后可读）",
          CANARY in ((cg.get("mem_priv") or {}).get("content") or ""), "内容未合并")


def case_internal(tmp):
    print("\n[2] 阴性对照：internal 主支不被提级（明文照旧在盘）")
    cg = _mk_cg(tmp, "pub")
    body = "PUBLIC-CANARY-1a2b 内部正文"
    cg.add("mem_pub", body, layer="knowledge", verification_basis="test",
           consistency=False)
    check("internal 主支档位", _sens(cg, "mem_pub") == "internal", _sens(cg, "mem_pub"))
    bid = "mem_pub@expp"
    r = branches.fork(cg, ["mem_pub"], branch_id="expp")
    check("fork 成功", r.get("ok") is True, r)
    check("internal 副本仍 internal（不过度提级）",
          _sens(cg, bid) == "internal", _sens(cg, bid))
    check("internal 副本正文照旧明文在盘（未被误加密）",
          _plaintext(cg, "PUBLIC-CANARY-1a2b") != [],
          _plaintext(cg, "PUBLIC-CANARY-1a2b"))


def case_downgrade_gate(tmp):
    print("\n[3] 降密级闸：分支档更高 ⇒ merge 跳过该节点（fail-closed）")
    cg = _mk_cg(tmp, "gate")
    cg.add("mem_low", "低档正文 LOW-CANARY-3c4d", layer="knowledge",
           verification_basis="test", consistency=False)
    cg.add("mem_low@bg", "升档正文 " + CANARY, layer="knowledge",
           sensitivity="private", branch_id="bg", branched_from="mem_low",
           verification_basis="test", consistency=False)
    check("分支节点落 private", _sens(cg, "mem_low@bg") == "private", _sens(cg, "mem_low@bg"))
    r = branches.merge(cg, "bg")
    check("merge 拒绝降密级：merged 为空", r.get("merged") == [], r)
    check("跳过理由点名「降密级」与单点 merge_downgrades",
          any("降密级" in str(s.get("why")) and "merge_downgrades" in str(s.get("why"))
              for s in (r.get("skipped") or [])), r.get("skipped"))
    check("主支档位不动（仍 internal）", _sens(cg, "mem_low") == "internal", _sens(cg, "mem_low"))
    check("主支正文未被 private 正文覆盖",
          CANARY not in ((cg.get("mem_low") or {}).get("content") or ""),
          (cg.get("mem_low") or {}).get("content"))
    check("全库无 private 明文（拒绝后也没落盘）",
          _plaintext(cg, CANARY) == [], _plaintext(cg, CANARY))


def case_extra_strip(tmp):
    print("\n[4] rewrite 的 extra 传 sensitivity：静默剥离（不报错、档位不变）")
    cg = _mk_cg(tmp, "extra")
    cg.add("mem_p2", CANARY + " 私密二", layer="knowledge", sensitivity="private",
           verification_basis="test", consistency=False)
    branches.fork(cg, ["mem_p2"], branch_id="ex2")
    try:
        r, err = branches.rewrite(cg, "mem_p2@ex2", "改后正文 " + CANARY,
                                  sensitivity="internal"), None
    except Exception as e:                                  # noqa: BLE001
        r, err = None, "%s: %s" % (type(e).__name__, e)
    check("调用方传 sensitivity 不报错（extra 剥离，非 TypeError）", err is None, err)
    check("rewrite 成功", bool(r) and r.get("ok") is True, r)
    check("档位不被调用方改成 internal（仍 private）",
          _sens(cg, "mem_p2@ex2") == "private", _sens(cg, "mem_p2@ex2"))
    check("全库无 private 明文", _plaintext(cg, CANARY) == [], _plaintext(cg, CANARY))


def case_single_point(tmp):
    print("\n[5] 判据单点自证：三处派生写都走 _inherit_sensitivity（调用留痕）")
    cg = _mk_cg(tmp, "sp")
    cg.add("mem_sp", CANARY + " 单点", layer="knowledge", sensitivity="private",
           verification_basis="test", consistency=False)
    _helper = getattr(branches, "_inherit_sensitivity", None)
    check("branches 暴露单点 _inherit_sensitivity（改前缺失即红）",
          callable(_helper), repr(_helper))
    if not callable(_helper):
        return
    calls = []

    def _rec(cgx, nidx):
        calls.append(nidx)
        return _helper(cgx, nidx)

    branches._inherit_sensitivity = _rec
    try:
        branches.fork(cg, ["mem_sp"], branch_id="sp")
        branches.rewrite(cg, "mem_sp@sp", "单点改写 " + CANARY)
        branches.merge(cg, "sp")
    finally:
        branches._inherit_sensitivity = _helper
    # 判据面：三处派生写各取一次来源（merge 取主支 + 分支各一次）——任一
    # 处改回「不查单点」（例如直传 None 或写死 internal）即在此红。
    check("三处派生写共调单点 4 次（fork1 + rewrite1 + merge2）",
          calls == ["mem_sp", "mem_sp@sp", "mem_sp", "mem_sp@sp"], calls)
    check("单点返回值被真正采用（派生写仍 private，非 internal）",
          _sens(cg, "mem_sp@sp") == "private" and _sens(cg, "mem_sp") == "private",
          (_sens(cg, "mem_sp@sp"), _sens(cg, "mem_sp")))
    # 注：此处**不**做源码文本形态断言（曾有一条「'= _inherit_sensitivity(cg,'
    # 出现 4 次」）。理由：它对合法等价重构（例如就地改调 subgraph.node_sensitivity）
    # 会假红，而「三处调用点都走单点」这一属性已由上面的调用留痕断言以行为口径
    # 覆盖（变异 bypass_single_point 实测把留痕打成 calls=[]）。
    check("全库无 private 明文（单点路径未降级）",
          _plaintext(cg, CANARY) == [], _plaintext(cg, CANARY))
    _gate = getattr(branches, "_merge_downgrades", None)
    check("branches 暴露单点 _merge_downgrades（改前缺失即红）",
          callable(_gate), repr(_gate))
    if callable(_gate):
        check("_merge_downgrades 方向正确（升档为真、降档为假）",
              _gate("internal", "private") is True
              and _gate("private", "internal") is False,
              (_gate("internal", "private"), _gate("private", "internal")))


def case_unjudgeable(tmp):
    print("\n[6] 判不了密级（单点返回 None）⇒ 三处派生写一律 fail-closed")
    cg = _mk_cg(tmp, "unk")
    cg.add("mem_u", CANARY + " 判不了", layer="knowledge", sensitivity="private",
           verification_basis="test", consistency=False)
    _helper = getattr(branches, "_inherit_sensitivity", None)
    check("branches 暴露单点 _inherit_sensitivity", callable(_helper), repr(_helper))
    if not callable(_helper):
        return
    branches._inherit_sensitivity = lambda cgx, nidx: None
    try:
        r1 = branches.fork(cg, ["mem_u"], branch_id="unk")
        check("fork：判不了即跳过，不落副本",
              r1.get("ok") is False and r1.get("forked") == []
              and any("判不了" in str(s.get("why")) for s in (r1.get("skipped") or [])),
              r1)
        check("fork 跳过理由点名 fail-closed 与单点 node_sensitivity",
              any("fail-closed" in str(s.get("why"))
                  and "node_sensitivity" in str(s.get("why"))
                  for s in (r1.get("skipped") or [])), r1.get("skipped"))
        # 用真单点建一个真分支副本，再撤掉单点，验 rewrite / merge 的拒写
        branches._inherit_sensitivity = _helper
        branches.fork(cg, ["mem_u"], branch_id="unk2")
        branches._inherit_sensitivity = lambda cgx, nidx: None
        r2 = branches.rewrite(cg, "mem_u@unk2", "改写正文 " + CANARY)
        check("rewrite：判不了即拒绝（ok=False，不动盘）",
              r2.get("ok") is False and "判不了" in str(r2.get("error")), r2)
        r3 = branches.merge(cg, "unk2")
        check("merge：判不了即跳过，不写盘",
              r3.get("merged") == []
              and any("判不了" in str(s.get("why")) for s in (r3.get("skipped") or [])),
              r3)
        check("三处都未落 internal 明文",
              _plaintext(cg, CANARY) == [], _plaintext(cg, CANARY))
        check("副本档位仍是 private（未被 None 归一成 internal）",
              _sens(cg, "mem_u@unk2") == "private", _sens(cg, "mem_u@unk2"))
    finally:
        branches._inherit_sensitivity = _helper
    # 真·非法档位腿（**不 monkeypatch 任何单点**）：索引快照档位改成非法值，
    # subgraph._sensitivity_of 的 _rank 抛异常分支即返回 None —— 走真实代码路径。
    cg2 = _mk_cg(tmp, "unk3")
    cg2.add("mem_real", CANARY + " 非法档", layer="knowledge",
            sensitivity="private", verification_basis="test", consistency=False)
    cg2.index["nodes"]["mem_real"]["sensitivity"] = "topsecret"
    check("真·非法档位：node_sensitivity 判 None（非 monkeypatch，索引快照路径）",
          subgraph.node_sensitivity(cg2, "mem_real") is None,
          subgraph.node_sensitivity(cg2, "mem_real"))
    r4 = branches.fork(cg2, ["mem_real"], branch_id="unk3")
    check("真·非法档位 A：fork 跳过且不落副本",
          r4.get("ok") is False and r4.get("forked") == [], r4)
    # 诚实边界（实测）：非法档位让**上游可读性**先 fail-closed（security._rank 对
    # 未知档抛 AccessDenied ⇒ cg.get 返回假值），fork 在更早的「节点不可见」守卫就
    # 跳过，故真·非法档位**走不到** branches 自己的判不了分支——后者是兜底。
    check("真·非法档位 A：上游即可读性 fail-closed（跳过理由=主支节点不存在或不可见）",
          any("不存在或不可见" in str(s.get("why")) for s in (r4.get("skipped") or [])),
          r4.get("skipped"))
    check("真·非法档位 A：全库无 private 明文（未被归一成 internal 落盘）",
          _plaintext(cg2, CANARY) == [], _plaintext(cg2, CANARY))
    # 回退路径腿：索引快照缺 sensitivity（置 None）时回退读文件 frontmatter；
    # 把盘上档位改成非法值，回退路径同样判 None ⇒ 仍 fail-closed。
    cg2.index["nodes"]["mem_real"]["sensitivity"] = None
    _disk = ""
    for _dp, _dirs, _files in os.walk(cg2.root):
        for _fn in _files:
            if _fn.startswith("mem_real") and _fn.endswith(".md"):
                _disk = os.path.join(_dp, _fn)
    if _disk:
        _raw = open(_disk, encoding="utf-8").read()
        _mut = _raw.replace('sensitivity: "private"', 'sensitivity: "topsecret"')
        if _mut != _raw:
            with open(_disk, "w", encoding="utf-8", newline="") as _fh:
                _fh.write(_mut)
            cg3 = _mk_cg(tmp, "unk3")
            check("真·非法档位 B：node_sensitivity 判 None（回退读文件路径）",
                  subgraph.node_sensitivity(cg3, "mem_real") is None,
                  subgraph.node_sensitivity(cg3, "mem_real"))
            r5 = branches.fork(cg3, ["mem_real"], branch_id="unk4")
            check("真·非法档位 B：fork 跳过（上游可读性 fail-closed）且不落副本",
                  r5.get("ok") is False and r5.get("forked") == []
                  and any("不存在或不可见" in str(s.get("why"))
                          for s in (r5.get("skipped") or [])),
                  r5)
            check("真·非法档位 B：全库无 private 明文",
                  _plaintext(cg3, CANARY) == [], _plaintext(cg3, CANARY))
        else:
            check("回退路径腿可构造（盘上 frontmatter 档位可改写）", False, _raw[:120])
    else:
        check("回退路径腿可构造（找到盘上节点文件）", False, cg2.root)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    mutate = ""
    for a in argv:
        if a.startswith("--mutate="):
            mutate = a.split("=", 1)[1].strip()
    if mutate:
        print("[定点变异] %s" % mutate)
        if mutate == "force_internal":
            # 复刻改前行为：派生写一律落 internal（add 缺省归一）
            branches._inherit_sensitivity = lambda cg, nid: "internal"
        elif mutate == "allow_downgrade":
            # 撤掉降密级闸：merge 恒放行
            branches._merge_downgrades = lambda main_sens, branch_sens: False
        elif mutate == "allow_unjudged":
            # 撤掉 fail-closed 判据：判不了也照写（None 直传 add ⇒ 归一成 internal）
            branches._fail_closed_on_unjudged = lambda sens: False
        elif mutate == "bypass_single_point":
            # 复刻「三处各写一份判据」的形态：调用点绕过 _inherit_sensitivity 单点
            _s = open(branches.__file__, encoding="utf-8").read()
            _m = _s.replace("= _inherit_sensitivity(cg,", "= _bypass_sensitivity(cg,")
            _m += ("\n\ndef _bypass_sensitivity(cg, nid):\n"
                   "    from . import subgraph as _sg\n"
                   "    return _sg.node_sensitivity(cg, nid)\n")
            exec(compile(_m, branches.__file__, "exec"), branches.__dict__)
        else:
            print("未知变异：%s（可选 force_internal / allow_downgrade / "
                  "allow_unjudged / bypass_single_point）" % mutate)
            return 2
    tmp = tempfile.mkdtemp(prefix="brsens_")
    try:
        case_private(tmp)
        case_internal(tmp)
        case_downgrade_gate(tmp)
        case_extra_strip(tmp)
        case_single_point(tmp)
        case_unjudgeable(tmp)
    except Exception:                                       # noqa: BLE001
        traceback.print_exc()
        FAILS.append("未捕获异常")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + "=" * 68)
    print("通过 %d / 失败 %d" % (PASS, len(FAILS)))
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    print("=" * 68)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
