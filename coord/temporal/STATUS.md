# 时序与跨机位实体消歧状态

分支：`research/temporal-reid`

实验提交：`8d0c1c6`；PR：https://github.com/Sealkeeper/truckflow-atlas/pull/5（保持打开，不合并）。

状态：实验完成，路线结论为“自动放行 no-go；复核辅助条件性 go”。

## 已完成

- 从两路原始视频抽取 6 个冻结观测点的 `t-10s / t / t+10s`，共 18 帧。
- 比较整帧、过道裁剪、三帧时序条、候选 contact sheet、跨机位唯一车辆图。
- 使用 Doubao、Aibox GLM-5.3-flash、智谱 GLM-4.5V 的实测响应；所有原响应、失败、token 和延迟已归档。
- 建立 `data/gold/temporal_gold.json`，明确区分已核实总数与 provisional 车型。
- 输出 `data/results/metrics.json`、`data/results/per_observation.csv`。

## 核心结果

- Doubao 过道裁剪：总数 raw exact 4/6，MAE 0.333；全策略 review-free full exact 最高仅 1/6。
- 三帧时序条未修复 north_600/south_900/south_1200 的漏计。
- contact sheet 双模型一致自动覆盖 0/6，review 100%。
- 同一时刻 naive 跨机位相加在 t600/t1200 分别多计 2 辆、2 辆；Aibox 实体图得到唯一数 7/6 但全部 review。
- 16 个正负配对探针仅 4 个完全答对，review 16/16。

## 接口与证据

- 报告：`research/temporal_reid/ROUTE_REPORT.md`
- 指标：`data/results/metrics.json`
- 金标准：`data/gold/temporal_gold.json`
- 候选：`data/candidates.json`
- 原响应：`data/runs/primary/`、`data/runs/confirm/`、`data/runs/pair_probes/`

## 阻塞与下一步

- 车型金标准尚需按准确率章程做双人独立标注与裁决；当前车型指标仅用于漂移诊断。
- 跨机位实体配对目前只能作为 review 门禁；若要提升自动率，需要用更多可复核的成对证据，而不是扩大提示词或凭数量平滑。
- 未实测任何 100% 准确率，不得对外声明。
