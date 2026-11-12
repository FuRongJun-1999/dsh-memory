# -*- coding: utf-8 -*-
# 功能名：hive/scoreboard.py 的「读件失败」命名出口 bad_files 真实存在且与「文件缺失」可分（issue #511）
# 生效条件：python -X utf8 -m md_cg.test_issue511_scoreboard_bad_files [--mutate]；被测面＝hive/scoreboard.py 的 read_json/_obj/_file_shape/job_record/scan/build
# 子功能：A 组＝复现面（result.json 非映射/坏 JSON 计入 bad_files、缺失不计；spec.json 同；record 级标记；非映射与缺失的 build() 输出可分）；K 组＝非恒真对照（合法映射 bad_files 为空且其它读数逐位不变、全缺失池、read_json 三态哨兵、确定性）；E 组＝名实一致（docstring 点名的 bad_files 在实现里存在、形状判据单点、_obj 的归一语义未被替换）
# 执行：默认断言；--mutate 在内存源码里三条定点变异（bad_files 恒空 / 缺失也算坏件 / 读件哨兵退回 None），红项须与声明逐项相符
# 验证方式：默认全 PASS 且 exit 0；--mutate 每条变异红项集合与声明一致；锚点字面量不在源码 ⇒ exit 2（fail-closed）
# 不适用条件：不判 `_scoreboard.jsonl` 的下游消费方（仓内未找到生产消费方）；不判评分公式（属 #158）；不判 hive/serve_start.py 的 status.json 崩溃面（属 #427，另有守卫）
"""issue #511 守卫：`_obj` 的静默归一让「读件失败」在命名出口上不存在。

病象（修前）：`read_json` docstring 声称「缺失或坏件…会计入 bad_files」，`_obj` 注释声称
「一律按读件失败处理…只计入 bad_files」——但 `bad_files` 这个标识在实现里**不存在**
（全树仅两处注释）。后果：`result.json` 为「合法 JSON 非映射」与「该文件缺失」在
`build()` 全部 9 个顶层键上逐位相同，该路没有任何出口区分这两态。

修法：① `read_json` 用两个哨兵区分「缺失」与「解析失败」（`None` 不再兼任三态）；
② `job_record` 经单点 `_file_shape` 给每个文件判形状，`bad_files` 只收 `nonmap`/`bad_json`
（存在但读不成映射），缺失不混入；③ `build()` 输出 `bad_files` 列表与 `totals.bad_files`，
让 docstring 点名的出口真的存在。映射性判据仍只在 `_obj` 一处（本修不复制它）。
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import types

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_REPO, "hive", "scoreboard.py")
_JID = "h_u09_任务_验证单元_0001"
_FAILS = []


def ok(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        _FAILS.append(name.split()[0])


def _load(src_text, name="sb511"):
    mod = types.ModuleType(name)
    mod.__file__ = _SRC
    exec(compile(src_text, "<sb511>", "exec"), mod.__dict__)
    return mod


def _job(root, files):
    """files: {文件名: ("obj", 值) | ("raw", 文本) | ("missing", None)}。返回 jobs 池。"""
    jobs = os.path.join(root, "jobs")
    d = os.path.join(jobs, _JID)
    os.makedirs(d, exist_ok=True)
    for nm, (kind, val) in files.items():
        p = os.path.join(d, nm)
        if kind == "missing":
            continue
        with io.open(p, "w", encoding="utf-8") as f:
            if kind == "raw":
                f.write(val)
            else:
                json.dump(val, f, ensure_ascii=False)
    return jobs


def _base(**over):
    files = {"status.json": ("obj", {"state": "done"}),
             "spec.json": ("obj", {"commands": ["x"]}),
             "result.json": ("obj", {"ok": True, "content": "c"})}
    files.update(over)
    return files


def run_checks(mod):
    root = tempfile.mkdtemp(prefix="iss511_")
    try:
        # ---- A 组：读件失败必须可见（修前该键不存在）----
        for i, (tag, files, want) in enumerate((
            ("A01 result.json=[1,2,3]（合法 JSON 非映射）",
             _base(**{"result.json": ("obj", [1, 2, 3])}), [_JID + "/result.json"]),
            ("A02 result.json={oops（坏 JSON）",
             _base(**{"result.json": ("raw", "{oops")}), [_JID + "/result.json"]),
            ("A03 result.json=\"x\"（合法 JSON 非映射）",
             _base(**{"result.json": ("obj", "x")}), [_JID + "/result.json"]),
            ("A04 spec.json=[1,2]（合法 JSON 非映射）",
             _base(**{"spec.json": ("obj", [1, 2])}), [_JID + "/spec.json"]),
        ), start=1):
            doc = mod.build(_job(os.path.join(root, "a%d" % i), files))
            ok("%s ⇒ bad_files=%s 且 totals.bad_files=1" % (tag, want),
               doc.get("bad_files") == want and doc["totals"].get("bad_files") == 1,
               (doc.get("bad_files", "<ABSENT>"), doc["totals"]))

        # A05 文件缺失是另一态：不进 bad_files（修前与「非映射」同态）
        doc_missing = mod.build(_job(os.path.join(root, "a05"),
                                     _base(**{"result.json": ("missing", None)})))
        ok("A05 result.json 缺失 ⇒ bad_files 为空（缺失不混入「读件失败」）",
           doc_missing.get("bad_files") == [] and doc_missing["totals"].get("bad_files") == 0,
           (doc_missing.get("bad_files", "<ABSENT>"), doc_missing["totals"]))

        # A06 输出面可分：同一池只改 result.json 三态，非映射与缺失的 build() 必须不同
        doc_nonmap = mod.build(_job(os.path.join(root, "a06n"),
                                    _base(**{"result.json": ("obj", [1, 2, 3])})))
        _diff = [k for k in sorted(set(doc_nonmap) | set(doc_missing))
                 if json.dumps(doc_nonmap.get(k), sort_keys=True, ensure_ascii=False)
                 != json.dumps(doc_missing.get(k), sort_keys=True, ensure_ascii=False)]
        ok("A06 非映射 vs 缺失在 build() 输出面上可分（修前全 9 键逐位相同）",
           "bad_files" in _diff and "totals" in _diff, _diff)

        # A07 记录级形状标记
        rec_n = mod.job_record(os.path.join(root, "a06n", "jobs", _JID))
        rec_m = mod.job_record(os.path.join(root, "a05", "jobs", _JID))
        ok("A07 job_record().bad_files：非映射=['result.json']、缺失=[]",
           rec_n.get("bad_files") == ["result.json"] and rec_m.get("bad_files") == [],
           (rec_n.get("bad_files", "<ABSENT>"), rec_m.get("bad_files", "<ABSENT>")))

        # ---- K 组：非恒真对照（含过度收紧方向）----
        doc_ok = mod.build(_job(os.path.join(root, "k01"), _base()))
        ok("K01 合法映射：bad_files 为空且其它读数不变（jobs=1 / delta_sum=12 / det 计入）",
           doc_ok.get("bad_files") == [] and doc_ok["totals"].get("bad_files") == 0
           and doc_ok["totals"]["jobs"] == 1 and doc_ok["totals"]["delta_sum"] == 12
           and (doc_ok["by_unit"][0]["deterministic"] == 1),
           (doc_ok.get("bad_files", "<ABSENT>"), doc_ok["totals"]))

        doc_all_missing = mod.build(_job(os.path.join(root, "k02"), {
            "status.json": ("missing", None), "spec.json": ("missing", None),
            "result.json": ("missing", None)}))
        ok("K02 三件全缺失：bad_files 为空、job 进 bad_ids（缺失语义不变）",
           doc_all_missing.get("bad_files") == []
           and doc_all_missing["bad_ids"] == [_JID], doc_all_missing)

        # K03 read_json 三态哨兵：缺失 / 坏 JSON / 合法 null 必须三者可分
        p_missing = os.path.join(root, "k03_missing.json")
        p_bad = os.path.join(root, "k03_bad.json")
        p_null = os.path.join(root, "k03_null.json")
        with io.open(p_bad, "w", encoding="utf-8") as f:
            f.write("{oops")
        with io.open(p_null, "w", encoding="utf-8") as f:
            f.write("null")
        r_missing, r_bad, r_null = (mod.read_json(p_missing), mod.read_json(p_bad),
                                    mod.read_json(p_null))
        ok("K03 read_json 三态可分：缺失=_MISSING、坏 JSON=_BAD_JSON、合法 null=None",
           r_missing is getattr(mod, "_MISSING", object())
           and r_bad is getattr(mod, "_BAD_JSON", object())
           and r_null is None and r_missing is not r_bad,
           (r_missing, r_bad, r_null))

        doc_ok2 = mod.build(_job(os.path.join(root, "k01"), _base()))
        ok("K04 确定性：同输入两次 build 逐字段相同",
           json.dumps(doc_ok, sort_keys=True, ensure_ascii=False)
           == json.dumps(doc_ok2, sort_keys=True, ensure_ascii=False), "")

        # ---- E 组：名实一致（docstring 点名的出口必须真的存在）----
        src = io.open(_SRC, encoding="utf-8").read()
        ok("E01 build() 真输出 bad_files 列表键（不只是 docstring 里的名字）",
           '"bad_files": bad_files,' in src and '"bad_files": len(bad_files),' in src, "")
        ok("E02 job_record 真带 bad_files 标记（每条记录可见）",
           '"bad_files": bad_files,' in src and 'bad_files = sorted(' in src, "")
        ok("E03 形状判据单点：`_file_shape` 定义一处；映射性判据仍只在 `_obj` 一处",
           src.count("def _file_shape(") == 1 and src.count("isinstance(v, dict)") == 1,
           (src.count("def _file_shape("), src.count("isinstance(v, dict)")))
        ok("E04 _file_shape 不复制映射判据（观察 _obj 输出：obj == v）",
           'return "ok" if obj == v else "nonmap"' in src, "")
        ok("E05 read_json docstring 点名的 bad_files 与实现出口同名",
           "bad_files" in mod.read_json.__doc__
           and '"bad_files": bad_files,' in src, "")
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---- 定点变异（源码级）-------------------------------------------------------
_AGG = "    bad_files = sorted(_bad_files)"
_AGG_EMPTY = "    bad_files = []   # 变异：出口恒空（回 #511 缺陷）"
_SHAPE = '    bad_files = sorted(nm for nm, sh in _shapes.items() if sh in ("nonmap", "bad_json"))'
_SHAPE_LOOSE = '    bad_files = sorted(nm for nm, sh in _shapes.items() if sh != "ok")   # 变异：缺失也算坏件'
_READ_MISSING = "        return _MISSING"
_READ_NONE = "        return None   # 变异：缺失/坏件同态（回缺陷）"
_READ_BAD = "        return _BAD_JSON"

_MUTATIONS = (
    # M1 回缺陷：build() 的 bad_files 恒空 ⇒ 非映射/坏 JSON 都不可见：A01/A02/A03/A04/A06 红。
    ("M1 回缺陷：bad_files 出口恒空", ((_AGG, _AGG_EMPTY),),
     ("A01", "A02", "A03", "A04", "A06")),
    # M2 过度收紧：把「缺失」也计入 ⇒ 缺失态被报成读件失败：A05/A06/A07（记录级）+K02 红。
    ("M2 过度收紧：缺失也算 bad_files", ((_SHAPE, _SHAPE_LOOSE),),
     ("A05", "A06", "A07", "K02")),
    # M3 回缺陷：read_json 的「缺失」哨兵退回 None ⇒ 与坏件同态、且被 _file_shape 判成 nonmap：
    # A05/A06/A07/K02/K03 红。
    ("M3 回缺陷：缺失哨兵退回 None（三态压成两态）", ((_READ_MISSING, _READ_NONE),),
     ("A05", "A06", "A07", "K02", "K03")),
)


def _apply(text, pairs):
    for old, new in pairs:
        if text.count(old) != 1:
            return None, "锚点命中 %d 次" % text.count(old)
        text = text.replace(old, new, 1)
    return text, ""


def _mutate(base):
    print("!! 定点变异自证：出口恒空（回缺陷）＋ 缺失也算坏件（过度收紧）＋ 哨兵退回 None")
    bad = []
    for desc, pairs, expect in _MUTATIONS:
        mut, why = _apply(base, pairs)
        if mut is None:
            print("  ANCHOR-MISS %s  %s" % (desc, why))
            bad.append(desc)
            continue
        global _FAILS
        _FAILS = []
        try:
            run_checks(_load(mut))
        except BaseException as exc:              # noqa: BLE001
            _FAILS = ["<崩溃:%s>" % type(exc).__name__]
        got = sorted(set(_FAILS))
        if got == sorted(expect):
            print("  OK   %s  红项=%s" % (desc, got))
        else:
            print("  MISMATCH %s  实际=%s 期望=%s" % (desc, got, sorted(expect)))
            bad.append(desc)
    print("定点变异：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
    return len(bad)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    base = io.open(_SRC, encoding="utf-8").read()
    # 锚点自检（fail-closed）：修法的关键判据不在源码里 ⇒ exit 2。
    if src_anchor_missing(base):
        print("ANCHOR-FAIL：bad_files 出口/_file_shape 字面量不在 hive/scoreboard.py 里")
        return 2
    if "--mutate" in argv:
        return 1 if _mutate(base) else 0
    print("== #511 hive/scoreboard.py 的 bad_files 出口 ==")
    run_checks(_load(base))
    print("")
    if _FAILS:
        print("issue #511 结果：%d 失败 —— %s" % (len(_FAILS), " ".join(_FAILS)))
        return 1
    print("issue #511 结果：全部通过")
    return 0


def src_anchor_missing(src):
    return not (src.count("def _file_shape(") == 1
                and '"bad_files": bad_files,' in src
                and 'if sh in ("nonmap", "bad_json")' in src)


if __name__ == "__main__":
    sys.exit(main())
