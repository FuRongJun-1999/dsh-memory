# -*- coding: utf-8 -*-
"""守卫 · issue #993：身份档案「查看完整画像」的过期守卫引用了未定义变量。

根因：`execute(button, tool, args, view)` 内为 `self_profile` 绑定点击处理器时，
handler 里写的是 `if(token!==generation)return`——但 `token` 只在
`navigate()` / `overview(token)` / `memory(token)` 的作用域里存在。
`execute` 既没声明它、也没有参数传入 ⇒ 每次点击都抛 ReferenceError，
被外层 catch 当成「读取失败」toast 出去。

修法：进入 try 前先取**模块级** `generation` 的快照，await 之后比快照，
语义不变（等待期间切页则丢弃旧结果）。

本守卫检查 4 份产物（payload 源 2 份 + 仓根产物 2 份）都不再出现
「在 profile 调用之后紧跟 `token!==generation`」这一段。
"""
import io
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = [
    os.path.join("ui", "minimal", "payload", "web", "app.js"),
    os.path.join("ui", "minimal", "payload", "lib", "client.js"),
    os.path.join("web", "app.js"),
    os.path.join("lib", "client.js"),
]

#: 调用点锚（字面或真换行两种形态都认）
CALL_ANCHOR = "action:'profile',subject_id:sid"
BAD = 'if(token!==generation)return'
GOOD = 'if(gen!==generation)return'
SNAP = 'const gen=generation'


def _check(path):
    fp = os.path.join(REPO, path)
    if not os.path.isfile(fp):
        return ('MISSING', path)
    text = io.open(fp, encoding='utf-8', errors='ignore').read()
    i = text.find(CALL_ANCHOR)
    if i < 0:
        return ('NOANCHOR', path)
    tail = text[i:i + 400]
    head = text[max(0, i - 400):i]
    if BAD in tail:
        return ('BAD', path)
    if GOOD not in tail:
        return ('NOGOOD', path)
    if SNAP not in head:
        return ('NOSNAP', path)
    return ('OK', path)


def main():
    bad = []
    for t in TARGETS:
        state, path = _check(t)
        print('  %-6s %s' % (state, path))
        if state not in ('OK', 'MISSING'):
            bad.append((state, path))
    print()
    print('issue #993 守卫：%d 目标，异常 %d' % (len(TARGETS), len(bad)))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())