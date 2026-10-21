# Roof-only 评测修订：冻结预注册

冻结时间：2026-10-21。依据用户最新约束及公共
`coord/exploration/ROOF_ONLY_STEERING.md`。本修订只适用于标注为
`evidence_scope=roof_only` 的新输出；旧整车记录原样保留，不覆盖、不重写、不混算。

## 路线分层

| 分类 | 允许的结论 |
|---|---|
| `legacy_whole_vehicle` | 可复算历史计数/内部一致性，只能作为旧口径对照；不能声称符合新证据约束 |
| `legacy_roof_incidental` | 旧输出里偶有车顶/顶面字段，但 prompt/输入与计数口径未按新约束冻结；仍归旧口径 |
| `roof_only_v1` | 新冻结 prompt/输入/输出只用车顶、货厢顶面、顶部轮廓；可用于新车顶口径评测 |

旧 B、旧 identity-assembly-v2、doubao-v2 Mini 均为旧整车口径。Mini 的输入已看过整车外观，
即使包含顶面描述也不能追认成 roof-only。Lite 旧口径未运行，状态保持 `0/20, not_run`。

## 新输出硬契约

每个机位样本必须显式声明：

```json
{
  "sample_id": "north_5",
  "camera": "north",
  "time": 5,
  "evidence_scope": "roof_only",
  "predicted_count": 5,
  "physical_entities": [
    {
      "id": "P1",
      "component": "vehicle_or_composition",
      "observation_ids": ["R1", "R2"],
      "bbox_space": "aisle_norm_0_1",
      "roof_bbox": [0.28, 0.49, 0.55, 0.62],
      "top_state": "top_open",
      "evidence_tags": ["roof", "top_edge"],
      "identity_status": "unknown"
    }
  ],
  "roof_observations": [
    {
      "id": "R1",
      "bbox_space": "aisle_norm_0_1",
      "roof_bbox": [0.28, 0.49, 0.55, 0.62],
      "top_state": "top_open",
      "evidence_tags": ["roof", "top_edge"],
      "component": "unknown"
    }
  ]
}
```

- `predicted_count` 只表示用户物理车口径的估计；必须等于 `physical_entities` 长度，
  不等于 `roof_observations` 数量。车头顶与货厢顶是两个顶面观察，不天然是两辆物理车。
- `physical_entities` 的 `observation_ids` 必须引用本样本真实存在的
  `roof_observations` ID；引用缺失或重复 ID 直接报错。
- `roof_bbox` / `roof_polygon` 是顶部证据区域，不得命名为完整 `vehicle_bbox`。
- `top_state` 只能为 `top_closed`、`top_open`、`unknown`。敞口货厢用 `top_open`，
  不推断隐藏底盘、轮胎或车头连接。
- `evidence_tags` 只能来自 `roof`、`cargo_roof`、`top_edge`、`top_polygon`、
  `top_outline`、`aerial_shape`。出现 `plate`、`tire`、`tail_light`、`side_text`、
  `cab_front`、`connection` 等下部/外观/不可见关系证据，新路线样本判 contract failure。
- `component` 无法确认时写 `unknown`；组成不确定不得用过去数量补足，进入复核。
- 观察 ID 与物理车 ID 分层；同色、同尺寸、同文字或同一箱号都不自动证明同一/不同实体。

## 坐标双口径

先保留原预注册勘误：B 兼容计数口径按历史 `normalize_vehicles` 规则接受 `0–1000`
四元框除以 1000，并独立报告原始严格 `0–1` schema。两者不互相覆盖。

| profile | 目的 | 计分 |
|---|---|---|
| `count_compat_b` | 与旧 B/新 Mini 的计数可比 | 显式声明或历史兼容规则归一化后，要求 declared total = raw list = normalized list |
| `strict_norm_0_1` | 坐标 schema 硬契约 | 原始框必须全部在 `[0,1]` 且有效；不得事后“救回”严格分 |

新 roof-only 输出仍必须声明 `bbox_space`。没有声明时不得猜；`0–1000` 与 `0–1`
必须分别报告有效数。兼容计数的通过不能写成严格 schema 通过。

## 指标与门禁

1. 物理机位计数、unique、overlap 继续以用户终审计数为真值，不修改标签。
2. 单独报告 `roof_observation_count`、`physical_entity_count`、被合并的顶面观察数；
   这只是输出结构统计，不是顶面检测准确率。
3. 顶面 bbox/polygon、顶面实例身份、部件归属和跨机位同车没有完整 roof-only gold 时，
   一律 `not measured`；不得拿物理计数正确代替。
4. `unknown` 边界、`top_open` 无封闭顶、组成不明均不算自动放行；自报 confidence
   仍不构成可靠门禁。
5. 新路线自动放行要求用户计数真值 0 错误，并且无未解决 unknown/复核项；否则
   `RESEARCH_ONLY` 或 `REJECT_FOR_NOW`。
6. 旧整路口径记录只能标 `legacy_whole_vehicle`，新报告必须将旧/新结果分表。

## 当前执行状态

- 本轮评测仍为 **0 模型调用**，不发起任何整车外观或车顶新请求。
- doubao-v2 Mini 20 已完成：旧整车口径独立复算；Lite 0/20 未运行。
- identity-assembly-v2 10 请求已完成：保留为旧整车候选装配负结果。
- `part-relation-v2`、`causal-memory-v2` 只在新公共产物完整后适配；未完成时
  `awaiting_public_artifacts`，不替它们抽帧或调用模型。
- 新独立时刻只有人审页/标签未完成时，状态为 `labels_pending`。
