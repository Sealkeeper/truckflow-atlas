# 显式跨路线比较 v1

日期：2026-10-21。只消费已发布 metrics，**没有新增模型调用**。

## 20 帧路线（固定 N=20）

| 路线 | Count exact | Count MAE | Unique exact | Unique MAE | Overlap exact | Overlap MAE | 车辆 ID |
|---|---:|---:|---:|---:|---:|---:|---|
| clean-aisle | **16/20** | **0.25** | 未测 | 未测 | 未测 | 未测 | 未测 |
| joint-multiview | 13/20 | 0.45 | 1/10 | 1.3 | 6/10 | 0.4 | 未测 |

| 路线 | 自动放行 | 复核 | 调用 | 图像 | Token | 延迟均值 / p95 |
|---|---|---:|---:|---:|---:|---|
| clean-aisle | 未测 | 未测 | 20 | 20 | 67,027 | 15.864 / 21.27 s |
| joint-multiview | 0 正确 / 8 错误，覆盖 80.0% | 2/10（20.0%） | 10 | 20 | 62,178 | 26.613 / 35.027 s |

## 定向 3 窗口路线（固定 N=3，单独报告）

| 路线 | Count exact | Count MAE | 自动放行 | 复核 | 调用 | 图像 | Token | 延迟均值 / p95 |
|---|---:|---:|---|---:|---:|---:|---:|---|
| event-ledger | 1/3 | 0.667 | 1 正确 / 2 错误，覆盖 100% | 0/3 | 3 | 9 | 24,397 | 50.718 / 94.273 s |

**N=3 与 N=20 的样本集合不同，不构成同口径排名，不得合并求平均。** event 的 3 个点只对应 `north_600`、`north_2100`、`south_2600`；其同点 aisle 基线为 2/3。

## 工作流审计

| 路线 | 结论 | 硬失败 | 说明 |
|---|---|---:|---|
| clean-aisle | PASS | 0 | 无人工框、同帧答案或未来帧；失败保留在分母 |
| joint-multiview | PASS | 0 | 同刻南北双图；无未来帧 |
| event-ledger | FAIL | 2 | `north_2100` 窗口含 2130/2160，属于回顾性未来帧；账本跨快照续状态但有新增图像证据，记 WARN |

## 解读限制

1. `16/20` 是每机位可见货车总数完全正确，不代表车型、逐车框、车辆 ID 或跨机位身份正确。
2. clean-aisle 使用固定 aisle 裁剪；joint-multiview 使用南北原始全图。调用数和输入图像数可直接比，精度差距不能全部归因于“联合架构”本身。
3. joint-multiview 的 unique 数量正确率仅 1/10，overlap 6/10；原报告已给出 `t600` overlap 数字正确但对象错配的反例，所以 overlap 数量不等于跨机位配对正确。
4. joint-multiview 自动放行 8/10，但这 8 个时刻全部至少一项数量错误；协议门禁通过不等于视觉正确。
5. event-ledger 1/3 与该路线自己的同点 aisle 2/3 对比才有意义；不能拿 1/3 与全量 16/20 比较。

## 来源

- clean-aisle：`clean-aisle-baseline-v1.manifest.json` / `.metrics.json`
- joint-multiview：`joint-multiview-v1.summary.json`，源自公共 `coord/exploration/joint-multiview/metrics.json`
- event-ledger：`event-ledger-v1.summary.json`，源自公共 `coord/exploration/event-ledger/metrics.json`
- 适配字段已逐项校验；详见 `README.md` 的哈希表。
