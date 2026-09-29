#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_verify_open_encoding.py — verify_open_encoding.py 的回放断言（脚本式，随 python 全量套件跑）。

覆盖（B 项验证清单 ②③④）：
  ① 正跑：全仓扫描必须全绿（基线为空，零容忍）——且必须真的扫到了面（不被空扫描面假绿）；
  ② 自证：--self-test 必须 0（判据锚 / 扫描面锚 / 定点变异三项）；
  ③ 定点变异：把「新增一处裸文本 open」注入**完整扫描面的临时副本**，守卫必须转红且**恰好命中 1 项**；
     同时注入二进制 / Attribute / 带 encoding 三种变体，守卫必须**不**报（对照 ③④ 的假阳性面）；
  ④ ANCHOR-MISS：判据锚改错 / 扫描面塌陷 / 对照点位消失 / 扫描目录缺失 / 契约点名点位级锚漂移，
     五条都必须退出码 2；
  ⑤ 白名单双向：填入一条不存在的豁免必须退出 1 并报「有而未命中」（不得静默豁免）。

命令一律走 argv 列表 + 显式 UTF-8（工作纪律第 15 条）。
"""
from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_GUARD = os.path.join(_HERE, "verify_open_encoding.py")


# 生效条件：以子进程方式跑守卫，返回 CompletedProcess（显式 UTF-8 + PYTHONUTF8=1）。
def run(*args):
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    return subprocess.run([sys.executable, _GUARD] + list(args),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, cwd=_REPO)


# 生效条件：__file__ 指向守卫源码时，importlib 直载守卫模块（供就地改配置做 ANCHOR-MISS 反证）。
def load_guard():
    spec = importlib.util.spec_from_file_location("_voe_test", _GUARD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# 生效条件：在内存里换掉守卫的某组模块级配置后跑 main(argv)，返回 (退出码, stdout)；上下文退出即还原。
class _Patched:
    def __init__(self, mod, **kw):
        self.mod, self.kw = mod, kw
        self.old = {}

    def __enter__(self):
        for k, v in self.kw.items():
            self.old[k] = getattr(self.mod, k)
            setattr(self.mod, k, v)
        return self

    def __exit__(self, *a):
        for k, v in self.old.items():
            setattr(self.mod, k, v)
        return False


# 生效条件：patched 模块在给定 argv 下跑 main，捕获 stdout，返回 (退出码, 文本)。
def run_main(mod, argv):
    buf, old = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        code = mod.main(argv)
    finally:
        sys.stdout = old
    return code, buf.getvalue()


def main():
    # ---- ① 正跑：基线为空 ----
    got = run()
    assert got.returncode == 0, "全仓扫描未全绿：\n" + got.stdout + got.stderr
    assert "✔ 全部文本模式调用点均显式声明 encoding=" in got.stdout, got.stdout
    assert "二进制 open" in got.stdout and "Attribute .open" in got.stdout, got.stdout
    print("① 正跑全绿：", [ln for ln in got.stdout.splitlines() if ln.startswith("扫描面")][0])

    # ---- ② 自证 ----
    got = run("--self-test")
    assert got.returncode == 0, "自证未通过：\n" + got.stdout + got.stderr
    assert "✔ 自证通过" in got.stdout, got.stdout
    print("② 自证 0：", [ln for ln in got.stdout.splitlines() if "定点变异" in ln][0])

    m = load_guard()

    # ---- ③ 定点变异：完整扫描面临时副本上注入 ----
    with tempfile.TemporaryDirectory(prefix="voe_surface_") as tmp:
        assert m._materialize_surface(tmp) > 0, "扫描面物化为空"
        target = m._MUTATION_TARGETS[0]
        src_abs = os.path.join(_REPO, target)
        with open(src_abs, encoding="utf-8", errors="replace") as fh:
            orig = fh.read()
        dst = os.path.join(tmp, target)

        cases = (
            ("裸文本 open（无 mode）", "    return open(p)", 1),
            ("裸文本 open（mode='w'）", '    return open(p, "w")', 1),
            ("裸文本 open（mode 非字面量）", "    return open(p, m)", 1),
            ("read_text 无 encoding", "    return Path(p).read_text()", 1),
            ("二进制 open（不得报）", '    return open(p, "rb")', 0),
            ("Attribute io.open（不得报）", '    return io.open(p, "w")', 0),
            ("Attribute tarfile.open（不得报）",
             '    return tarfile.open(name=p, mode="r:gz")', 0),
            ("带 encoding 的 open（不得报）",
             '    return open(p, "w", encoding="utf-8")', 0),
        )
        for i, (label, injected, want) in enumerate(cases):
            new_src, expect_line = m._inject(orig, injected)
            if i == 0:
                # 首例用**完整扫描面临时副本**证明「全域恰好命中 1 项」（其余变体只需判据本身，用 scan_src 直判）
                with open(dst, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(new_src)
                bad = m.scan(tmp)[0]
                hits = [x for x in bad if x[0].replace("\\", "/") == target]
                assert len(hits) == want and len(bad) == want, \
                    "%s：全域预期 %d 项，实测 %d 项 %s" % (label, want, len(bad), bad)
            else:
                counts2 = {"text_open": 0, "bin_open": 0, "mode_unknown_open": 0,
                           "attr_open": 0, "attr_text_rw": 0}
                bad = []
                m.scan_src(target, new_src, counts2, bad)
                hits = bad
                assert len(hits) == want, "%s：预期 %d 项，实测 %d 项 %s" % (
                    label, want, len(hits), hits)
            if want == 1:
                assert hits[0][1] == expect_line, \
                    "%s：命中行 %d ≠ 注入行 %d" % (label, hits[0][1], expect_line)
            print("③ 定点变异 %-32s 命中 %d 项（期望 %d）" % (label, len(hits), want))

        # ③c 真退出码：完整扫描面临时副本上留一处裸文本 open，走守卫 main() 全路径 → 必须 exit 1
        # （临时面是整仓 .py 的物化副本 ⇒ 扫描面下限锚同样成立，这条路径与真仓运行完全同形）
        new_src, expect_line = m._inject(orig, '    return open(p, "w")')
        with open(dst, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new_src)
        with _Patched(m, ROOT=tmp):
            code, out = run_main(m, [])
        assert code == 1, "新增一处裸文本 open 未转红：exit=%s\n%s" % (code, out)
        assert out.count("未声明 encoding=") == 1, "应恰好报 1 处：\n" + out
        assert "%s:%d" % (target, expect_line) in out, "未点名注入点位：\n" + out
        print("③c 完整扫描面 + 注入一处裸文本 open → 守卫 exit 1（恰好 1 处，行号 %d）" % expect_line)
        # 还原（临时面即将销毁，此处只为语义完整）

    # ---- ③b 真实仓的 89 处二进制 open 对照：不误报 ----
    _bad, counts, _f = m.scan(_REPO)
    assert counts["bin_open"] >= m._FLOORS["bin_open"], \
        "真实仓二进制 open 计数 %d 低于下限——对照面塌陷" % counts["bin_open"]
    assert counts["attr_open"] >= m._FLOORS["attr_open"], \
        "真实仓 Attribute .open 计数 %d 低于下限——对照面塌陷" % counts["attr_open"]
    for rel in m._ATTR_CONTROL_FILES:
        ap = os.path.join(_REPO, rel)
        assert os.path.isfile(ap), "Attribute 对照点位文件不在：" + rel
        c2 = {"text_open": 0, "bin_open": 0, "mode_unknown_open": 0,
              "attr_open": 0, "attr_text_rw": 0}
        b2 = []
        with open(ap, encoding="utf-8", errors="replace") as fh:
            m.scan_src(rel, fh.read(), c2, b2)
        assert c2["attr_open"] >= 1, "%s 已无 Attribute .open（对照点位漂移）" % rel
        assert not b2, "%s 被误报：%s" % (rel, b2)
    print("③b 对照：真实仓二进制 open %d 处 / Attribute .open %d 处，"
          "5 个假阳性点位全部不报" % (counts["bin_open"], counts["attr_open"]))

    # ---- ④ ANCHOR-MISS 四条（退出码必须 2）----
    with _Patched(m, _ANCHOR_CORPUS=m._ANCHOR_CORPUS + (("drift", 'open(p, "w")\n', 0),)):
        code, out = run_main(m, ["--self-test"])
    assert code == 2, "判据锚漂移未报 ANCHOR-MISS：%s%s" % (code, out)
    print("④a 判据锚漂移 → 退出 2")

    with tempfile.TemporaryDirectory(prefix="voe_empty_") as tmp:
        for d in m.SCAN_DIRS:
            os.makedirs(os.path.join(tmp, d), exist_ok=True)
        with _Patched(m, ROOT=tmp):
            code, out = run_main(m, [])
    assert code == 2, "扫描面塌陷未报 ANCHOR-MISS：%s%s" % (code, out)
    print("④b 扫描面下限塌陷 → 退出 2")

    with _Patched(m, _ATTR_CONTROL_FILES=m._ATTR_CONTROL_FILES + ("md_cg/__ghost__.py",)):
        code, out = run_main(m, ["--self-test"])
    assert code == 2, "对照点位漂移未报 ANCHOR-MISS：%s%s" % (code, out)
    print("④c 对照点位消失 → 退出 2")

    with tempfile.TemporaryDirectory(prefix="voe_nodir_") as tmp:
        with _Patched(m, ROOT=tmp):
            code, out = run_main(m, [])
    assert code == 2, "扫描目录缺失未报 ANCHOR-MISS：%s%s" % (code, out)
    print("④d 扫描目录缺失 → 退出 2")

    # ---- ④e 契约点名「点位级」对照锚承重（④c 只钉到文件级）----
    with _Patched(m, _ATTR_CONTROL_POINTS=m._ATTR_CONTROL_POINTS + (("md_cg/fsutil.py", "ghost.open"),)):
        code, out = run_main(m, ["--self-test"])
    assert code == 2, "点位级对照锚漂移未报 ANCHOR-MISS：%s%s" % (code, out)
    assert "对照点位漂移" in out, out
    print("④e 契约点名点位级对照锚漂移 → 退出 2")

    # ---- ⑤ 白名单双向（不得静默豁免）----
    with _Patched(m, WHITELIST={"md_cg/__ghost__.py": "演示陈化豁免"}):
        code, out = run_main(m, [])
    assert code == 1, "白名单不吻合未转红：%s%s" % (code, out)
    assert "有而未命中" in out and "md_cg/__ghost__.py" in out, out
    print("⑤ 白名单双向报出 → 退出 1")

    # ---- ⑥ 白名单现为空（B 项收口口径）----
    assert load_guard().WHITELIST == {}, "白名单必须为空（B 项收口口径）"
    print("ALL PASS test_verify_open_encoding")
    return 0


if __name__ == "__main__":
    sys.exit(main())
