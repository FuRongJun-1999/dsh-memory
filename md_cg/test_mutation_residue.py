# -*- coding: utf-8 -*-
# 功能名：变异残留预检——in-place 定点变异工装被强杀后，工作树残留的「变异态源码」必须变成响亮的信号（issue #353）
# 生效条件：python -X utf8 -m md_cg.test_mutation_residue；全仓扫描带 --mutate 的守卫，抽取其 _MUTATIONS 里的「变异态」字符串，断言它不在对应生产源里
# 子功能：① AST + 受限求值抽取变异态串（chr/常量/拼接）② 判据=「变异态在盘 且 改动前形态不在盘」（两者同在=锚点歧义，跳过不判，防误报）③ 命中即列出文件/行并 rc=1
# 执行：无需参数；被 run_tests.py 收集。in-place 守卫被强杀后，本守卫在下一次普通跑就把残留变成响亮失败
# 验证方式：全绿 = 无残留；命中时输出「疑似残留」与修法提示（git checkout -- <file>）
# 不适用条件：不修任何 in-place 工装本体（124 个文件迁移 + 共享 helper 是设计决定，归维护者）；变异态串静态求值取不到时跳过（覆盖缺口如实计数，不误报）；不判 CI 是否跑 --mutate
"""issue #353 守卫：变异残留从「静默假红」变成「响亮失败」。

病象：本仓约 125 个守卫带 --mutate 定点变异自证，其中约 113 个的形态是
「io.open(生产源, 'w').write(变异) → 跑守卫 → finally 还原」。finally 只防得住
异常与 SIGINT；SIGKILL（进程树强杀 / OOM / 断电）绕过 finally ⇒ 工作树停留在
变异态且没有任何一处记录这件事，之后在这棵树上跑的每个守卫都把残留当成
产品回归报假红（红项措辞与真缺陷完全同形）。

判据方向：**变异态字符串在盘 且 改动前形态不在盘** 才判残留——两者同在视为
锚点歧义（同一片段在别处合法出现），跳过不判。只判「变异态在盘」会把
`return False` / 裸括号这类通用片段误报成残留（项目方首版实测 5/5 全误报）。
本守卫不改任何 in-place 工装本体。
"""
import ast
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "target", "lib"}
_MIN_LEN = 20          # 短于此的变异态串不判（太通用，误报面大）
_SELF = os.path.basename(os.path.abspath(__file__))
FAILS = []


def _eval_str(node):
    """把 AST 表达式安全求值成字符串：字面量直取；拼接/chr() 用受限名字空间。
    取不到返回 None（覆盖缺口如实跳过，不误报）。"""
    try:
        v = ast.literal_eval(node)
        return v if isinstance(v, str) else None
    except Exception:
        pass
    try:
        code = compile(ast.Expression(node), "<mut>", "eval")
        v = eval(code, {"__builtins__": {}}, {"chr": chr})
        return v if isinstance(v, str) else None
    except Exception:
        return None


def _guard_files():
    out = []
    for dirpath, dd, ff in os.walk(_REPO):
        dd[:] = [d for d in dd if d not in _SKIP_DIRS]
        for fn in ff:
            if fn.startswith("test_") and fn.endswith(".py") and fn != _SELF:
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def _extract(node):
    out = []
    for el in getattr(node, "elts", []):
        if not isinstance(el, ast.Tuple) or len(el.elts) < 4:
            continue
        rel = _eval_str(el.elts[1])
        old = _eval_str(el.elts[2])
        new = _eval_str(el.elts[3])
        if rel and new and rel.endswith(".py") and len(new) >= _MIN_LEN:
            out.append((rel, old, new))
    return out


print("== 变异残留预检（issue #353）==")
_guards = [p for p in _guard_files()
           if "--mutate" in (open(p, encoding="utf-8").read())]
_checked = _ambiguous = 0
_hits = []
for p in _guards:
    try:
        tree = ast.parse(open(p, encoding="utf-8").read())
    except Exception:
        continue
    pairs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and "MUTATION" in t.id.upper()
                for t in node.targets):
            pairs.extend(_extract(node.value))
    if not pairs:
        continue
    rel_g = os.path.relpath(p, _REPO).replace(chr(92), "/")
    for rel, old, new in pairs:
        tp = os.path.join(_REPO, rel.replace("/", os.sep))
        try:
            cur = open(tp, encoding="utf-8").read()
        except OSError:
            continue
        _checked += 1
        if new in cur and (old or "") not in cur:
            line = cur[:cur.index(new)].count(chr(10)) + 1
            _hits.append((rel, rel_g, line, new))
        elif new in cur:
            _ambiguous += 1   # 变异态与改动前形态同时在盘 ⇒ 锚点歧义，不判

print("  盘点：带 --mutate 守卫 %d ｜ 变异态判据 %d 条 ｜ 锚点歧义跳过 %d 条"
      % (len(_guards), _checked, _ambiguous))
if _hits:
    print("  !! 疑似残留变异：上一次 --mutate 未还干净，git checkout -- 下列文件即可")
    for rel, rel_g, line, new in _hits[:20]:
        print("    残留 %s:%d（来自守卫 %s）  变异态=%r"
              % (rel, line, rel_g, new[:70]))
    FAILS.append("残留 %d 处" % len(_hits))
else:
    print("  PASS 无变异残留（in-place 工装的变异态串都不在盘上源里）")

print("")
if FAILS:
    print("issue #353 结果：%s" % "；".join(FAILS))
    sys.exit(1)
print("issue #353 结果：全部通过")