# Canonical 输出与坐标适配

统一评测入口是 `tools/evaluate_round2.py`，核心校验和计分在 `tools/core.py`。所有 adapter 都必须显式声明证据口径和坐标空间；评测器不猜尺度、不按样本名修正、不用真值补空值。

## 顶层文档

```json
{
  "schema": "round2-canonical-output-v1",
  "evidence_scope": "legacy_whole_vehicle",
  "samples": [],
  "times": [],
  "workflow": {},
  "release_unit": "camera"
}
```

`samples` 也可由 `predictions` 提供，但 adapter 应优先输出 `samples`。`samples` 和 `times` 都必须是列表。

### 机位样本

```json
{
  "sample_id": "north_5",
  "camera": "north",
  "time": 5,
  "status": "valid",
  "predicted_count": 5,
  "bbox_space": "aisle_norm_0_1",
  "vehicles": [
    {
      "id": "N1",
      "bbox": [0.28, 0.49, 0.55, 0.89],
      "bbox_space": "aisle_norm_0_1"
    }
  ],
  "release_decision": "review"
}
```

- `camera` 只能是 `north` 或 `south`；`time` 是非负整数。
- `status` 只能是 `valid`、`failed`、`refused`、`missing`。`ok/success` 映射到 `valid`，`error/invalid` 映射到 `failed`，`abstain/refusal` 映射到 `refused`，`not_run/awaiting` 映射到 `missing`。
- `predicted_count` 必须是明确非负整数；valid 样本缺少计数会失败，不会用实例列表长度回填。
- 旧整车路线使用 `vehicles`，也可适配 `instances` 或 `objects`。roof-only 使用 `physical_entities`。
- 每个实例要有稳定且样本内唯一的 `id`。重复 ID 只让该样本失败，不覆盖前一个实例。
- 实例可单独声明 `bbox_space`；否则继承样本级空间。没有声明就是失败，不从数值大小猜测。
- 声明计数、原始实例列表长度和解析后实例列表长度必须一致；公式相等只证明内部一致，不证明框语义正确。

### 时刻记录

跨机位的 overlap/unique 使用独立 `times`：

```json
{
  "time": 5,
  "status": "valid",
  "overlap": 1,
  "unique": 7,
  "matches": [{"north_id": "N1", "south_id": "S1"}],
  "release_decision": "review"
}
```

- 若提供 `matches`，overlap 必须等于去重后的配对数量，且 ID 必须存在于对应机位样本。
- unique 必须满足 `N + S - overlap`。
- 缺标签、失败、拒答和缺失都保留在固定分母；MAE 只在可评分样本上计算并单列 `valid_N/scored_N`。
- 重复 time、重复 `(time,camera)`、重复 `sample_id` 或重复 `(north_id,south_id)` 都会显式报错。

## 坐标空间

| `bbox_space` | 原始坐标 | 统一映射 |
|---|---|---|
| `aisle_norm_0_1` | aisle 归一化 0–1 | `x=350+520u`，`y=960v` 到 1280×960 |
| `aisle_int_0_1000` | aisle 整数 0–1000 | 先除以 1000，再按 aisle 映射 |
| `aisle_pixel_1040x1920` | aisle 输出像素 | 先除以 1040/1920，再按 aisle 映射 |
| `full_norm_0_1` | 完整图归一化 0–1 | 乘 1280/960 |
| `full_pixel_1280x960` | 完整图像素 | 直接使用 |

严格 profile `strict_norm_0_1` 要求原始坐标全部位于 `[0,1]`、宽度和高度为正，且声明空间与内容一致。

历史 `count_compat_b` 是单独适配的兼容口径，只用于和旧 B/Mini 逐样本 count 对照。它按照冻结的历史规则接受 `0–1000` 整数框并除以 1000；该兼容通过不能当成严格 schema 通过，也不能默认套到新路线。

## Roof-only 扩展

roof-only 样本必须显式写：

