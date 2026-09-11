---
name: lingshu-browser
description: >-
  灵枢白箱条件单元域入口：浏览器与网页（104 单元 / 14 子域）。触发词：浏览器、渲染、DOM、事件循环、Web存储、CSP、性能、PWA。
  场景：任务命中本域任一子域主题时使用。先查下方路由表定位单元，语义模糊时经 mdcg cg op=route 路由；
  单元正文在 units/<slug>/SKILL.md 按需回读（KCCS 四要素在各单元内，不随本入口加载）。
  【不适用】Not for：任务不属于本域任何子域主题（负路由）；跨域方向判断改用 designer-perspective 元技能。
license: MIT
allowed-tools: Read Grep Glob Bash
metadata:
  version: "2.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-09-11"
  domain: browser
  unit-count: 104
  kccs:
    trigger_words: ["浏览器", "渲染", "安全", "性能", "PWA", "事件", "存储", "网络", "CSS", "HTTP", "并行", "HTML"]
    when: "任务命中本域单元的生效条件（子域主题见路由表；单元级条件在 units/<slug>/SKILL.md）"
    sub: ["浏览器", "渲染", "安全", "性能", "PWA", "事件", "存储", "网络", "CSS", "HTTP", "并行", "HTML", "URL", "通知"]
    execute: "① 定位：路由表或 mdcg cg op=route → ② 回读 units/<slug>/SKILL.md → ③ 按单元 KCCS 执行 → ④ 验证交灵枢 MCP（编译/运行/断言）"
    not_applicable: ["任务不属于本域任何子域主题（负路由）", "需要全局观测/资格裁决时改用 designer-perspective（元技能不执行操作层）"]
---

# 灵枢 浏览器与网页域入口（lingshu-browser）

白箱条件单元域入口（v2.0 层级化重组）。本域 104 个单元收纳于 `units/`，
本文件只承载**子域路由**——description 进上下文做域级命中，单元按需回读。

## 路由表（子域 → 单元）

