#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_check_push_scope —— check_push_scope 判据守卫（合成仓 + 定点变异自证）

为什么要有它
    check_push_scope 的判据面是「共享检出里 push 会带上哪些提交」。若守卫只断言
    「脚本能跑、不抛异常」，那么「只数总量不逐笔」「退出码恒 0」「标记检测失效」三种
    退化都能静默通过——正是本判据要防的形态。故本守卫用**合成 git 仓**（tempfile 内
    git init，跑完即删）喂给被测实现，断言其**逐笔清单 / 标记 / 退出码**三段，并用
    --mutate 把修复点逐条改回退化形态，要求断言组**按预期点名转红**。

守卫断言（行为断言：合成仓喂给被测实现，读其 stdout/JSON 与退出码；不做源码文本匹配）
  S1 单笔可推：清单恰 1 笔；逐笔 sha == 真实 sha；退出码 = 1（fail-closed）；
               归属标注 mine == True（作者 == 仓内 user.email）
  S2 三笔（其一带「待裁定」）：清单恰 3 笔；sha 集合 == 真实 3 个 sha；
               恰 1 笔带标记；退出码 = 3（搭车高风险）
  S3 同步态（本地 == 远端）：清单 0 笔；退出码 = 0
  S4 非 git 目录：退出码 = 2
  S5 remote 不存在：退出码 = 2
  S6 --json 形状：ok / base_ref / ahead / commits / dirty / exit_code / exit_meaning 齐备，
               且 exit_code 与进程退出码一致、commits 逐笔含 markers/mine/on_first_parent
  S7 只读性：跑完（不带 --fetch）合成仓 HEAD / 全部 ref / 工作树 porcelain 逐字未变

用法
  python -X utf8 scripts/test_check_push_scope.py              # 测工作树版
  python -X utf8 scripts/test_check_push_scope.py --impl <path>
  python -X utf8 scripts/test_check_push_scope.py --mutate     # 定点变异自证
退出码：0 = 全部按预期；1 = 有断言失败 / 变异未按预期转红；2 = 变异锚点失配。
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_IMPL = os.path.join(HERE, "check_push_scope.py")

_N_S1_1 = "S1 单笔：清单恰 1 笔"
_N_S1_2 = "S1 单笔：逐笔 sha == 真实 sha"
_N_S1_3 = "S1 单笔：退出码 = 1（有可推须逐笔确认）"
_N_S1_4 = "S1 单笔：归属标注 mine == True"
_N_S2_1 = "S2 三笔：清单恰 3 笔"
_N_S2_2 = "S2 三笔：sha 集合 == 真实 3 个 sha"
_N_S2_3 = "S2 三笔：恰 1 笔带待裁定标记"
_N_S2_4 = "S2 三笔：退出码 = 3（含待裁定，搭车高风险）"
_N_S3_1 = "S3 同步态：清单 0 笔"
_N_S3_2 = "S3 同步态：退出码 = 0"
_N_S4_1 = "S4 非 git 目录：退出码 = 2"
_N_S5_1 = "S5 remote 不存在：退出码 = 2"
_N_S6_1 = "S6 --json：必需键齐备"
_N_S6_2 = "S6 --json：exit_code 与进程退出码一致且 commits 逐笔含三标注"
_N_S7_1 = "S7 只读性：HEAD/refs/porcelain 逐字未变"

_RESULTS = []


def _check(name, ok, detail=""):
    _RESULTS.append((name, bool(ok), detail))
    print("  %s %s%s" % ("[green]" if ok else "[RED ]", name,
                         ("  —— " + detail) if (not ok and detail) else ""))


def _skip(name, why):
    _RESULTS.append((name, True, "SKIP: " + why))
    print("  [skip ] %s  —— %s" % (name, why))


def _git(cwd, args):
    return subprocess.run(["git", "-C", cwd] + list(args), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=120)


