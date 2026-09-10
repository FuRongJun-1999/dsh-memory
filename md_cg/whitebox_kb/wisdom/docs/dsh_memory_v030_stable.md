# dsh-memory v0.3.0 · 长期稳定版发布记录（2026-09）

## 版本状态

- **版本**：v0.3.0（tag 已推）
- **能力验证**：WB-SPEC 八维 **0.9851**（W1-W5+W8 全满格，W6 0.9457，W7 0.8106）
- **回归**：25 套测试全绿（CCG/自迭代/执行计划/工作流/技能/理论完整性/情绪决策/条件反射）
- **修复**：Issue #2 git 安装空壳（补 prepare 脚本 + files 含 src）——已验证 npm run build 通过、npm test 7/7

## 白箱代码能力（稳定版基线）

| 维度 | 得分 | 说明 |
|---|---|---|
| W1-W5 | 1.0 | 可执行/功能/边界/规范/集成全满（681 单元确定性） |
| W6 效率 | 0.9457 | 修评估器缺陷后真实水平（37 状态机语义复杂度） |
| W7 可读 | 0.8106 | 短名惯例短板（诚实保留） |
| W8 安全 | 1.0 | 零 LLM 无注入面 |
| **总分** | **0.9851** | 长期稳定基线 |

## 能力清单（v0.3.0）

- **核心**：route / verify / audit / stats / nl_compile（六域 681 单元，零 LLM）
- **CCG**：ccg_search / ccg_compose / ccg_route（四态递归）/ ccg_escalate（分层判断）/ ccg_report / ccg_bootstrap
- **第七阶段**：wf_execute / wf_load（能力工作流，仿 ComfyUI）/ skills_cond（技能条件路由）/ ccg_confidence（路由置信度）
- **自迭代**：八步闭环（感知→识别→分析→验证→固化→记录→反馈→方向性自检，含理论完整性自指检查）+ auto_iterate 自动循环 + 条件反射优先度

## Issue 处理

- **#2 git 安装空壳**：✅ 已修复（commit 05f5914 → 75f427d），回复已备（需 GITHUB_TOKEN 手动提交）
- **#1 DSH Directory 收录**：待处理（社区目录收录邀请，需填写提交表单）

## 后续

- 自举探针（mini 计算器跑 condition_vm）为下一阶段任务（方向性抉择 C 已定）
