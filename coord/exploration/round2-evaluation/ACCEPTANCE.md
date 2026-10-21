# 统一验收表

日期：2026-10-21。所有结果来自固定开发集；没有一条可升级为生产验收或泛化成绩。

## 路线状态

| 路线 | 证据口径 | 固定分母 | 有效/失败/拒答/缺失 | 核心结果 | 自动放行 | 判定 |
|---|---|---:|---|---|---|---|
| B r1 | `legacy_whole_vehicle` | 20 机位 | 20 / 0 / 0 / 0 | 18/20，MAE 0.100 | 三轮合计 54 放行，48 正确，**6 错** | 旧口径参照；生产 `REJECT_FOR_NOW` |
| B r2 | `legacy_whole_vehicle` | 20 机位 | 20 / 0 / 0 / 0 | 18/20，MAE 0.100 | 同上 | 同上 |
| B r3 | `legacy_whole_vehicle` | 20 机位 | 20 / 0 / 0 / 0 | 18/20，MAE 0.150 | 同上 | 同上 |
| Doubao Mini v2 | `legacy_whole_vehicle` | 20 机位 | 20 / 0 / 0 / 0 | 18/20，MAE 0.100；严格 schema 6/20 | 未报告 | `LEGACY_REFERENCE_ONLY`，不是 roof-only |
| Doubao Lite | 旧口径 | 20 机位 | 未运行 | **0/20, not_run** | 未测 | 无准确率或淘汰结论 |
| identity-assembly-v2 | `legacy_whole_vehicle` | 20 机位 + 10 时刻 | 20 / 0 / 0 / 0 | 机位 18/20；overlap 3/10，MAE 1.100；unique 2/10，MAE 1.300 | 6/10 放行，正确 1，**错误 5**；复核 4 | `REJECT_FOR_NOW`，装配负结果 |
| roof-only-v1 | `roof_only_v1` | 20 机位 | 13 / 7 / 0 / 0 | **6/20**，valid-only MAE 0.846154 | 0 自动放行；20 未报告 | `FAIL_CONTRACT`，当前配置淘汰 |
| part-relation-v2 | `roof_only_v1` 计划 | 4 个诊断样本 | 无结果 | 无 raw/metrics/REPORT | 未测 | `awaiting_public_artifacts` |
| causal-memory-v2 | roof-only 计划 | 20 机位 / 71 当前对象 | 无结果 | 无回放/metrics/REPORT | 未测 | `awaiting_public_artifacts` |
| round2-research independent-v1 | 新时刻，标签未完成 | 20 机位 | 未评分 | 不得按 0 分或未运行处理 | 未测 | `labels_pending` |

表中 `failed` 均留在固定分母内。`valid-only MAE` 只说明有效样本误差，不能美化 headline。B 三轮是相同 20 帧的重复运行，不是 60 个独立样本。

## 硬门禁

| 门禁 | B | Doubao Mini | identity | roof-only-v1 |
|---|---|---|---|---|
| 固定分母且无静默覆盖 | PASS | PASS | PASS | PASS |
| 状态明确分离 valid/failed/refused/missing | PASS | PASS | PASS | FAIL：7 个 schema 失败 |
| 实例列表长度 = 声明计数 | PASS | PASS（兼容口径） | PASS | 通过的位置结构；schema 契约失败 |
| 输入与 prompt hash | PASS：20/20 aisle | PASS | PASS | PASS |
| 跨机位公式 | 未提供 | 未提供 | PASS：10 时刻 | 不计算 |
| overlap / unique 完整测量 | `not measured` | `not measured` | 3/10、2/10 | 0/10 可评分 |
| 自动放行 0 个计数错误 | **FAIL：6 错** | 未报告 | **FAIL：5 错** | 0 放行，不能证明安全 |
| roof-only 证据契约 | 不适用 | 不适用 | 不适用 | **FAIL** |
| 独立新时段 | `not evaluated` | `not evaluated` | `not evaluated` | `not evaluated` |
| 对象级框/属性/身份 | `not measured` | `not measured` | `not measured` | `not measured` |

没有任何路线达到 `PASS_RESEARCH`。B 和 Mini 的计数成绩只能作为旧口径开发集参照；identity 为负结果；roof-only-v1 为契约失败。

## Doubao Mini 的严格 schema

Mini 的计数 headline 使用历史 B 兼容口径，保留 0–1000 坐标的 `/1000` 归一化；这只是与旧路线可比。独立严格 0–1 契约的结果是：

- 严格 schema valid：**6/20**
- 严格 schema 失败：14/20
- 严格有效且计数正确：**6/20**
- 原始坐标分布：`raw_0_1` 6，`raw_0_1000` 14

计数兼容通过不能写成 schema 通过。

## roof-only-v1

- 固定 20 分母：6/20 exact。
- valid 13、failed 7、refused 0、missing 0。
- valid-only MAE：0.846154；漏 10 单位/6 帧，多 1 单位/1 帧。
- 不设 schema 门槛的数字/fully-resolved 诊断：11/20；严格有效且计数正确：6/20；schema 失败但数字命中：5/20。
- 7 个失败全部在 south，模型把 `roof_kind` 写成字面量 `cab_roof|cargo_roof`。
- 6 个样本含 uncertain：8 组、12 个顶部观察；uncertain 不增加物理车数，且禁止自动放行。
- 输出结构共 73 个 roof observation、57 个 physical entity；structure checked，语义 accuracy `not measured`。

11/20 只是不计 schema 的数字诊断，不是官方有效成绩；不能覆盖 7 个契约失败。

## 明确不外推

- 不把 20 帧开发集成绩写成新时段或新视频泛化。
- 不把机位 count 正确写成 bbox、实例集合、物理组成、配对或身份正确。
- 不把 uncertain/拒答/复核率写成识别准确率。
- 不把历史初始化当作免费，也不把未公开耗时/内存填成 0。
- 不把旧整车 B、Mini、identity 追认成 roof-only。
- 不根据计数碰巧正确宣布顶部像素隔离已被证明。roof-only-v1 仍输入完整 aisle 图，只通过 prompt 限制证据。