| 子域 | 数 | 单元（slug · 中文主题）|
|---|---|---|
| 浏览器 | 57 | `browser-03b04f98` · 浏览器-表单验证（browser-03b04f98）、`browser-093c03ab` · 浏览器-预加载（browser-093c03ab）、`browser-09e60b35` · 浏览器-画中画（browser-09e60b35）、`browser-0ab4f2db` · 浏览器-网络记录（browser-0ab4f2db）、`browser-0f598430` · 浏览器-页面可见性（browser-0f598430）、`browser-18f823e2` · 浏览器-响应式断点（browser-18f823e2）、`browser-1bafe81c` · 浏览器-振动反馈（browser-1bafe81c）、`browser-1fdb5852` · 浏览器-标签页通信（browser-1fdb5852）、`browser-22e8de36` · 浏览器-触控手势（browser-22e8de36）、`browser-2895ff52` · 浏览器-文件系统访问（browser-2895ff52）、`browser-2cc1da58` · 浏览器-扩展管理（browser-2cc1da58）、`browser-3189fe6f` · 浏览器-字体加载（browser-3189fe6f）、`browser-31f2b08f` · 浏览器-形状检测（browser-31f2b08f）、`browser-396ec3a6` · 浏览器-书签管理（browser-396ec3a6）、`browser-43154cec` · 浏览器-窗口管理（browser-43154cec）、`browser-434b74b8` · 浏览器-资源优先级（browser-434b74b8）、`browser-440d4398` · 浏览器-弹窗拦截（browser-440d4398）、`browser-4d6c0788` · 浏览器-媒体播放（browser-4d6c0788）、`browser-50fecd89` · 浏览器-历史记录（browser-50fecd89）、`browser-57312d24` · 浏览器-离线队列（browser-57312d24）、`browser-59a0ada4` · 浏览器-语音合成（browser-59a0ada4）、`browser-5a455aeb` · 浏览器-摄像头（browser-5a455aeb）、`browser-5ae7623a` · 浏览器-标签页管理（browser-5ae7623a）、`browser-5e5f1396` · 浏览器-扫码（browser-5e5f1396）、`browser-5ebb01dd` · 浏览器-唤醒锁（browser-5ebb01dd）、`browser-5f5453f9` · 浏览器-传感器（browser-5f5453f9）、`browser-5f90f58c` · 浏览器-语言检测（browser-5f90f58c）、`browser-609362ee` · 浏览器-蓝牙扫描（browser-609362ee）、`browser-6636d49c` · 浏览器-拖放交互（browser-6636d49c）、`browser-6cfcb6db` · 浏览器-联系人（browser-6cfcb6db）、`browser-77a97b43` · 浏览器-存储配额（browser-77a97b43）、`browser-7bb4871d` · 浏览器-剪贴板（browser-7bb4871d）、`browser-7da433f3` · 浏览器-屏幕捕获（browser-7da433f3）、`browser-7f9cefec` · 浏览器-虚拟键盘（browser-7f9cefec）、`browser-80224e71` · 浏览器-全屏模式（browser-80224e71）、`browser-822cfa44` · 浏览器-屏幕方向（browser-822cfa44）、`browser-853690c0` · 浏览器-内置聊天（browser-853690c0）、`browser-85553126` · 浏览器-权限API（browser-85553126）、`browser-87b0ce80` · 浏览器-在线状态（browser-87b0ce80）、`browser-910405c4` · 浏览器-语音识别（browser-910405c4）、`browser-9e4914a7` · 浏览器-网页共享（browser-9e4914a7）、`browser-a280ec64` · 浏览器-网络信息（browser-a280ec64）、`browser-a2d9b0b0` · 浏览器-游戏手柄（browser-a2d9b0b0）、`browser-a990e68e` · 浏览器-翻译（browser-a990e68e）、`browser-bcd4288d` · 浏览器-图像生成（browser-bcd4288d）、`browser-bfad66a5` · 浏览器-请求合并（browser-bfad66a5）、`browser-c879eb0b` · 浏览器-文本摘要（browser-c879eb0b）、`browser-c92ac01b` · 浏览器-CSP报告（browser-c92ac01b）、`browser-cb179242` · 浏览器-设备方向（browser-cb179242）、`browser-cf3c47f0` · 浏览器-会话恢复（browser-cf3c47f0）、`browser-d462581c` · 浏览器-下载管理（browser-d462581c）、`browser-d5fa0b7f` · 浏览器-空闲调度（browser-d5fa0b7f）、`browser-e84565c1` · 浏览器-音频上下文（browser-e84565c1）、`browser-ea9b2b8e` · 浏览器-地理位置（browser-ea9b2b8e）、`browser-f75a4418` · 浏览器-资源完整性（browser-f75a4418）、`browser-f8f2966e` · 浏览器-支付请求（browser-f8f2966e）、`browser-ff94a671` · 浏览器-提示词（browser-ff94a671） |
| 渲染 | 16 | `browser-0c7f88d6` · 渲染-盒模型（browser-0c7f88d6）、`browser-1f9ab1f0` · 渲染-边框圆角（browser-1f9ab1f0）、`browser-21b0359c` · 渲染-文本排版（browser-21b0359c）、`browser-44d7f183` · 渲染-渐变填充（browser-44d7f183）、`browser-60aefeeb` · 渲染-滚动容器（browser-60aefeeb）、`browser-716cd26c` · 渲染-动画帧（browser-716cd26c）、`browser-7be57bbe` · 渲染-颜色转换（browser-7be57bbe）、`browser-7e96fe1d` · 渲染-混合模式（browser-7e96fe1d）、`browser-81345ecd` · 渲染-重排重绘（browser-81345ecd）、`browser-a372edeb` · 渲染-命中测试（browser-a372edeb）、`browser-a7a2b0c1` · 渲染-绘制（browser-a7a2b0c1）、`browser-aaac4eec` · 渲染-布局树（browser-aaac4eec）、`browser-ae6586bb` · 渲染-合成分层（browser-ae6586bb）、`browser-c4dd6078` · 渲染-样式计算（browser-c4dd6078）、`browser-df1a919e` · 渲染-块布局（browser-df1a919e）、`browser-fa65fa2d` · 渲染-像素光栅化（browser-fa65fa2d） |
| 安全 | 6 | `browser-25afee4d` · 安全-沙箱隔离（browser-25afee4d）、`browser-555c0626` · 安全-同源策略（browser-555c0626）、`browser-5dac60b6` · 安全-CORS检查（browser-5dac60b6）、`browser-a681d0c2` · 安全-CSP策略（browser-a681d0c2）、`browser-b501767c` · 安全-混合内容（browser-b501767c）、`browser-faac8812` · 安全-XSS防护（browser-faac8812） |
| 性能 | 4 | `browser-37b8339e` · 性能-关键渲染路径（browser-37b8339e）、`browser-3df2f904` · 性能-懒加载（browser-3df2f904）、`browser-900c4484` · 性能-防抖节流（browser-900c4484）、`browser-d72e225b` · 性能-渲染优化（browser-d72e225b） |
| PWA | 3 | `browser-6e1c1158` · PWA-应用清单（browser-6e1c1158）、`browser-cc7d3d6d` · PWA-安装事件（browser-cc7d3d6d）、`browser-cf9f812e` · PWA-缓存策略（browser-cf9f812e） |
| 事件 | 3 | `browser-02898b15` · 事件-事件冒泡（browser-02898b15）、`browser-97a14ca3` · 事件-事件监听（browser-97a14ca3）、`browser-b4c8cf65` · 事件-事件委托（browser-b4c8cf65） |
| 存储 | 3 | `browser-7008e942` · 存储-IndexedDB（browser-7008e942）、`browser-720ce1a1` · 存储-本地存储（browser-720ce1a1）、`browser-95fd3c86` · 存储-会话存储（browser-95fd3c86） |
| 网络 | 3 | `browser-0754386d` · 网络-Fetch请求（browser-0754386d）、`browser-a4c793a4` · 网络-Cookie（browser-a4c793a4）、`browser-e947a564` · 网络-HTTP缓存（browser-e947a564） |
| CSS | 2 | `browser-17906c62` · CSS-选择器（browser-17906c62）、`browser-c45cbfe9` · CSS-级联（browser-c45cbfe9） |
| HTTP | 2 | `browser-2471a991` · HTTP-请求构建（browser-2471a991）、`browser-9de10895` · HTTP-响应解析（browser-9de10895） |
| 并行 | 2 | `browser-0fd64fa5` · 并行-Service Worker（browser-0fd64fa5）、`browser-f5ffc6d9` · 并行-Web Worker（browser-f5ffc6d9） |
| HTML | 1 | `browser-24163519` · HTML-DOM解析（browser-24163519） |
| URL | 1 | `browser-afa4091f` · URL-解析（browser-afa4091f） |
| 通知 | 1 | `browser-283a91bd` · 通知-推送消息（browser-283a91bd） |

## 路由流程

1. **词面命中**：任务含子域/单元触发词 → 直接查上表回读对应单元
2. **语义模糊**：`mdcg cg op=route intent=<任务描述>` → 返回建议能力名与知识
3. **回读**：`units/<单元slug>/SKILL.md`（含 KCCS 四要素与验证样例）
4. **验证**：灵枢 MCP 工具物理执行（编译/运行/断言裁决），技能说"怎么验证"、MCP 负责"真去跑"

## 真源与纪律

- 知识真源：`md_cg/whitebox_kb/wisdom/browser_units.py`（KCCS 四要素唯一真源）
- 本包为生成投影（2026-09-11 层级化重组 v2.0）：单元内容零改动，仅目录收纳 + 域入口新增
- 触发词全量索引：`md_cg/whitebox_kb/wisdom/trigger_words_index.json`
- 变更须在真源层修改后重新导出（R6 变更验证），勿直接改本目录单元
