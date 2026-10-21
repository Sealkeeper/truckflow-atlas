# 中枢作战板

更新时间：2026-10-21 17:05 +08:00

## 当前路线

| 路线 | 分支 | 会话 | 目标 | 状态 |
|---|---|---|---|---|
| 基线准确率 | main `accuracy/` | 中枢 | 金标准、模型探针、逐帧精确率 | 开发集 18 帧；Doubao 15/18 精确 |
| 方案调研 | `research/accuracy-landscape` | research | 多模型/裁剪/共识专业方案 | 实验中 |
| 识别后端 | `feat/accuracy-pipeline` | pipeline | 可运行 API、抽帧、共识、评测 | 实现中 |
| 时序实体 | `research/temporal-reid` | temporal | 时序条 + 跨机位实体图 | 实验中 |
| 架构挑战 | `research/architecture-challenge` | architecture | 空间分解/递归候选树/场景图 | 启动 |
| 容量几何 | `research/capacity-geometry` | capacity | 单应标定、容量、不确定度 | 启动 |
| 第二套界面 | `feat/web-workspace-v2` | ui_finish | 可交互工作台 + 截图验收 | 启动 |

## 已确认事实

1. 可用视觉模型：Doubao endpoint；智谱 `glm-4.5v`；Aibox `glm-5.3-flash`。`glm-4.7`、`glm-5.3` 不可用作视觉。
2. 逐机位人工开发集计数见 `data/gold/camera_counts_v0.json`。北机位 10 帧为 `3,3,4,3,3,2,2,2,3,2`，南机位为 `3,4,5,5,5,5,4,4,3,3`。
3. Doubao 整帧在已完成的 18 个样本中 15 个完全正确（83.3%），MAE 0.22；错误全部是遮挡/远端漏计。
4. `north_600` 整帧模型报 2，人工核实为 4；裁剪放大后可找回，但会拆分同一辆车。
5. 南机位车型有明显 `large` 偏置，必须做候选裁剪二次判定。
6. 跨机位去重尚未完成，所有“合计”数字不能当唯一车辆真值。

## 门禁

- 没有金标准证据的数字只标 `DEMO` 或 `pending_review`。
- 任何架构必须报告 exact match / MAE / 漏检 / 多计 / 车型错误 / 成本。
- 合并顺序：先冻结基线评测，再吸收改动；每次只合并一个 PR 并回归。

