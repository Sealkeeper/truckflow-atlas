# 独立复算差异与审计更正

本页只记录能从公共文件复现的差异。它不修改任何原路线 raw、summary 或用户标签。

## B：声明值一致，但生产门禁失败

- r1/r2/r3 的 exact 均为 18/20；MAE 分别为 0.100、0.100、0.150。
- 漏计（单位/帧）：r1 `0/0`、r2 `1/1`、r3 `2/1`；多计（单位/帧）：r1 `2/2`、r2 `1/1`、r3 `1/1`。
- `summary.json` 与 `RUNS_INDEX.json` 的 exact、MAE、漏多和失败字段在三位小数舍入范围内一致。
- 60 个运行样本中有 54 个自报放行；48 个计数正确，6 个错误。6 个错误帧没有一个被复核捕获。
- top-level 车辆框均在 0–1；`calls[].parsed` 中仍有 142 个框不在严格 0–1。两层不能混写。
- 180 个公共 raw 文件 hash 全部一致；实际使用的 20 张 aisle 输入 hash 20/20，prompt hash 一致。
- 公共 `full/far` 派生图缺失 36 张（19 far、17 full），因此只能声明 Aisle 输入核验通过，不能声明“所有变体输入均完整”。

本轮修正了两个审计实现问题：

1. `B_evidence_manifest.json` 的 9 行证据块把 truth 放在样本级 `block.truth`，原审计错误地与不存在的 `run.truth` 比较。现改为比较 raw truth 与样本级 truth，9/9 hash、计数、车辆列表、调用字段和 truth 均一致。
2. B 的实际模型输入只有 aisle。验收中的输入完整性现按 20/20 aisle hash 判定；未使用的 full/far 变体是否公开另列为 `unused_variants_complete=false`，不拿无关缺失否决 Aisle 输入。

这些修正只改变审计字段，不改变任何计数、误差或放行结果。

## Doubao Mini：计数对，schema 不对

- 固定 20 分母计数 18/20，MAE 0.100，与路线 summary 一致。
- 兼容计数使用历史 B 的 0–1000 归一化，20/20 可计分。
- 严格 0–1 schema 仅 6/20 有效，14/20 失败；严格有效且计数正确 6/20。
- 原始坐标分布为 `raw_0_1` 6 个、`raw_0_1000` 14 个。
- 20 个 raw attempts、输入和 prompt 审计通过；80/80 原始/attempt/started 文件 manifest 一致。
- Lite 是 `0/20, not_run`，不能推成模型能力差异。

## identity-assembly-v2：放行策略差异

结构复算与原路线声明一致：

- 机位计数 18/20，来自冻结 B r1，不是新检测收益。
- overlap 3/10，MAE 1.100；unique 2/10，MAE 1.300。
- 10 个 raw 产生 119 个北×南矩阵行：same 3、unknown 7、different 109。
- 133/133 证据文件 hash 一致。
- 原路线报告 6 个自动放行，其中正确 1、错误 5；复核 4。

唯一放行策略差异在 `t1800`：

- 原路线因 `review_required=true` 和 `unreliable_candidates` 实际送入复核。
- 简化独立门禁只按显式候选条件重算，得到该时刻“可放行”的候选。
- 因此 `release_gate_audit.independent_gate_candidates=7`、`reported_released=6`，差异 1 个时刻。

该差异是门禁策略审计，不是结构 schema 错误，不抹掉原路线真实复核决定，也不影响 3/10 overlap、2/10 unique 和 119 行矩阵。

## roof-only-v1：11 个数字命中不等于 11 个有效结果

- 固定 20 分母严格结果 6/20；valid 13、failed 7、refused 0、missing 0。
- 不计 schema 的原始/fully-resolved 数字诊断是 11/20。
- 7 个失败全部是 south，且都因 `roof_kind` 被写成字面量 `cab_roof|cargo_roof`。
- 其中 5 个样本的数字碰巧正确；这不能追认 schema 契约通过。
- 13 个 valid 中只有 6 个计数正确；valid-only MAE 0.846154。
- 6 个样本、8 组、12 个顶部观察处于 uncertain；uncertain 不增加物理车计数，也不允许自动放行。
- 输出结构 73 个 roof observation、57 个 physical entity；结构通过不等于顶面检测或分组正确。
- 20 张输入 20/20 hash 一致，prompt 一致，raw manifest 80/80，20 个请求可重建且 hash 一致。
- 禁用证据词在 reasoning 的“不要使用”自检中出现 13 次，正向使用疑点 0；这只说明词法审计结果，不能证明像素级未看下部。

完整 aisle 图仍是模型输入，`pixel_masking_implemented=false`。不能把 prompt 限制写成物理隔离。

## 共性边界

所有路线都只在 10 个开发时刻、南北两机位的 20 帧上复算。没有独立新时段标签，所以 `generalization: not evaluated`。机位、overlap、unique 三种分母和指标分别报告，互不代填。