def _mk_repo(tmp):
    """合成：bare origin.git + 工作仓 repo（main 首次提交并 push 建立基线）。"""
    root = os.path.join(tmp, "repo")
    bare = os.path.join(tmp, "origin.git")
    os.makedirs(root)
    r = subprocess.run(["git", "init", "--bare", "-b", "main", bare],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        subprocess.run(["git", "init", "--bare", bare], capture_output=True)
        subprocess.run(["git", "-C", bare, "symbolic-ref", "HEAD", "refs/heads/main"],
                       capture_output=True)
    r = subprocess.run(["git", "init", "-b", "main", root], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        subprocess.run(["git", "init", root], capture_output=True)
        _git(root, ["symbolic-ref", "HEAD", "refs/heads/main"])
    _git(root, ["config", "user.email", "guard@example.com"])
    _git(root, ["config", "user.name", "Guard"])
    _git(root, ["config", "commit.gpgsign", "false"])
    _git(root, ["remote", "add", "origin", bare.replace("\\", "/")])
    _commit(root, "base.txt", "chore: base")
    _git(root, ["push", "-q", "-u", "origin", "main"])
    return root, bare


def _commit(root, name, msg):
    with open(os.path.join(root, name), "a", encoding="utf-8") as fh:
        fh.write(msg + "\n")
    _git(root, ["add", "-A"])
    _git(root, ["commit", "-q", "-m", msg])
    return _git(root, ["rev-parse", "HEAD"]).stdout.strip()


def _run(impl, repo, *args):
    return subprocess.run([sys.executable, "-B", "-X", "utf8", impl, "--repo", repo]
                          + list(args), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300)


def _json_of(res):
    try:
        return json.loads(res.stdout)
    except Exception:
        return None


def _snapshot(root):
    return (_git(root, ["rev-parse", "HEAD"]).stdout.strip(),
            _git(root, ["for-each-ref", "--format=%(refname):%(objectname)"]).stdout.strip(),
            _git(root, ["status", "--porcelain"]).stdout.strip())


def _case_synced(impl, root):
    res = _run(impl, root)
    payload = _json_of(_run(impl, root, "--json"))
    n = len((payload or {}).get("commits") or [])
    _check(_N_S3_1, n == 0, "json.commits=%r rc=%s" % (n, res.returncode))
    _check(_N_S3_2, res.returncode == 0, "rc=%s ｜ %s" % (res.returncode, res.stdout.strip()[:200]))
    return payload


def _case_single(impl, root, sha1):
    res = _run(impl, root, "--json")
    payload = _json_of(res) or {}
    commits = payload.get("commits") or []
    _check(_N_S1_1, len(commits) == 1, "commits=%r" % ([c.get("short") for c in commits],))
    _check(_N_S1_2, [c.get("sha") for c in commits] == [sha1],
           "got=%r want=%r" % ([c.get("sha") for c in commits], [sha1]))
    _check(_N_S1_3, res.returncode == 1, "rc=%s" % res.returncode)
    _check(_N_S1_4, bool(commits) and commits[0].get("mine") is True,
           "mine=%r" % (commits[0].get("mine") if commits else None,))


def _case_multi(impl, root, shas):
    res = _run(impl, root, "--json")
    payload = _json_of(res) or {}
    commits = payload.get("commits") or []
    _check(_N_S2_1, len(commits) == 3, "n=%d shorts=%r" % (len(commits), [c.get("short") for c in commits]))
    _check(_N_S2_2, sorted(c.get("sha") for c in commits) == sorted(shas),
           "got=%r want=%r" % (sorted(c.get("sha") for c in commits), sorted(shas)))
    marked = [c for c in commits if c.get("markers")]
    _check(_N_S2_3, len(marked) == 1,
           "marked=%r" % ([(c.get("short"), c.get("markers")) for c in marked],))
    _check(_N_S2_4, res.returncode == 3, "rc=%s" % res.returncode)
    return payload


def _case_json_shape(payload, rc):
    need = ("ok", "base_ref", "ahead", "commits", "dirty", "exit_code", "exit_meaning")
    missing = [k for k in need if k not in (payload or {})]
    _check(_N_S6_1, not missing, "missing=%r" % (missing,))
    ok2 = False
    if payload:
        per = payload.get("commits") or []
        ok2 = (payload.get("exit_code") == rc
               and all(("markers" in c and "mine" in c and "on_first_parent" in c) for c in per))
    _check(_N_S6_2, ok2, "exit_code=%r rc=%s" % ((payload or {}).get("exit_code"), rc))


def _case_bad_repo(impl, tmp):
    notgit = os.path.join(tmp, "notgit")
    os.makedirs(notgit, exist_ok=True)
    res = _run(impl, notgit)
    _check(_N_S4_1, res.returncode == 2, "rc=%s err=%s" % (res.returncode, res.stderr.strip()[:150]))


def _case_bad_remote(impl, root):
    res = _run(impl, root, "--remote", "nope")
    _check(_N_S5_1, res.returncode == 2, "rc=%s err=%s" % (res.returncode, res.stderr.strip()[:150]))


def _scenarios(impl, tmp):
    """顺序跑 S3→S1→S6→S2→S7→S4→S5（同一合成仓按阶段推进）。"""
    root, _bare = _mk_repo(tmp)
    _case_synced(impl, root)
    sha1 = _commit(root, "one.txt", "feat: 单笔产出")
    _case_single(impl, root, sha1)
    _case_json_shape(_json_of(_run(impl, root, "--json")), 1)
    sha2 = _commit(root, "two.txt", "feat: 第二笔")
    sha3 = _commit(root, "three.txt", "wip: 待裁定 第三笔勿推")
    _case_multi(impl, root, [sha1, sha2, sha3])
    before = _snapshot(root)
    _run(impl, root)          # 不带 --fetch ⇒ 必须零写
    after = _snapshot(root)
    _check(_N_S7_1, before == after, "before=%r after=%r" % (before, after))
    _case_bad_repo(impl, tmp)
    _case_bad_remote(impl, root)


# ---- 定点变异自证 ----------------------------------------------------------
_MUTATIONS = [
    ("M1 逐笔清单退化为「只数总量」",
     "        commits.append(_describe(sha, short, an, ae, adate, subj, body, plist,\n"
     "                                 first_parent, me))",
     "        commits.append({\"sha\": \"?\", \"short\": \"?\", \"author\": \"\", \"email\": \"\","
     " \"date\": \"\", \"subject\": \"[只数总量]\", \"markers\": sorted({m.group(0) for m in"
     " MARKER_RE.finditer(subj)}), \"mine\": False, \"on_first_parent\": False,"
     " \"parents\": [], \"merge\": False})",
     [_N_S1_2, _N_S1_4, _N_S2_2]),
    ("M2 退出码恒 0（静默安全）",
     "    if not commits:\n        return EXIT_OK\n"
     "    if any(c[\"markers\"] for c in commits):\n        return EXIT_TAINTED\n"
     "    return EXIT_REVIEW",
     "    return EXIT_OK",
     [_N_S1_3, _N_S2_4, _N_S6_2]),
    ("M3 标记检测恒不命中",
     "MARKER_RE = re.compile(\n"
     "    r\"(待裁定|待裁|未决|未推送|未提交|暂缓|挂起|待定|\"\n"
     "    r\"DO[ _-]?NOT[ _-]?MERGE|DONTMERGE|WIP\\b|HOLD\\b)\", re.I)",
     "MARKER_RE = re.compile(r\"(?!x)x\")",
     [_N_S2_3, _N_S2_4]),
]


def _read_norm(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read().replace("\r\n", "\n")


def _write_norm(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _mutate_mode(tmp):
    """逐个变异点：改回退化形态 → 断言组必须按预期点名转红。"""
    print("!! 定点变异自证：逐条把修复点改回退化形态，断言组必须按预期点名转红\n")
    src = _read_norm(DEFAULT_IMPL)
    anchor_bad = 0
    for idx, (label, old, new, expect) in enumerate(_MUTATIONS):
        hits = src.count(old)
        if hits != 1:
            print("  [锚点失配] %s：锚点命中 %d 次（要求恰 1 次）" % (label, hits))
            anchor_bad = 2
            continue
        mut = os.path.join(tmp, "mut_%d.py" % idx)
        _write_norm(mut, src.replace(old, new))
        keep = list(_RESULTS)
        del _RESULTS[:]
        sub = os.path.join(tmp, "mut_%d_case" % idx)
        os.makedirs(sub, exist_ok=True)
        try:
            _scenarios(mut, sub)
        except Exception as exc:
            _check("变异 %s：场景执行异常" % label, False, "%s: %s" % (type(exc).__name__, exc))
        reds = {n for n, ok, _d in _RESULTS if not ok}
        del _RESULTS[:]
        _RESULTS[:] = keep
        if reds == set(expect):
            print("  [green] %s —— 恰按 %d 条点名转红：%s" % (label, len(reds), sorted(reds)))
        else:
            print("  [RED ] %s —— 转红集合不符：多红 %r / 少红 %r"
                  % (label, sorted(reds - set(expect)), sorted(set(expect) - reds)))
            _check("变异 %s 按预期点名转红" % label, False,
                   "多红 %r / 少红 %r" % (sorted(reds - set(expect)), sorted(set(expect) - reds)))
    if anchor_bad:
        return anchor_bad
    return 0 if all(ok for _n, ok, _d in _RESULTS) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="check_push_scope 判据守卫（合成仓 + 定点变异）")
    ap.add_argument("--impl", default=DEFAULT_IMPL, help="被测实现路径（默认工作树版）")
    ap.add_argument("--mutate", action="store_true", help="定点变异自证")
    args = ap.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="cps_guard_") as tmp:
        if args.mutate:
            rc = _mutate_mode(tmp)
        else:
            print("== check_push_scope 判据守卫（合成仓，tempfile 内 git init）==\n")
            _scenarios(args.impl, tmp)
            print("")
            n_red = sum(1 for _n, ok, _d in _RESULTS if not ok)
            print("通过 %d / 失败 %d" % (len(_RESULTS) - n_red, n_red))
            rc = 1 if n_red else 0
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
