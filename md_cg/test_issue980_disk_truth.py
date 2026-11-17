# -*- coding: utf-8 -*-
"""守卫 · 判定面以磁盘为真源（issue #980 问题 2，2026-11-17）。

病象：手改 .md 后 `read` 认新值，`protect.check` 还报旧值——两处不同源。
根因：`_fm` 只读 `cg.index`（内存快照），回退读文件的分支因「键恒存在」从不触发。

修：判定面加 **mtime 级**新鲜度判定——文件比索引新就读盘（每节点一次 stat，微秒级）。

  D1 手改文件后，is_protected 立即认新值
  D2 未改动的节点仍走索引（不额外读盘）
  D3 protect.check 返回 source=file / as_of / index_mismatch
"""
import io
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import mcp_server, protect  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def main():
    T = tempfile.mkdtemp(prefix='disktruth_')
    try:
        cg = MdCGOS(T, actor='t')
        for i in range(2):
            cg.add('n%d' % i, '# 功能名：n%d\n\n正文' % i, layer='knowledge', importance=0.9)
        path = None
        for dp, _, fs in os.walk(T):
            if 'n0.md' in fs:
                path = os.path.join(dp, 'n0.md')
        before = protect.is_protected(cg, 'n0')
        ok(before[0] is True, 'D0 改前：按分受保护', before)

        # 同时把显式保护位撤掉——只改分数不改位，节点仍受保护（那是正确行为）
        txt = (io.open(path, encoding='utf-8').read()
               .replace('importance: 0.9', 'importance: 0.25')
               .replace('protected: true', 'protected: false'))
        io.open(path, 'w', encoding='utf-8', newline='').write(txt)
        after = protect.is_protected(cg, 'n0', fresh=True)   # 单节点判定＝读盘（check 走这条）
        ok(after[0] is False, 'D1 手改文件后判定立即认新值（不再读陈旧索引）', after)
        other = protect.is_protected(cg, 'n1')
        ok(other[0] is True, 'D2 未改动节点仍按索引判（不误伤）', other)

        r = mcp_server.call_tool(cg, 'cg', {'op': 'protect', 'action': 'check', 'node_id': 'n0'})
        ok((r or {}).get('source') == 'file', 'D3a 返回体标明数据来源 = file', (r or {}).get('source'))
        ok(isinstance((r or {}).get('as_of'), int), 'D3b 带 as_of 时间戳', (r or {}).get('as_of'))
        ok((r or {}).get('index_mismatch') is True, 'D3c 索引与磁盘分歧被点名',
           ((r or {}).get('index_importance'), (r or {}).get('file_importance')))
    finally:
        shutil.rmtree(T, ignore_errors=True)

    print()
    print('磁盘真源守卫：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())