---
name: lingshu-net
description: >-
  灵枢白箱条件单元域入口：网络（117 单元 / 2 子域）。触发词：TCP、UDP、HTTP、DNS、路由、拥塞控制、限流、负载均衡、TLS、蜂群。
  场景：任务命中本域任一子域主题时使用。先查下方路由表定位单元，语义模糊时经 mdcg cg op=route 路由；
  单元正文在 units/<slug>/SKILL.md 按需回读（KCCS 四要素在各单元内，不随本入口加载）。
  【不适用】Not for：任务不属于本域任何子域主题（负路由）；跨域方向判断改用 designer-perspective 元技能。
license: MIT
allowed-tools: Read Grep Glob Bash
metadata:
  version: "2.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-09-11"
  domain: net
  unit-count: 117
  kccs:
    trigger_words: ["网络", "蜂群"]
    when: "任务命中本域单元的生效条件（子域主题见路由表；单元级条件在 units/<slug>/SKILL.md）"
    sub: ["网络", "蜂群"]
    execute: "① 定位：路由表或 mdcg cg op=route → ② 回读 units/<slug>/SKILL.md → ③ 按单元 KCCS 执行 → ④ 验证交灵枢 MCP（编译/运行/断言）"
    not_applicable: ["任务不属于本域任何子域主题（负路由）", "需要全局观测/资格裁决时改用 designer-perspective（元技能不执行操作层）"]
---

# 灵枢 网络域入口（lingshu-net）

白箱条件单元域入口（v2.0 层级化重组）。本域 117 个单元收纳于 `units/`，
本文件只承载**子域路由**——description 进上下文做域级命中，单元按需回读。

## 路由表（子域 → 单元）

