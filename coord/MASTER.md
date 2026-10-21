# 中枢作战板

更新时间：2026-10-21 18:05 +08:00

## 当前路线

| 路线 | 分支 | 会话 | 目标 | 状态 |
|---|---|---|---|---|
| 基线准确率 | main `accuracy/` | 中枢 | 金标准、模型探针、逐帧精确率 | 开发集 Doubao 15/18；Aibox count_v2 实验中 |
| 方案调研 | `research/accuracy-landscape` | research | 多模型/裁剪/共识专业方案 | 实验中 |
| 识别后端 | `feat/accuracy-pipeline` | pipeline | 可运行 API、抽帧、共识、评测 | 实现中 |
| 时序实体 | `research/temporal-reid` | temporal | 时序条 + 跨机位实体图 | 实验中 |
| 架构挑战 | `research/architecture-challenge` | architecture | 空间分解/递归候选树/场景图 | 启动 |
| 容量几何 | `research/capacity-geometry` | capacity | 单应标定、容量、不确定度 | 15/15 测试通过，PR 待补 REPORT |
| 第二套界面 | `feat/web-workspace-v2` | ui_finish | 可交互工作台 + 截图验收 | PR #2 待评审 |
| 全时段时间轴 | `research/event-timeline` | events | 44 分钟分钟级采样与事件 | 实验中 |
| 调试体验 | `debug/live-experience` | debug | 实测识别调试台 + 固定文件名截图 | **已合并 PR #3** |

## 已确认事实

1. 可用视觉模型：Doubao endpoint；智谱 `glm-4.5v`；Aibox `glm-5.3-flash`。`glm-4.7`、`glm-5.3` 不可用作视觉。
2. 逐机位人工开发集计数见 `data/gold/camera_counts_v0.json`。北机位 10 帧为 `3,3,4,3,3,2,2,2,3,2`，南机位为 `3,4,5,5,5,5,4,4,3,3`。
3. Doubao 整帧在已完成的 18 个样本中 15 个完全正确（83.3%），MAE 0.22；错误全部是遮挡/远端漏计。
4. `north_600` 整帧模型报 2，人工核实为 4；裁剪放大后可找回，但会拆分同一辆车。
5. 南机位车型有明显 `large` 偏置，必须做候选裁剪二次判定。
6. 跨机位去重尚未完成，所有“合计”数字不能当唯一车辆真值。
7. 新发现：`north_600` 可通过顶部/中部/近景三段裁剪分别找到远端两辆蓝色货厢车；但三类模型对同一车体的拆分并不稳定，必须做候选合并与复核。
8. 当前界面：`all-sessions-can-see/assets/live/latest-desktop.png`，每 30 分钟自动重截。
9. 实测调试台（已合并）：`debug/viewer/lab.html`，逐帧显示预测/人工/差值、模型真实 bbox、同帧模型对照；本机常驻地址 `http://127.0.0.1:4178/debug/viewer/lab.html`。
10. Aibox `glm-5.3-flash` + count_v2 的单次 `north_600 = 4` **不可复现**：全量重跑同一帧返回 3（人工 4）。单样本胜利不能当作能力。
11. Aibox count_v2 全量实测（19 条有效记录）只有 10 条完全正确（52.6%），MAE 0.47；错误以近景多计 1 辆为主（北 5/300/2400，南 5/300/1500/1800/2400），远端仍有漏计。它不适合当主力，只能作为独立复核/分歧探针。
12. Aibox 单帧耗时约 30–50 秒，存在 503 重试成本；实时性需在架构层单独评估。

## 合并记录

- PR #1 `debug/experience` 已合并：可重复的浏览器截图与独立预览页，无识别算法改动。
- PR #3 `debug/live-experience` 已合并：实测识别调试台，只画模型原始 bbox，截图自检通过。
- PR #2 `feat/web-workspace-v2` 已开：真实开发集计数、双机位工作台、无伪造框，待评审。
- `main` 提交 `3b8d6a8`：留存 count_v2 提示词、三模型探针与 20 帧通道提示词实验证据。

## 门禁

- 没有金标准证据的数字只标 `DEMO` 或 `pending_review`。
- 任何架构必须报告 exact match / MAE / 漏检 / 多计 / 车型错误 / 成本。
- 合并顺序：先冻结基线评测，再吸收改动；每次只合并一个 PR 并回归。

