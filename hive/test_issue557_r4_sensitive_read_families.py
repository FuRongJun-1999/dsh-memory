# -*- coding: utf-8 -*-
# 功能名：hive 凭据文件黑名单的族覆盖（issue #557 R4 / #95 追评）
# 生效条件：python -u -X utf8 -m hive.test_issue557_r4_sensitive_read_families；被测面＝hive/exec._sensitive_read
# 子功能：A 组＝新增族必须命中；K 组＝常见合法文件不得误命中
# 执行：直接调 _sensitive_read(绝对路径) 判返回值真值
# 验证方式：全部 PASS 即通过（退出码 0）
# 不适用条件：不判「黑名单是否穷尽所有凭据形态」（黑名单天生会漏，见源码注释）
import sys

from . import exec as _ex

PASS = 0
FAIL = 0
FAILS = []


def ok(cond, title, detail=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print('  PASS %s' % title)
    else:
        FAIL += 1
        FAILS.append(title)
        print('  FAIL %s  <- %r' % (title, detail))


print('== A 组：新增族必须命中 ==')
HIT = [
    ('/home/u/.config/gh/hosts.yml', 'gh CLI token'),
    ('/app/secrets.yaml', 'k8s secrets'),
    ('/app/secrets.json', 'compose secrets'),
    ('/home/u/.terraformrc', 'terraform 凭据'),
    ('/home/u/app.jks', 'Java keystore'),
    ('/home/u/app.keystore', 'Java keystore'),
    ('/home/u/client.ovpn', 'OpenVPN 内联私钥'),
    ('/home/u/old.kdb', 'KeePass 旧版'),
    ('/infra/terraform.tfstate', 'terraform state'),
]
for path, label in HIT:
    why = _ex._sensitive_read(path)
    ok(bool(why), 'A %-18s %s' % (label, path.rsplit('/', 1)[-1]), why)

print('== K 组：常见合法文件不得误命中 ==')
CLEAN = ['/home/u/project/README.md', '/home/u/project/config.yaml',
         '/home/u/src/main.py', '/home/u/project/notes.txt']
for path in CLEAN:
    why = _ex._sensitive_read(path)
    ok(why is None, 'K %-24s' % path.rsplit('/', 1)[-1], why)

print('')
print('=' * 56)
print('通过 %d / 失败 %d' % (PASS, FAIL))
for f in FAILS:
    print('  - %s' % f)
sys.exit(0 if FAIL == 0 else 1)