| 子域 | 数 | 单元（slug · 中文主题）|
|---|---|---|
| 网络 | 111 | `net-02090d29` · 网络-NAT（net-02090d29）、`net-05937712` · 网络-NTP同步（net-05937712）、`net-059d072f` · 网络-TCP握手（net-059d072f）、`net-080f6012` · 网络-吞吐量测量（net-080f6012）、`net-08a2fc88` · 网络-路由收敛（net-08a2fc88）、`net-0935edf1` · 网络-拓扑发现（net-0935edf1）、`net-0e7f91e4` · 网络-CRC校验（net-0e7f91e4）、`net-0f2850e0` · 网络-API限流（net-0f2850e0）、`net-107ab486` · 网络-网关（net-107ab486）、`net-111e79b0` · 网络-链路加密（net-111e79b0）、`net-126876c1` · 网络-报文解析（net-126876c1）、`net-13eeb575` · 网络-前向纠错（net-13eeb575）、`net-14102d54` · 网络-广播风暴（net-14102d54）、`net-14e9ad0d` · 网络-滑动窗口限流（net-14e9ad0d）、`net-184175d3` · 网络-边缘计算（net-184175d3）、`net-1da1c695` · 网络-CDN缓存（net-1da1c695）、`net-240a14ec` · 网络-时隙（net-240a14ec）、`net-2784f98b` · 网络-帧解析（net-2784f98b）、`net-292ef917` · 网络-报文重排序（net-292ef917）、`net-3434e92f` · 网络-数据包采样（net-3434e92f）、`net-3bbc6afb` · 网络-ARP解析（net-3bbc6afb）、`net-3bdf9d9d` · 网络-多径传输（net-3bdf9d9d）、`net-3dcb84d3` · 网络-连接池（net-3dcb84d3）、`net-431cccf9` · 网络-路由汇聚（net-431cccf9）、`net-435a9f7f` · 网络-压缩传输（net-435a9f7f）、`net-4508101f` · 网络-蜂群中继（net-4508101f）、`net-4585c9e7` · 网络-路由衰减（net-4585c9e7）、`net-479612a0` · 网络-WebSocket握手（net-479612a0）、`net-4e36e1e3` · 网络-链路聚合（net-4e36e1e3）、`net-509b8001` · 网络-流分类（net-509b8001）、`net-51930c5e` · 网络-拥塞控制（net-51930c5e）、`net-56dbd63f` · 网络-Anycast（net-56dbd63f）、`net-57387462` · 网络-链路状态路由（net-57387462）、`net-5c115606` · 网络-异常检测（net-5c115606）、`net-5d27f392` · 网络-反向代理（net-5d27f392）、`net-5f69c938` · 网络-累积确认（net-5f69c938）、`net-5fa6c13b` · 网络-帧封装（net-5fa6c13b）、`net-61926703` · 网络-RTO退避（net-61926703）、`net-61f64fbc` · 网络-令牌桶限速（net-61f64fbc）、`net-6200f3b2` · 网络-隧道封装（net-6200f3b2）、`net-66e6119b` · 网络-DHCP租约（net-66e6119b）、`net-68643014` · 网络-访问令牌（net-68643014）、`net-686632aa` · 网络-链路预算（net-686632aa）、`net-6967ff14` · 网络-心跳保活（net-6967ff14）、`net-6996f499` · 网络-路径备份（net-6996f499）、`net-6c3b02c2` · 网络-带宽分配（net-6c3b02c2）、`net-6eb37f63` · 网络-链路利用率（net-6eb37f63）、`net-6f96c190` · 网络-QUIC握手（net-6f96c190）、`net-6fb27488` · 网络-距离矢量（net-6fb27488）、`net-703559d0` · 网络-加密握手（net-703559d0）、`net-706d2692` · 网络-组播（net-706d2692）、`net-70a20e04` · 网络-RTT平滑（net-70a20e04）、`net-7376158c` · 网络-流量统计（net-7376158c）、`net-74d647cb` · 网络-连接迁移（net-74d647cb）、`net-74e8a576` · 网络-尽力交付（net-74e8a576）、`net-7801c2c0` · 网络-选择性确认（net-7801c2c0）、`net-78cae54d` · 网络-滑动窗口（net-78cae54d）、`net-78ec0324` · 网络-IPv6地址（net-78ec0324）、`net-7998097c` · 网络-延迟测量（net-7998097c）、`net-7d81ae06` · 网络-抓包分析（net-7d81ae06）、`net-7eabbbc8` · 网络-误码率（net-7eabbbc8）、`net-7ed4f2c5` · 网络-多路复用（net-7ed4f2c5）、`net-80b56cd6` · 网络-证书校验（net-80b56cd6）、`net-83447546` · 网络-数据去重（net-83447546）、`net-8361fe5b` · 网络-路径MTU发现（net-8361fe5b）、`net-85e3996c` · 网络-重传统计（net-85e3996c）、`net-8897d5cc` · 网络-BGP路径选择（net-8897d5cc）、`net-88ad93a6` · 网络-网络切片（net-88ad93a6）、`net-8e6f359e` · 网络-包过滤（net-8e6f359e）、`net-8edc4cdb` · 网络-分块传输（net-8edc4cdb）、`net-8f6169e9` · 网络-HTTP状态码（net-8f6169e9）、`net-91e00638` · 网络-序列号回绕（net-91e00638）、`net-96c61a3c` · 网络-IP分片（net-96c61a3c）、`net-99076a29` · 网络-跳频（net-99076a29）、`net-998f3641` · 网络-MQTT发布订阅（net-998f3641）、`net-a1d7228a` · 网络-内容路由（net-a1d7228a）、`net-a74da501` · 网络-端口转发（net-a74da501）、`net-ac57deb7` · 网络-报文调度（net-ac57deb7）、`net-b22d2f2b` · 网络-内容协商（net-b22d2f2b）、`net-b2b29d8d` · 网络-局域网发现（net-b2b29d8d）、`net-b2ddce5d` · 网络-DNS解析（net-b2ddce5d）、`net-b4151e9a` · 网络-CSMA退避（net-b4151e9a）、`net-b873d6f7` · 网络-ICMP探测（net-b873d6f7）、`net-bd3d2d55` · 网络-服务发现（net-bd3d2d55）、`net-c2a3f019` · 网络-漏桶限流（net-c2a3f019）、`net-c685b788` · 网络-停等协议（net-c685b788）、`net-c6c1fd79` · 网络-慢启动（net-c6c1fd79）、`net-c74a1b5d` · 网络-会话亲和（net-c74a1b5d）、`net-cdac702d` · 网络-校验和（net-cdac702d）、`net-d12dff5c` · 网络-Reno拥塞控制（net-d12dff5c）、`net-d3747882` · 网络-流式传输（net-d3747882）、`net-d5fefa59` · 网络-数据序列化（net-d5fefa59）、`net-d67ec725` · 网络-消息路由（net-d67ec725）、`net-d80c1c4c` · 网络-消息队列（net-d80c1c4c）、`net-d9cb43b0` · 网络-多宿主（net-d9cb43b0）、`net-da559517` · 网络-MAC学习（net-da559517）、`net-db4f414e` · 网络-负载均衡（net-db4f414e）、`net-dc09d67c` · 网络-VLAN划分（net-dc09d67c）、`net-e2d185de` · 网络-物联网遥测（net-e2d185de）、`net-e2fc73f8` · 网络-CIDR（net-e2fc73f8）、`net-e33ef0c2` · 网络-协议解码（net-e33ef0c2）、`net-e6b3389a` · 网络-HTTP重定向（net-e6b3389a）、`net-e9758fc0` · 网络-流量镜像（net-e9758fc0）、`net-e9a9747a` · 网络-报文分片（net-e9a9747a）、`net-ea14aab8` · 网络-快速重传（net-ea14aab8）、`net-f29d91d2` · 网络-会话超时（net-f29d91d2）、`net-f314dd0d` · 网络-QoS队列（net-f314dd0d）、`net-f332b629` · 网络-策略路由（net-f332b629）、`net-f7df127c` · 网络-端口镜像（net-f7df127c）、`net-fb9d8f5d` · 网络-端口扫描检测（net-fb9d8f5d）、`net-fdec2c86` · 网络-带宽时延积（net-fdec2c86） |
| 蜂群 | 6 | `net-35019e6b` · 蜂群-超时重传（net-35019e6b）、`net-47a19838` · 蜂群-消息分帧（net-47a19838）、`net-61580202` · 蜂群-会话状态（net-61580202）、`net-63c3eda3` · 蜂群-路由表（net-63c3eda3）、`net-e346863c` · 蜂群-配对信任（net-e346863c）、`net-eba92ac1` · 蜂群-消息去重（net-eba92ac1） |

## 路由流程

1. **词面命中**：任务含子域/单元触发词 → 直接查上表回读对应单元
2. **语义模糊**：`mdcg cg op=route intent=<任务描述>` → 返回建议能力名与知识
3. **回读**：`units/<单元slug>/SKILL.md`（含 KCCS 四要素与验证样例）
4. **验证**：灵枢 MCP 工具物理执行（编译/运行/断言裁决），技能说"怎么验证"、MCP 负责"真去跑"

## 真源与纪律

- 知识真源：`md_cg/whitebox_kb/wisdom/net_units.py`（KCCS 四要素唯一真源）
- 本包为生成投影（2026-09-11 层级化重组 v2.0）：单元内容零改动，仅目录收纳 + 域入口新增
- 触发词全量索引：`md_cg/whitebox_kb/wisdom/trigger_words_index.json`
- 变更须在真源层修改后重新导出（R6 变更验证），勿直接改本目录单元