```json
{
  "sample_id": "north_5",
  "camera": "north",
  "time": 5,
  "evidence_scope": "roof_only",
  "predicted_count": 1,
  "roof_observations": [
    {
      "id": "R1",
      "bbox_space": "aisle_norm_0_1",
      "roof_bbox": [0.28, 0.49, 0.55, 0.62],
      "top_state": "top_open",
      "evidence_tags": ["roof", "top_edge"],
      "component": "unknown"
    }
  ],
  "physical_entities": [
    {
      "id": "P1",
      "component": "vehicle_or_composition",
      "observation_ids": ["R1"],
      "identity_status": "unknown"
    }
  ],
  "uncertain_roof_groups": [],
  "release_decision": "review"
}
```

### 顶部观察

- `roof_bbox` 或 `roof_polygon` 必须是顶部证据区域，而不是完整车辆框。
- `top_state` 只能是 `top_closed`、`top_open`、`unknown`。
- `evidence_tags` 非空，只允许 `roof`、`cargo_roof`、`top_edge`、`top_polygon`、`top_outline`、`aerial_shape`。
- `plate`、`license_plate`、`tire`、`wheel`、`tail_light`、`side_text`、`cab_front`、`connection`、`trailer_hitch`、`body_side` 等下部/外观/不可见关系标签判 contract failure。
- 一个车头顶与一个货厢顶可以是两个 roof observation，但必须通过 `observation_ids` 归入一个 physical entity；观察数不等于物理车数。
- 顶部观察 ID 必须在本样本唯一。

### 物理实体与 uncertain

- `predicted_count` 只能等于 `physical_entities` 长度；不能等于 roof observation 数。
- 每个 roof observation 必须且只能归属一个 confirmed physical entity **或** 一个 uncertain group。
- `uncertain_roof_groups` 的元素形如 `{"roof_ids": ["R2"], "reason": "..."}`；读取器也兼容 `uncertain` 和 `observation_ids` 别名，但新 adapter 应使用显式名称。
- uncertain 组不增加物理车计数。`0` 个 confirmed physical entity 加 uncertain 是合法结构，前提是状态为复核且不自动放行。
- `component` 为 `cab_roof`、`trailer_roof`、`cab` 或 `trailer` 的单部件实体必须有非空 `grouping_basis`。
- `identity_status` 只能是 `unknown`、`provisional`、`confirmed`。没有逐实例 gold 时这三者都只做结构审计，不产生身份准确率。
- 出现 uncertain、顶部边界 unknown 或组成 unknown 时禁止 `auto_release`。

### 放行语义

`release_decision` 推荐字符串 `auto_release`、`review`、`refused`。布尔值 `true/false` 分别映射到放行/复核；也兼容 `auto_release` 和 `gate.decision` 字段。

放行只按显式决定计分。模型自报 `confidence`、`visibility=full`、`checked=true` 或 `possible_miss=false` 都不是放行门禁。truth 有误的样本被自动放行即计一个 release error。

## 成本与工作流

样本可提供：

- `call_count` 或 `calls`；若为列表，按实际调用数计。
- `input_images` 或 `images`；同上。
- `tokens_total` 或 `tokens`。
- `latency_total_s` 或 `latency_s`。

顶层 `cost.initialization` 与 `cost.online` 分开；初始化未公开时保持 `null`，不填 0。`cost.concurrency`、实际墙钟和峰值内存分别记录。

`workflow` 必须显式给出人工框是否进入模型、同帧标注是否暴露、是否看未来帧、是否续填数量、失败是否跳过、记忆检索范围和失败是否留在分母。缺字段按未通过处理，不把沉默当清白。

## 与公共路线的关系

- B/Mini/identity 的 adapter 均标记 `legacy_whole_vehicle`。
- roof-only-v1 标记 `roof_only_v1`，但完整 aisle 图仍输入模型；`pixel_masking_implemented=false`，prompt 限制不等于像素隔离。
- 旧输出的 incidental roof 字段不能迁移成新 roof-only 结果。
- 新路线必须使用新 run ID；改 prompt、模型、输入或 schema 后不得覆盖旧 run 或合并计分。
