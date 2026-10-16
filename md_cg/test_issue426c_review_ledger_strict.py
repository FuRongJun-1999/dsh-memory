# -*- coding: utf-8 -*-
# 功能名：inbox/decisions 追加失败不得静默（issue #426-C）
# 生效条件：python -X utf8 -m md_cg.test_issue426c_review_ledger_strict [--mutate]；
#           被测面＝md_cg/mdcos.py 的三个「不能丢」写点：propose→inbox、_record_decision→decisions、
#           _cascade_dedup→decisions
# 子功能：A 组＝inbox 写失败响亮失败且不产生假入队；B 组＝decisions 写失败 fail-closed（accept/级联）；
#         E 组＝三写点消费返回值钉子
# 执行：--mutate 时就地短路一条判据（三处检查各撤一处），指定断言须恰好转红
# 不适用条件：不判进程被杀等 crash 时序（issue #426-C 修复建议 3，另案）；不判其它 121 处 append_jsonl 调用点
"""issue #426-C 守卫：07b18ce 之后 append_jsonl 改返回 False，inbox/decisions 写点不读返回值。

病象（修前）：inbox 写失败时改写回执仍 ok:true/moved_to=review_queue/hint「不需要
重试」；decisions 写失败时 accept 仍 ok:true，重开后该单回待审、重复 accept 会重复
落盘。修前（07b18ce 父提交）同一故障是响亮的 PermissionError。

修复语义：三个「不能丢」写点消费 append_jsonl 返回值，False 即抛 OSError
（issue #426-C 修复建议 1）——I/O 故障时 propose/accept 从静默成功回到响亮失败，
正常路径逐位不变。
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SELF = os.path.abspath(__file__)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_CC = "# 功能名：部署\n# 生效条件：部署相关\n# 子功能：端口\n# 执行：%s\n# 验证方式：用户自述\n# 不适用条件：无关话题"
_CHECKS = []
FAILS = []


def _check(name, cond, detail=""):
    if name not in _CHECKS:
        _CHECKS.append(name)
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


class _Env:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="iss426c_")
        self.saved = {}

    def __enter__(self):
        from md_cg import crypto
        env = {"MDCG_ROOT": self.dir + "/brain",
               "MDCG_STATE_ROOT": self.dir + "/state",
               "MDCG_AUX_ROOT": self.dir + "/auxstore",
               "MDCG_DATA_ROOT": self.dir + "/data",
               "MDCG_EXPORT_ROOT": self.dir,
               "MDCG_TOKEN_FILE": self.dir + "/auxstore/tokens.json",
               "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
               crypto.MASTER_ENV: "ab" * 32}
        for k, v in env.items():
            self.saved[k] = os.environ.get(k)
            os.environ[k] = v
        from md_cg.mdcos import MdCGSecure
        from md_cg.security import Principal
        self.cg = MdCGSecure(os.environ["MDCG_ROOT"],
                             principal=Principal(clearance="secret",
                                                 can_admin=True), autoflush=1)
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


def _fail_append_for(path_eq):
    """返回 (patcher, restore)：让 mdcos.append_jsonl 对 path_eq 返回 False，其它透传。"""
    import md_cg.mdcos as mdcos
    real = mdcos.append_jsonl
    key = os.path.abspath(path_eq)

    def patched(path, rec):
        if os.path.abspath(str(path)) == key:
            return False
        return real(path, rec)

    def restore():
        mdcos.append_jsonl = real

    mdcos.append_jsonl = patched
    return patched, restore


def _assertions():
    print("== A 组：inbox 写失败响亮失败（不产生假入队） ==")
    with _Env() as e:
        r0 = e.cg.propose("w_ok", _CC % "端口 7001", info=True)
        _check("A01 前提：正常 propose 返回 pid",
               isinstance(r0, dict) and bool(r0.get("pid")), r0)
        _, restore = _fail_append_for(e.cg.inbox_log)
        try:
            try:
                e.cg.propose("w_fail", _CC % "端口 7002", info=True)
                exc = None
            except Exception as ex:                     # noqa: BLE001
                exc = ex
        finally:
            restore()
        _check("A02 ★行：inbox 写失败 ⇒ 抛 OSError（不再回 pid）",
               isinstance(exc, OSError) and "审核队列写入失败" in str(exc), exc)
        lst = e.cg.review_list() or []
        _check("A03 ★行：失败提案未产生假入队（队列正文无 7002）",
               all("7002" not in ((x.get("content")) or "") for x in lst))

    print("== B 组：decisions 写失败 fail-closed ==")
    with _Env() as e:
        p1 = e.cg.propose("b_ok", _CC % "端口 7101", info=True)["pid"]
        d1 = e.cg.review_decide(p1, "accept", reason="ok")
        _check("B01 前提：正常 accept 成功", bool(d1.get("ok")), d1)
        p2 = e.cg.propose("b_fail", _CC % "端口 7102", info=True)["pid"]
        _, restore = _fail_append_for(e.cg.decisions_log)
        try:
            try:
                e.cg.review_decide(p2, "accept", reason="x")
                exc2 = None
            except Exception as ex:                     # noqa: BLE001
                exc2 = ex
        finally:
            restore()
        _check("B02 ★行：decisions 写失败 ⇒ accept 抛 OSError（不再回 ok=true）",
               isinstance(exc2, OSError) and "裁决记录写入失败" in str(exc2), exc2)
    with _Env() as e:                                    # 级联出清面
        p3 = e.cg.propose("c_main", _CC % "端口 7201", info=True)["pid"]
        with io.open(e.cg.inbox_log, encoding="utf-8") as fh:
            rec0 = json.loads(fh.read().strip().split("\n")[-1])
        ph = rec0.get("payload_hash")
        brother = {"t": time.time(), "pid": "prop_brother_c", "id": "c_brother",
                   "content": rec0.get("content"), "layer": "knowledge",
                   "tags": [], "condition_space": {}, "payload_hash": ph,
                   "verify": {}, "verify_hash": "", "extra": {}, "actor": "x",
                   "session": "s"}
        with io.open(e.cg.inbox_log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(brother, ensure_ascii=False) + "\n")
        e.cg._inbox_scan_size = -1                       # 让增量缓存重读（若有）
        _, restore = _fail_append_for(e.cg.decisions_log)
        try:
            try:
                e.cg._cascade_dedup(p3, ph, "accept")
                exc3 = None
            except Exception as ex:                     # noqa: BLE001
                exc3 = ex
        finally:
            restore()
        _check("B03 ★行：级联出清写失败 ⇒ 抛 OSError（未出清的不进 closed）",
               isinstance(exc3, OSError) and "级联裁决记录写入失败" in str(exc3), exc3)

    print("== E 组：三写点消费返回值钉子 ==")
    with io.open(os.path.join(_REPO, "md_cg/mdcos.py"), encoding="utf-8") as fh:
        src = fh.read()
    _check("E01 ★钉子：三处写点均 if not append_jsonl(...) fail-closed",
           src.count("if not append_jsonl(") >= 3, src.count("if not append_jsonl("))
    _check("E02 ★钉子：三处错误文案各就其位",
           "审核队列写入失败" in src and "裁决记录写入失败" in src
           and "级联裁决记录写入失败" in src)


def _run_assertions():
    global FAILS
    FAILS = []
    del _CHECKS[:]
    _assertions()
    print("通过 %d / 失败 %d" % (len(_CHECKS) - len(FAILS), len(FAILS)))
    return len(FAILS)


def _subprocess_fail_names():
    r = subprocess.run([sys.executable, "-X", "utf8", _SELF, "--assert-only"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=_REPO, timeout=600)
    names = set(re.findall(r"(?m)^\s*FAIL\s+([A-Z]\d+)", r.stdout or ""))
    return names, (r.stdout or "") + (r.stderr or "")


_INBOX_OK = chr(10).join([
    "            # issue #426-C：inbox 是队列权威源，写失败必须响亮失败——",
    "            # 不得回执「已入队、不需要重试」而全库零副本。",
    "            if not append_jsonl(self.inbox_log, rec):",
    "                raise OSError(\"审核队列写入失败（%s）：提案未入队，请重试\"",
    "                              % self.inbox_log)",
])
_DEC_OK = chr(10).join([
    "            # issue #426-C：裁决记录不能丢——写失败 fail-closed（动作可能已落盘，",
    "            # 调用方必须知道并先排查，而不是收到 ok=true 后重复 accept）。",
    "            if not append_jsonl(self.decisions_log, rec):",
    "                raise OSError(\"裁决记录写入失败：目标 %s 可能已落盘，请勿重复 \"",
    "                              \"accept，先排查 %s\"",
    "                              % (rec.get(\"target_id\"), self.decisions_log))",
])
_CAS_OK = chr(10).join([
    "                # issue #426-C：级联出清同属「不能丢」的裁决账，写失败 fail-closed。",
    "                if not append_jsonl(self.decisions_log, rec):",
    "                    raise OSError(\"级联裁决记录写入失败：兄弟提案 %s 未出清，\"",
    "                                  \"先排查 %s\" % (bpid, self.decisions_log))",
])
_ARMS = {
    "M1": ("md_cg/mdcos.py", _INBOX_OK + chr(10),
           "            append_jsonl(self.inbox_log, rec)" + chr(10),
           {"A02", "E01", "E02"}),
    "M2": ("md_cg/mdcos.py", _DEC_OK + chr(10),
           "            append_jsonl(self.decisions_log, rec)" + chr(10),
           {"B02", "E01"}),
    "M3": ("md_cg/mdcos.py", _CAS_OK + chr(10),
           "                append_jsonl(self.decisions_log, rec)" + chr(10),
           {"B03", "E01", "E02"}),
}


def _mutate(argv):
    want = ""
    for a in argv:
        if a == "--mutate":
            want = want or "ALL"
        elif a.startswith("--mutate="):
            want = a.split("=", 1)[1]
    if not want:
        return 0
    ids = sorted(_ARMS) if want == "ALL" else [want]
    red = 0
    for mid in ids:
        if mid not in _ARMS:
            print("[ANCHOR-MISS] %s：未登记该变异臂" % mid)
            return 2
        rel, old, new, expect = _ARMS[mid]
        target = os.path.join(_REPO, *rel.split("/"))
        with open(target, "rb") as fh:
            orig = fh.read()
        try:
            text = orig.decode("utf-8")
            nl = "\r\n" if "\r\n" in text else "\n"
            norm = text.replace("\r\n", "\n")
            _cnt = norm.count(old)
            if _cnt != 1:
                print("[ANCHOR-MISS] %s：锚点命中 %d 次（期望 1）⇒ 无法变异，判据失效"
                      % (mid, _cnt))
                return 2
            with open(target, "wb") as fh:
                fh.write(norm.replace(old, new).replace("\n", nl).encode("utf-8"))
            actual, out = _subprocess_fail_names()
            if actual == expect:
                print("[MUTATE-OK]   %s：指定断言转红 %s" % (mid, sorted(actual)))
            else:
                print("[MUTATE-FAIL] %s：期望红 %s，实际红 %s"
                      % (mid, sorted(expect), sorted(actual)))
                for line in out.splitlines():
                    if line.strip().startswith("FAIL"):
                        print("    " + line)
                red += 1
        finally:
            with open(target, "wb") as fh:
                fh.write(orig)
    print("反证结果：%d 条变异，%s" % (len(ids), "全部恰好命中" if red == 0 else "%d 条未命中" % red))
    return 1 if red else 0


if __name__ == "__main__":
    _f = _run_assertions()
    if "--assert-only" in sys.argv:
        sys.exit(1 if _f else 0)
    _m = _mutate(sys.argv[1:])
    sys.exit(1 if (_f or _m) else 0)
