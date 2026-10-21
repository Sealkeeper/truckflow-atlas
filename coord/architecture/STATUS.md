# architecture 会话状态

更新时间：2026-10-21

工作区：`sessions/architecture_challenger`

分支：`research/architecture-challenge`

## 已完成

- 五条架构代码可复跑：A 透视条带、A′ 紧贴纵向窗口、B 递归树、
  C 场景图、D 整帧后置审稿。
- 五帧 `north_300, north_600, south_600, north_1200, south_1200` 全部跑完；
  原始 prompt、回答、reasoning、usage、失败和证据图均已落盘到
  `research/architecture_challenge/runs/` 与 `evidence/`。
- 已切换到人工复核真值
  `all-sessions-can-see/accuracy/reviewed/user-final-review-v2-2026-10-21.json`；
  `camera_counts_v0.json` 只保留为车型/边界的诊断标签。
- 修复共享去重闭环：合并后重算候选并继续提出跨窗相邻对；修复
  `is_truck=false` 的低置信负例泄漏；收紧 A/B 裁剪，避免邻车污染车型判断。
- 新增 `src/evaluate_architectures.py`、`src/render_evidence.py` 和最终报告。

## 当前结果（五帧诊断集，人工 v2 总数）

| 路线 | 总数 exact | MAE | 漏/多 | Token | Wall |
|---|---:|---:|---:|---:|---:|
| 整帧 Doubao 基线 | 3/5 | 0.600 | 3/0 | 18,299 | 79.1 s |
| A | 2/5 | 0.600 | 1/2 | 129,196 | 417.2 s |
| **A′** | **4/5** | **0.200** | **0/1** | 143,325 | 544.1 s |
| B | 1/5 | 1.000 | 1/4 | 291,099 | 1,166.5 s |
| C | 2/5 | 0.800 | 4/0 | 67,228 | 224.8 s |
| D | 3/5 | 0.600 | 3/0 | 94,346 | 339.1 s |

20 帧整帧基线（人工 v2）为 16/20 exact、MAE 0.300、漏 5、多 1。
纯 aisle 单裁剪基线按中央复核口径为 15/19（`south_1200` 失败），不是 17/20。

## 建议

保留 A′ + 迭代语义去重，进入 20 帧回归；用 C 的 `part_of`/`queue_index`
作为车头/挂车关系层；B 和 D 不作为独立架构继续投入。

## 阻塞/风险

- 只有 Doubao 端点稳定可用；智谱图像请求被拒绝，AIBox GLM 不稳定。
- 单次温度 0 仍有随机性；同一 far 裁剪重复调用出现 1/2/3 个候选。
- A′ 的 `south_600` 仍多 1：红色车头与“灰色货厢 + 红色车头”被当成两辆。
- 人工 v2 只有总数，没有车型拆分；不能报告人工车型准确率。
- 尚未完成 20 帧架构回归、跨机位唯一实体和重复运行稳定性测试。

## 需要的协作

1. 中枢提供/确认 20 帧人工车型真值，或明确车型只进入 `review`。
2. 确认 `south_600` 车头/挂车口径；不要把该帧的 +1 通过提示词偶然压掉当成能力。
3. 在 20 帧回归通过前，不把 A′ 自动总数合并进主流水线。
