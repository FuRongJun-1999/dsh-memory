# -*- coding: utf-8 -*-
"""issue #355 守卫：写入硬上限的类型面收口 + oversize_response 死段不复存在。

病象（main a0274500，本机实跑）：当天 e8d0ddf5（fix #324）把硬上限从 content 扩到
其余字段，但留下两处残口——
  ① 死段：return None 之后留着 pre-#324 的整段旧响应体（289-298 行，AST 顶层可达性
     实测），文件里含 gate 字面量的字典变成 2 个，推翻 #212/#324 自己写下的
     「判据与响应体收敛到唯一构造点」；
  ② 类型面：判据①对非 str content 记 n=0，判据②的总字节循环把 content 排除在外
     ⇒ 1.5MB dict 两条判据都不过、闸返回 None 放行，随后击穿库层裸 AttributeError
     （实测盘上零放大，但 _write_attempts.jsonl 零痕迹——#142② 三态对账断在闸前）。

修法：删死段（零行为变更）；oversize_response 入口对 content 非 str（且非 None）按
类型二值直接拒收（与字节数无关），响应体仍走唯一构造点 _oversize_body 的 note 通道。
显式 None/缺省 content 维持既有放行形态；str 面（#82.3/#324）逐字不变。

判据组：
  T1 行为面：dict/list 结构化拒收、文案点名收到类型；str 超限/正常/缺省/显式 None 四对照不退化；
  T2 账本面：dict 经 cg(op=write) 拒收后 _write_attempts.jsonl 恰多一行且 halted_by=writelimit_size，节点 .md 零落盘；
  T3 源码面：gate 字面量全文件恰 1；oversize_response 首个顶层 return None 之后无语句（AST）；旧文案 0 命中；
  T4 构造点面：类型分支经 _oversize_body(note=...)，不拼第二份字面量。

运行：python -X utf8 -m md_cg.test_issue355_writepipe_typeface [--mutate]
退出码：0 全绿；1 有红；2 变异锚点未命中（ANCHOR-MISS）。
"""
from __future__ import annotations

import ast
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_WP = os.path.join(_REPO, "md_cg", "writepipe.py")
_GATE_LIT = '"' + 'gate' + '": "' + 'writelimit_size' + '"'
_BIG = 1_500_000

_RESULTS = []


def _check(name, cond, detail=""):
    _RESULTS.append((bool(cond), name, detail))
    print(("  PASS " if cond else "  FAIL ") + name
          + ("" if cond else ("  <- " + repr(detail)[:220])))


def _src():
    return io.open(_WP, encoding="utf-8", newline="").read()


class _Env:
    """隔离库根（与 #313 守卫同形态），供端到端 _dispatch 与盘量读数。"""

    def __enter__(self):
        from md_cg import autonomy_modes as _am
        from md_cg import crypto
        self.dir = tempfile.mkdtemp(prefix="iss355_")
        self.saved = {}
        env = {"MDCG_ROOT": self.dir + "/brain",
               "MDCG_STATE_ROOT": self.dir + "/state",
               "MDCG_AUX_ROOT": self.dir + "/auxstore",
               "MDCG_DATA_ROOT": self.dir + "/data",
               "MDCG_EXPORT_ROOT": self.dir,
               "MDCG_TOKEN_FILE": self.dir + "/auxstore/tokens.json",
               "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
               _am.AUTONOMY_ENV_KEYS["mode"]: "confirm",
               crypto.MASTER_ENV: "ab" * 32}
        for k, v in env.items():
            self.saved[k] = os.environ.get(k)
            os.environ[k] = v
        os.makedirs(env["MDCG_AUX_ROOT"], exist_ok=True)
        from md_cg.mdcos import MdCGSecure
        from md_cg.security import Principal
        self.cg = MdCGSecure(env["MDCG_ROOT"],
                             principal=Principal(clearance="secret",
                                                 can_admin=True), autoflush=1)
        self.attempt = os.path.join(env["MDCG_ROOT"], "_write_attempts.jsonl")
        self.root = env["MDCG_ROOT"]
        return self

    def __exit__(self, *exc):
        try:
            self.cg.close()
        except Exception:                               # noqa: BLE001
            pass
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.dir, ignore_errors=True)
        return False


