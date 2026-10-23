# 可自取任务队列（pull 模式）

> **历史队列，不是当前自动派单入口。** 以下任务归属、完成状态和零付费 / 禁下载规则是旧窗口快照，
> 不据此自动认领或执行。新贡献先开 issue 核对现状、输入和授权，避免重复任务。
> 实时与离线按 [2026-10-23 最新边界](../../CONTRIBUTING.md#实时部署与离线研发的边界)：
> 实时链路不依赖 YOLO 类检测器，离线教师 / 预标注 / 蒸馏可研究，具体执行仍须数据隔离与资源预算。
> 旧规则不一刀切禁止离线研究，也不赋予任何新请求 / 下载 / 训练权限。

规则（所有会话共同遵守）：

1. 做完手上任务后**不要停**，直接从本文件挑一条 `STATUS: OPEN` 的任务，把该行改成
   `STATUS: CLAIMED by <你的角色> <HH:MM>`，然后立刻开始做。
2. 同一时刻一个任务只能有一个认领者。**只改自己认领的那一行**，不要重排整个文件。
3. 做完把 `CLAIMED` 改成 `STATUS: DONE <路径>`，并写一句话结论（含分母）。
4. 认领后若发现与别人重复，立刻释放（改回 `OPEN`）并在消息里说明。
5. 所有任务默认零付费：**不得调用任何 chat/completions**，不得下载检测器/分割模型/SAM。
6. 任何数字必须带分母与文件 sha；拿不到分母就写"未测"。

---

## Q1 复算审计者（防虚报）

STATUS: CLAIMED by 架构推翻 21:36
目标：独立复算最近 72 小时所有对外报过的数字。逐条重建并比对：
`results-old10.json` 的 5/10、`CEILING_DECOMPOSITION.md` 的 7/10 与 8/10 与 10/10、
`V3B_ROBUSTNESS.md` 的 6/10 与 7/10、`SELF_CONSISTENCY.md` 的 17/20→19/20。
交付：`coord/optimization-20261022/audit/NUMBER_AUDIT.md`，每条给"复现值 / 报告值 / 是否一致 / 差异原因"。
验收：不一致项必须能指到具体行号或字段；不得只写"一致"。

## Q2 全量视频挖掘（扩大样本）

STATUS: CLAIMED by 多分支探索 21:36
目标：从现有南北视频里再找出**至少 10 个**可用于回归的时刻（有明确车辆、且不与现有 15 个重复），
输出时刻表（秒数、帧号、南北是否都有车、交通状态描述）与抽取命令。
交付：`coord/optimization-20261022/dataset/CANDIDATE_MOMENTS.md` + `candidates.json`。
验收：每个时刻给出南北两帧的路径与 sha256；**不标注真值**（真值仍需人工）。

## Q3 性能瓶颈画像（不跑模型）

STATUS: DONE coord/optimization-20261022/performance/COST_PROFILE.md — 20/20 冻结 attempt 复算：推理占总 token 189898/257917（73.63%），总 token 减半需在其余开销不变时削减推理 67.91%（非实测节省）；JSON SHA256 955aeb424b3ca6841fb6bd0daccd6faf5d4dfd5864dac0461fcdc5b70b7ef485。
目标：用冻结的 20 个 attempt 记录（tokens、reasoning_tokens、耗时），画出
「tokens/帧 vs 帧内车辆数」「reasoning_tokens 占比」「单请求耗时分布」，
找出"哪一类帧最贵"，为 tokens/帧 ≤ 基线 50% 指出可压缩点。
交付：`coord/optimization-20261022/performance/COST_PROFILE.md` + 图 + json。
验收：每个结论必须能落到具体 attempt 字段；不得用估计值冒充实测。

## Q4 提示词契约（不发调用）

STATUS: CLAIMED by 错误解剖 21:40
目标：把 `invention/contract/SCHEMA.md` 变成一份**可直接使用的提示词文本**（中文），
要求模型逐候选输出 `eligibility` 三态与 `evidence`，且**不得直接给总数**。
同时写一个"违规输出检测器"（缺字段、给了总数、evidence 为空都要报错）。
交付：`coord/optimization-20261022/contract/PROMPT_V1.md` + `validate_output.py` + 单测。
验收：用 3 个手工构造的违规样例证明检测器能拦住。

## Q5 重叠边定义压力测试

STATUS: DONE coord/optimization-20261022/labeling/OVERLAP_EDGE_SPEC.md — 5 条同画面候选中按规范应判重叠边 1/5（S05）、不应判 4/5；用 bbox 相交自动判边会多出 4/5 假边。
目标：用 `identity-deepdive/denominator/candidates.json` 的 5 条同画面重叠候选，
检验"重叠边"定义在边界情况下的行为（部分遮挡、一车完全挡住另一车、只共享一条边）。
交付：`coord/optimization-20261022/labeling/OVERLAP_EDGE_SPEC.md`（含 5 个案例的判定表）。
验收：每种边界情况给"应判/不应判"的明确规则与理由，供标注台统一口径。

## Q6 指标口径冻结版

STATUS: CLAIMED by 盲测与统计 21:37
目标：把两个主指标写成**机器可执行的判定伪代码**（含 unknown/拒答/部分真值/重复 ID 的处理），
并与 `coord/evaluation-v3/` 的实际实现逐条对照，列出实现与文档不一致处。
交付：`coord/evaluation-v3/PROTOCOL_FROZEN.md` + `parity.md`。
验收：任何不一致必须给最小复现输入。

## Q7 失败帧可视化复盘

STATUS: DONE coord/optimization-20261022/error-atlas/figures/FAIL_600.jpg, FAIL_2400.jpg, FAIL_2600.jpg — 3/3 张四联图已生成并对齐 10 时刻中的 3 个失败帧；原图未改。
目标：为 t600 / t2400 / t2600 各生成一张"预测 vs 真值"的四联图（南预测、南真值、北预测、北真值），
让非专业读者一眼看出错在哪。
交付：`coord/optimization-20261022/error-atlas/figures/FAIL_<t>.jpg`。
验收：图上标注对象编号与多/少标记；不得修改原图。

## Q8 成本与预算模型

STATUS: DONE coord/optimization-20261022/experiment/COST_MODEL.md — 7 个 run × 20 帧实测（sha 607A9828F750F10F）：raw_lite 12,896 tokens/帧（20/20），reasoning 占 completion 97.7%；thinking 关掉后 3,395（26%）。单价日志缺失=待用户填；±2pp 95% CI 需 900–2,400 个时刻（15 个时刻只能到 ±20–25pp）。
目标：基于冻结 attempt 的真实 usage 字段，建一个成本模型：
每帧 tokens、每千帧成本、不同像素预算下的预估成本；并给出"要跑多少帧才能把 15 时刻的
95% 置信区间压到 ±2%"的样本量估算。
交付：`coord/optimization-20261022/experiment/COST_MODEL.md` + 计算脚本。
验收：公式与代入值都写出；单价缺失处明确标"待用户填"。
