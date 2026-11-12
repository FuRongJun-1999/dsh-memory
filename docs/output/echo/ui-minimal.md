# echo 页：极简前端增量包（ui/minimal）

版本锚: 理论=v1.1，架构=v0.9.14，本投影=v0.9.14

## 1 解决什么问题

想有界面又不想装整套 Web 的人，只能在终端敲命令。

## 2 凭什么可信

check_publish_artifact 的 R4 拦打包越界；integrity.json 记清单哈希，装时逐文件校验，改一字节即失败。

## 3 怎么用一次

解压 ui/minimal/，跑 install.ps1 -CheckOnly 自检，再去掉参数安装。

---
真源: docs/UI_极简前端.md