# ---------------------------------------------------------------- T1 行为面
def t1():
    print("== T1 行为面：类型二值拒收，str 面与缺省面不退化 ==")
    from md_cg import writepipe as wp
    d = wp.oversize_response("t1d", {"content": {"blob": "x" * _BIG},
                                     "node_id": "t1d"})
    _check("T1.1 星号 dict content(1.5MB) 被闸结构化拒收（gate/committed/verdict 齐全）",
           isinstance(d, dict) and d.get("gate") == "writelimit_size"
           and d.get("committed") is False
           and (d.get("verdict") or {}).get("state") == "REJECT", d)
    _check("T1.2 拒收文案点名**收到的类型**（不是字节超限文案）",
           isinstance(d, dict) and "dict" in (d.get("error") or "")
           and "超过写入硬上限" not in (d.get("error") or ""), (d or {}).get("error"))
    l = wp.oversize_response("t1l", {"content": ["z" * 700] * 2000,
                                     "node_id": "t1l"})
    _check("T1.3 list content(1.4MB) 同判据拒收（文案点名 list）",
           isinstance(l, dict) and "list" in (l.get("error") or ""), l)
    s = wp.oversize_response("t1s", {"content": "x" * _BIG, "node_id": "t1s"})
    _check("T1.4 str 超限面逐字不退化（#82.3 文案 + field=content）",
           isinstance(s, dict) and "超过写入硬上限（issue #82.3）"
           in (s.get("error") or "") and s.get("field") == "content", s)
    _check("T1.5 正常短 str 照旧放行",
           wp.oversize_response("t1ok", {"content": "正常内容",
                                         "node_id": "t1ok"}) is None)
    _check("T1.6 缺省 content 与显式 None 维持既有放行形态（不扩张语义）",
           wp.oversize_response("t1n", {"node_id": "t1n"}) is None
           and wp.oversize_response("t1m", {"node_id": "t1m",
                                            "content": None}) is None)


# ---------------------------------------------------------------- T2 账本面
def t2():
    print("== T2 账本面：类型拒收走尝试账本（三态可账），且不落节点 ==")
    from md_cg import mcp_server
    with _Env() as e:
        before = os.path.getsize(e.attempt) if os.path.exists(e.attempt) else 0
        try:
            out = mcp_server._dispatch(e.cg, "cg",
                                       {"op": "write", "node_id": "t2nid",
                                        "content": {"blob": "x" * _BIG}})
            err = None
        except Exception as exc:                        # noqa: BLE001
            out, err = None, type(exc).__name__
        after = os.path.getsize(e.attempt) if os.path.exists(e.attempt) else 0
        _check("T2.1 星号 dict 写入被闸拒后 _write_attempts.jsonl 变多且回执 gate 齐全",
               after > before and isinstance(out, dict)
               and out.get("gate") == "writelimit_size",
               {"delta": after - before, "raise": err,
                "gate": (out or {}).get("gate")})
        try:
            rec = json.loads(io.open(e.attempt, encoding="utf-8")
                             .read().splitlines()[-1])
        except Exception:                               # noqa: BLE001
            rec = {}
        _check("T2.2 该行 halted_by=writelimit_size 且 id 对得上（不是击穿后的它账）",
               rec.get("halted_by") == "writelimit_size"
               and rec.get("id") == "t2nid", rec)
        n2 = [os.path.join(a, f) for a, _dd, fs in os.walk(e.root)
              for f in fs if f.endswith(".md") and "t2nid" in f]
        _check("T2.3 拒收不落节点正文（零盘上放大，既有口径保持）", not n2, n2)


# ---------------------------------------------------------------- T3 源码面
def t3():
    print("== T3 源码面：唯一构造点 + 无死段（AST 顶层可达性）==")
    src = _src()
    _check("T3.1 星号 含 gate 的字典字面量全文件恰 1 个（死段回植即红）",
           src.count(_GATE_LIT) == 1, src.count(_GATE_LIT))
    tree = ast.parse(src)
    bad = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "oversize_response":
            st = list(node.body)
            for i2, stn in enumerate(st):
                if (isinstance(stn, ast.Return)
                        and isinstance(stn.value, ast.Constant)
                        and stn.value.value is None):
                    after = [x for x in st[i2 + 1:]
                             if not (isinstance(x, ast.Expr)
                                     and isinstance(x.value, ast.Constant)
                                     and isinstance(x.value.value, str))]
                    bad = (len(after), stn.lineno)
                    break
    _check("T3.2 星号 oversize_response 首个顶层 return None 之后无任何语句（AST 实证）",
           bad is not None and bad[0] == 0, bad)
    _check("T3.3 旧死段文案已消失（缩短正文 全文件 0 命中）",
           "缩短正文" not in src, src.count("缩短正文"))


# ---------------------------------------------------------------- T4 构造点面
def t4():
    print("== T4 构造点面：类型面走 _oversize_body 的 note 通道 ==")
    src = _src()
    tree = ast.parse(src)
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "oversize_response":
            for n2 in ast.walk(node):
                if (isinstance(n2, ast.Call) and isinstance(n2.func, ast.Name)
                        and n2.func.id == "_oversize_body"):
                    calls.append(n2)
    note_kw = [c for c in calls if any(k.arg == "note" for k in c.keywords)]
    _check("T4.1 类型面分支以 note= 关键字调 _oversize_body（不拼第二份字面量）",
           len(note_kw) == 1, [len(calls), len(note_kw)])
    sig = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_oversize_body":
            sig = [a.arg for a in node.args.args]
    _check("T4.2 _oversize_body 形参含 note（默认 None，其余调用点零改动）",
           sig is not None and "note" in sig and sig[-1] == "note", sig)


