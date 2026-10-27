# -*- coding: utf-8 -*-
# 功能名：UI 接线纳入仓库的守卫（声明面随仓库 package.json，产物面由 scripts/build_ui.py 铺）
# 生效条件：python -X utf8 -m md_cg.test_ui_wiring_in_repo；被测面＝仓库 package.json 的 dsh.client / exports["./client"] / files / scripts，与 scripts/build_ui.py 的幂等与 --check 语义
# 子功能：①声明面齐全（platform=web + 三个 inject、exports 指向 lib/client.js）②分发面齐全（files 含 ui/web/CHANGELOG）③构建面接线（build 与 prepublishOnly 都含 build_ui）④build_ui 幂等⑤--check 两态⑥与最终用户安装器口径一致
# 执行：读 package.json 断言 → 临时目录跑 build() 两次断言幂等 → --check 两态 → install.ps1 源码锚点
# 验证方式：全部 PASS exit 0，否则 exit 1
# 不适用条件：不判 DSH 是否真的加载 client bundle（宿主面需重启目视）；不判 payload 与产物字节一致（由 build_ui --check 承接）
"""UI 接线纳入仓库的守卫（2026-10-27 使用者裁定）。"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

_PASS, _FAIL = [], []


def ok(cond, msg, detail=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg + (("  <- " + str(detail)) if detail and not cond else ""))


def main():
    pkg = json.load(open(os.path.join(ROOT, "package.json"), encoding="utf-8"))

    print("== A 声明面（随仓库提供，不再靠安装器注入）")
    cl = (pkg.get("dsh") or {}).get("client") or {}
    ok(cl.get("platform") == "web", "A1 dsh.client.platform == web", cl.get("platform"))
    ok(cl.get("immediately") is True, "A2 dsh.client.immediately == true")
    want = {"@deepseek-ai/dsh-client-ui-renderer",
            "@deepseek-ai/dsh-client-ui-layout",
            "@deepseek-ai/dsh-client-ui-sidebar"}
    ok(set(cl.get("inject") or []) == want,
       "A3 inject 三项齐全（renderer/layout/sidebar）", cl.get("inject"))
    ok((pkg.get("exports") or {}).get("./client") == "./lib/client.js",
       "A4 exports 的 ./client 指向 lib/client.js",
       (pkg.get("exports") or {}).get("./client"))

    ts = open(os.path.join(ROOT, "src", "index.ts"), encoding="utf-8").read()
    ok("installConsoleWeb" in ts,
       "A5 接线写在**源** src/index.ts（重新 build 不会丢）")
    ok(ts.count("installConsoleWeb") >= 2,
       "A6 import 与调用都在位", ts.count("installConsoleWeb"))

    print("== B 分发面（npm 包要带上安装器与静态资源）")
    files = pkg.get("files") or []
    for item in ("ui", "web", "CHANGELOG.md"):
        ok(item in files, "B1 files 含 " + item, files[-6:])

    print("== B2 跨面一致性（2026-10-27 双单元复核指出的系统性漏项）")
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import workspace_index
    root_files = set(getattr(workspace_index, "ROOT_FILES", {}) or {})
    top_level = [f for f in files if "/" not in str(f) and not str(f).startswith(".")]
    top_files = [f for f in top_level
                 if os.path.isfile(os.path.join(ROOT, str(f)))]   # 只查文件；目录归 DIR_ROLES
    missing_reg = [f for f in top_files if f not in root_files]
    ok(not missing_reg,
       "B2a package.json::files 的根级项都在 workspace_index.ROOT_FILES 登记",
       ("未登记：", missing_reg))
    ok("CHANGELOG.md" in root_files,
       "B2b CHANGELOG.md 已登记工作区结构面（本 PR 曾因此双红）")

    print("== C 构建面（产物由脚本生成，构建链自动带）")
    scr = pkg.get("scripts") or {}
    ok("build_ui.py" in str(scr.get("build", "")),
       "C1 build 链末尾包含 build_ui", scr.get("build"))
    ok("build_ui.py" in str(scr.get("prepublishOnly", "")),
       "C2 prepublishOnly 包含 build_ui（发布前必生成）", scr.get("prepublishOnly"))
    ok(os.path.exists(os.path.join(ROOT, "scripts", "build_ui.py")),
       "C3 scripts/build_ui.py 存在")

    print("== D 幂等与 --check 语义（临时目录，不污染仓库）")
    import build_ui
    tmp = tempfile.mkdtemp(prefix="uiwire_")
    r1 = build_ui.build(root=tmp)
    ok(r1.get("error") is None and r1["written"],
       "D1 首次铺文件成功", r1.get("error") or len(r1["written"]))
    r2 = build_ui.build(root=tmp)
    ok(r2["written"] == [] and r2["skipped"],
       "D2 幂等：第二次零写入、全部跳过",
       ("写入", len(r2["written"]), "跳过", len(r2["skipped"])))
    rc1 = build_ui.main(["--root", tmp, "--check"])
    ok(rc1 == 0, "D3 --check 对已同步树返回 0", rc1)
    victim = os.path.join(tmp, "web", "index.html")
    if os.path.exists(victim):
        os.remove(victim)
    rc2 = build_ui.main(["--root", tmp, "--check"])
    ok(rc2 == 1, "D4 --check 发现缺文件返回 1（fail-closed）", rc2)
    shutil.rmtree(tmp, ignore_errors=True)

    print("== E 与最终用户安装器的口径一致")
    inst = os.path.join(ROOT, "ui", "minimal", "install.ps1")
    src = open(inst, encoding="utf-8", errors="replace").read() if os.path.exists(inst) else ""
    ok("./lib/client.js" in src,
       "E1 install.ps1 注入目标与仓库声明一致（./lib/client.js）")
    ok("pkg.dsh" in src and "client" in src,
       "E2 install.ps1 仍可为无接线的旧插件包补齐（面向最终用户）")

    print()
    print("UI 接线纳入仓库守卫：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("  -", f)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())