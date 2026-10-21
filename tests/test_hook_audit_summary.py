# -*- coding: utf-8 -*-
"""#606 摘要守卫与定点变异。作者：fladyck。

python -X utf8 tests/test_hook_audit_summary.py
python -X utf8 tests/test_hook_audit_summary.py --mutate
依赖：npm ci --ignore-scripts --include=dev；Node >=22.19。
每臂期望红项预先写死；变异源文件在 finally 中按原始字节恢复。
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / 'src' / 'hooks.ts'
AUDIT = ROOT / 'src' / 'lib' / 'hook_audit.ts'
INDEX = ROOT / 'src' / 'index.ts'
UNIT = 'test/hook_audit_summary.test.ts'
HOST = 'test/host.test.ts'

# 预注册：单臂只跑对应回归面，失败集合必须恰好相等；不接受语法/导入错误。
ARMS = [
    ('M1', HOOKS, '      if (summary) ctx.logger.info(summary)',
     '      if (false) ctx.logger.info(summary)', UNIT,
     {'S1', 'S2', 'S5', 'S7'}),
    ('M2', HOOKS, '    if (reported) return',
     '    if (false) return', UNIT, {'S1'}),
    ('M3', AUDIT, " || value < 0", '', UNIT, {'S3 坏计数安静降级：负数'}),
    ('M4', HOOKS, '      if (summary) ctx.logger.info(summary)',
     '      if (summary) ctx.logger.info(summary + JSON.stringify({ last: \"PRIVATE_BODY_SENTINEL\" }))',
     UNIT, {'S1', 'S2', 'S5', 'S7'}),
    ('M5', INDEX, '    disposers.push(installMemoryHooks(ctx, mdcg, config.memory))',
     '    installMemoryHooks(ctx, mdcg, config.memory)', HOST, {'S8'}),
]


def run(file: str) -> tuple[int, set[str], str]:
    node = shutil.which('node')
    if node is None:
        raise RuntimeError('未找到 Node；请先安装项目声明的 Node 版本')
    cmd = [node, '--import', 'tsx', '--test', '--test-reporter=tap']
    if file == HOST:
        cmd.append('--test-name-pattern=^S8 ')
    cmd.append(file)
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=90)
    output = proc.stdout + proc.stderr
    names = set(re.findall(r'^not ok [0-9]+ - (.+)$', output, re.MULTILINE))
    red = {name if name.startswith('S3 ') else name.split(' ', 1)[0] for name in names}
    return proc.returncode, red, output


def main() -> int:
    if sys.argv[1:] not in ([], ['--mutate']):
        print(__doc__)
        return 2
    for file in (UNIT, HOST):
        rc, red, output = run(file)
        if rc != 0:
            print(output)
            print('BASE-FAIL', file, sorted(red))
            return 1
        passed = re.search(r'^# pass ([0-9]+)$', output, re.MULTILINE)
        if not passed or int(passed.group(1)) == 0:
            print('BASE-FAIL 无实际通过项', file)
            return 1
        print('BASE-PASS', file, 'pass=' + passed.group(1))
    if '--mutate' not in sys.argv:
        return 0
    for mid, file, old, new, target, expected in ARMS:
        original = file.read_bytes()
        source = original.decode('utf-8')
        if source.count(old) != 1:
            print('ANCHOR-MISS', mid, 'count=' + str(source.count(old)))
            return 2
        try:
            file.write_bytes(source.replace(old, new).encode('utf-8'))
            rc, actual, output = run(target)
        finally:
            file.write_bytes(original)
        if file.read_bytes() != original:
            raise RuntimeError('变异后源文件未按原始字节恢复：' + str(file.relative_to(ROOT)))
        errors = ('SyntaxError', 'TransformError', 'ERR_MODULE_NOT_FOUND',
                  'ERR_SYSTEM_ERROR', 'ERR_UNKNOWN_FILE_EXTENSION')
        exact = rc == 1 and actual == expected and not any(e in output for e in errors)
        print(mid, json.dumps({'rc': rc, 'red': sorted(actual),
                              'expected': sorted(expected), 'exact': exact}, ensure_ascii=False))
        if not exact:
            print(output)
            return 1
    print('MUTATE-PASS 5/5；源文件原始字节均已恢复')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