# ---------------------------------------------------------------- 定点变异
# 锚全部取 writepipe.py 现行文本（LF）；(说明, 旧, 新, 预期红前缀)
_MV = (
    ("V1 类型面判据停用（回到 #355 病灶：dict 过闸、库层裸异常、账本无痕）",
     "    if _cv is not None and not isinstance(_cv, str):",
     "    if False:",
     ("T1.1", "T1.2", "T1.3", "T2.1", "T2.2")),
    ("V2 note 通道退化成字节文案（点名类型丢失，字节数误导仍在）",
     '        _err = "content 类型非法（issue #355）：须为字符串，收到 " + note',
     '        _err = "content 超过写入硬上限（issue #82.3）"',
     ("T1.2", "T1.3")),
    ("V3 死段回植（唯一构造点被推翻、return None 后挂语句）",
     "    return None\n\n\nclass WritePipeline:",
     "    return None\n    return {\n        \"gate\": \"writelimit_size\",\n    }\n\n\nclass WritePipeline:",
     ("T3.1", "T3.2")),
    ("V4 类型面丢掉 note 实参（走字节文案）",
     '                              "content", note=type(_cv).__name__)',
     '                              "content")',
     ("T1.2", "T1.3", "T4.1")),
)


def _live_ok():
    """跑本体前扫一遍：生产源里若躺着 _MV 的新侧串，说明上一次 --mutate 被强杀留了残留。"""
    src = _src()
    bad = []
    for desc, _old, new, _exp in _MV:
        probe = new.split("class WritePipeline:")[0]
        if "\n" in probe or probe not in src:
            continue
        bad.append(desc)
    return bad


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss355_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__",
                                                           "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml",
                                              "package.json")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ, PYTHONPATH=tree, PYTHONUTF8="1",
               PYTHONDONTWRITEBYTECODE="1", MDCG_GUARD_MUT_UNDER_TEST="1")
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue355_writepipe_typeface"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "  FAIL " in ln]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐条把判据改回改动前形态，守卫必须转红")
    tree = _mirror_build()
    rc, reds, out = _run_in(tree)
    print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
    if rc != 0 or reds:
        print(chr(10).join(out.splitlines()[-20:]))
        return 1
    miss = []
    bad = []
    ok = 0
    for desc, old, new, exp in _MV:
        p = os.path.join(tree, "md_cg", "writepipe.py")
        t = io.open(p, encoding="utf-8", newline="").read()
        if t.count(old) != 1:
            miss.append(desc)
            print("  ANCHOR-MISS %s —— 锚点命中 %d 次" % (desc, t.count(old)))
            continue
        bak = t
        io.open(p, "w", encoding="utf-8", newline="").write(
            t.replace(old, new, 1))
        for root2, _dd, ff in os.walk(tree):
            if os.path.basename(root2) == "__pycache__":
                shutil.rmtree(root2, ignore_errors=True)
        rc2, reds2, out2 = _run_in(tree)
        io.open(p, "w", encoding="utf-8", newline="").write(bak)
        hit = [r3 for r3 in reds2 if r3.startswith(exp)]
        if rc2 != 0 and len(hit) == len(exp):
            ok += 1
            print("  OK   %s  红项=%d 指定命中=%d/%d"
                  % (desc, len(reds2), len(hit), len(exp)))
        else:
            bad.append(desc)
            print("  MISMATCH %s 红项=%d 指定命中=%d/%d"
                  % (desc, len(reds2), len(hit), len(exp)))
            for r3 in reds2[:6]:
                print("        FAIL " + r3[:140])
            if not reds2:
                print(chr(10).join(("        | " + x) for x
                                   in out2.splitlines()[-8:]))
    print("定点变异自证：%s（%d 条不合格%s）"
          % ("PASS" if not bad and not miss else "FAIL", len(bad),
             "，锚点未命中 %d" % len(miss) if miss else ""))
    if miss:
        return 2
    return 0 if not bad else 1


def main():
    if "--mutate" in sys.argv:
        return _mutate()
    if os.environ.get("MDCG_GUARD_MUT_UNDER_TEST") != "1":
        live = _live_ok()
        if live:
            print("!! 盘上源命中变异新侧串（上一次 --mutate 被强杀的残留）：%s"
                  % "；".join(live))
            print("   请 git checkout -- md_cg/writepipe.py 后重跑；本守卫拒跑（rc=2）")
            return 2
    t1()
    t2()
    t3()
    t4()
    bad = [n for ok, n, _d in _RESULTS if not ok]
    print("")
    print("issue #355 结果：%d 通过 / %d 失败"
          % (len(_RESULTS) - len(bad), len(bad)))
    for n in bad:
        print("    红: " + n)
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
