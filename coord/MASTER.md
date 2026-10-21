# 中枢作战板

更新时间：2026-10-21 19:30 +08:00

## 当前路线

| 路线 | 分支 | 会话 | 目标 | 状态 |
|---|---|---|---|---|
| 基线准确率 | main `accuracy/` | 中枢 | 金标准、模型探针、逐帧精确率 | 20 帧全量：Doubao 16/20；Aibox count_v2 10/20 |
| 方案调研 | `research/accuracy-landscape` | research | 多模型/裁剪/共识专业方案 | 实验中 |
| 识别后端 | `feat/accuracy-pipeline` | pipeline | 可运行 API、抽帧、共识、评测 | 实现中 |
| 时序实体 | `research/temporal-reid` | temporal | 时序条 + 跨机位实体图 | 实验中 |
| 架构挑战 | `research/architecture-challenge` | architecture | 空间分解/递归候选树/场景图 | 启动 |
| 容量几何 | `research/capacity-geometry` | capacity | 单应标定、容量、不确定度 | 15/15 测试通过，**已合并 PR #4** |
| 第二套界面 | `feat/web-workspace-v2` | ui_finish | 可交互工作台 + 截图验收 | **已合并 PR #2** |
| 全时段时间轴 | `research/event-timeline` | events | 44 分钟分钟级采样与事件 | **已合并 PR #6**；人工抽查 19/24 |
| 调试体验 | `debug/live-experience` | debug | 实测识别调试台 + 固定文件名截图 | **已合并 PR #3** |
| 终审复核 | main `review/` | 中枢 | 20 时刻连续帧 + 争议视频 + 导出 JSON | **待用户一次性终审** |

## 已确认事实

1. 可用视觉模型：Doubao endpoint；智谱 `glm-4.5v`；Aibox `glm-5.3-flash`。`glm-4.7`、`glm-5.3` 不可用作视觉。
2. 逐机位数量初标见 `data/gold/camera_counts_v0.json`，状态为 `ai-single-annotator-provisional`：由 AI 中枢对单帧目视计数，**不是人工金标准**。北 10 帧 `3,3,4,3,3,2,2,2,3,2`，南 10 帧 `3,4,5,5,5,5,4,4,3,3`，全部待用户终审。
3. Doubao 整帧在 20 帧全量中 16 帧总数完全正确（80.0%），MAE 0.25；累计漏计 4 辆、多计 1 辆。`count_v2` 为 15/20，没有提升基线。
4. `north_600` 整帧模型报 2，AI 初标为 4（待终审）；裁剪放大后可找回，但会拆分同一辆车。
5. 南机位车型有明显 `large` 偏置，必须做候选裁剪二次判定。
6. 终审材料已就绪：`review/index.html` 提供 20 个时刻的五帧证据、9 个通道存疑时刻的 ±15 秒视频、底边货厢口径选择与 JSON 导出；导出后由 `accuracy/evaluate_reviewed.py` 自动重算所有模型。
7. 通道裁剪提示词 `corridor_v1` 实测 13/20，低于整帧基线 16/20；但它把 `south_2600` 修正到 3，说明“底边货厢是否计入”会直接改变评测结论，必须先定口径。
6. 跨机位去重尚未完成，所有“合计”数字不能当唯一车辆真值。
7. 新发现：`north_600` 可通过顶部/中部/近景三段裁剪分别找到远端两辆蓝色货厢车；但三类模型对同一车体的拆分并不稳定，必须做候选合并与复核。
8. 当前界面：`all-sessions-can-see/assets/live/latest-desktop.png`，每 30 分钟自动重截。
9. 实测调试台（已合并）：`debug/viewer/lab.html`，逐帧显示预测/人工/差值、模型真实 bbox、同帧模型对照；本机常驻地址 `http://127.0.0.1:4178/debug/viewer/lab.html`。
10. Aibox `glm-5.3-flash` + count_v2 的单次 `north_600 = 4` **不可复现**：全量重跑同一帧返回 3（人工 4）。单样本胜利不能当作能力。
11. Aibox count_v2 全量实测 20/20 成功，但只有 10 条完全正确（50.0%），MAE 0.50；1 帧漏计、9 帧多计。它不适合当主力，只能作为独立复核/分歧探针。
12. Aibox 成功帧平均耗时 38.09 秒，24 次 HTTP 尝试中 4 次 504 后重试；实时性需在架构层单独评估。

## 合并记录

- PR #1 `debug/experience` 已合并：可重复的浏览器截图与独立预览页，无识别算法改动。
- PR #3 `debug/live-experience` 已合并：实测识别调试台，只画模型原始 bbox，截图自检通过。
- PR #2 `feat/web-workspace-v2` 已合并：真实开发集计数、双机位工作台、无伪造框。
- PR #4 `research/capacity-geometry` 已合并：单应标定、容量与不确定度。
- PR #5 `research/temporal-reid` 已合并：时序与跨机位实体消歧实测。
- PR #6 `research/event-timeline` 已合并：92 点全时段逐机位时间轴、24 点人工抽查与 9 张证据图；自动复核门控未能命中已确认的计数错误，只能作为证据底图。
- `main` 提交 `3b8d6a8`：留存 count_v2 提示词、三模型探针与 20 帧通道提示词实验证据。
- `main` 提交 `089ad3a`：新增视频复核台；把单帧 AI 初标正式降级为 `ai-single-annotator-provisional`，不再称人工金标准。

## 门禁

- 没有金标准证据的数字只标 `DEMO` 或 `pending_review`。
- 任何架构必须报告 exact match / MAE / 漏检 / 多计 / 车型错误 / 成本。
- 合并顺序：先冻结基线评测，再吸收改动；每次只合并一个 PR 并回归。

