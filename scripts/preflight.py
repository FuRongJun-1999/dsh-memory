# -*- coding: utf-8 -*-
"""提交前一次过（2026-11-17）：把「每次都忘」的四道门禁收成一条命令。

起因：cogmap 行锚点漂移、新环境变量未登记、UI 产物过期、本机路径入追踪面——
这四类问题反复在 CI 才暴露，每次都是我「记住了但没跑」。
与其记，不如把它做成一个脚本，**提交前跑一次**：

    python -X utf8 scripts/preflight.py

行为：只检查不修改（cogmap 用 check 模式）；有任何 FAIL 即非零退出，并打印修复命令。
"""
import subprocess
import sys

REPO = __file__.rsplit('scripts', 1)[0].rstrip('\\/')

CHECKS = [
    ('认知图行锚点', ['scripts/cogmap_sync.py', 'check'],
     'python -X utf8 scripts/cogmap_sync.py build'),
    ('配置登记面', ['scripts/check_config_env_registry.py'],
     '在 config_registry_bulk.py 补登记后跑 scripts/gen_config_registry.py'),
    ('UI 产物新鲜度', ['scripts/build_ui.py', '--check'],
     'node build-ui.mjs && python -X utf8 scripts/build_ui.py'),
    ('本机路径', ['scripts/check_local_paths.py'],
     '改为相对路径或中性占位（<仓根> / %TEMP%）'),
    ('工作区索引', ['scripts/workspace_index.py', '--check'],
     'python -X utf8 scripts/workspace_index.py --write'),
]


def main():
    failed = []
    for name, args, fix in CHECKS:
        r = subprocess.run([sys.executable, '-X', 'utf8'] + args, cwd=REPO,
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        ok = r.returncode == 0
        print(('  PASS ' if ok else '  FAIL ') + name)
        if not ok:
            failed.append((name, fix, (r.stdout or r.stderr or '').strip().splitlines()[-1:]))
    print()
    if failed:
        for name, fix, tail in failed:
            print('FAIL ' + name + ' ⇒ ' + fix)
            for line in tail:
                print('     ' + line[:160])
        print()
        print('提交前检查：%d 项未过' % len(failed))
        return 1
    print('提交前检查：全过（可以直接提交）')
    return 0


if __name__ == '__main__':
    sys.exit(main())