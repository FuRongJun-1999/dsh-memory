#!/usr/bin/env bash
# 批次 33：Linux node 面验证——npm ci(匿名卷) + build + ts test。
# N254（2026-10-05）：本脚本此前只有 set -u、三段只 echo 退出码、末句是 tail → 进程退出码
# **恒 0**；消费退出码的宿主（docker run … && 下一步）把 ci=1/build=1/test=1 的全失败读成
# 「成功」。现复用同目录 scripts/linux_verify.sh:12-15 的既有单点 record，末行以
# `[ "$fail" -eq 0 ]` 传播（与 scripts/linux_verify.sh:129 同一判据）。
set -u
cd /work
pass=0; fail=0
note() { echo "[$1] $2"; }
record() { # record <label> <exit>
  if [ "$2" -eq 0 ]; then pass=$((pass+1)); note "PASS" "$1"; else fail=$((fail+1)); note "FAIL" "$1"; fi
}
node --version
npm ci --no-audit --no-fund >/dev/null 2>&1;              record "npm ci" $?
npm run build >/dev/null 2>&1;                            record "npm run build" $?
node --import tsx --test test/*.test.ts >/tmp/ts_test.log 2>&1
record "ts test (node --import tsx --test)" $?
tail -6 /tmp/ts_test.log

echo "=== 汇总: $pass pass / $fail fail ==="
[ "$fail" -eq 0 ]
