# 公共评测入口 v1

日期：2026-10-21

发布方：`clean_eval`

分支：`accuracy/clean-baseline`

PR：https://github.com/Sealkeeper/truckflow-atlas/pull/9

本轮只发布已有结果的 manifest、指标和显式比较产物，**没有新增模型调用**。

## 唯一正式基线

正式基线是纯 `aisle` 视图、固定 20 个机位样本：

| 文件 | 用途 |
|---|---|
| `clean-aisle-baseline-v1.manifest.json` | 20 个样本的固定清单：路径、SHA256、字节数、真值、预测、误差、模型与耗时 |
| `clean-aisle-baseline-v1.metrics.json` | `truckflow-route-summary-v1` 指标，可直接作为比较工具输入 |
| `clean-aisle-baseline-v1.raw-list.json` | 20 个原始运行文件的精简清单与 SHA256 |
| `raw/` | 20 个正式 aisle 原始运行文件与 `_provenance.json` |
| `evaluation-clean-v1.json` | 逐样本评测输出副本 |
| `truth-canonical-v1.json` | 10 时刻 canonical 真值内容与来源一致性 |
| `BASELINE_REPORT_v1.md` | 纯 aisle 基线详细报告副本 |
| `build_public_baseline.py` / `build_canonical_truth.py` | manifest 与 canonical 真值生成器（只读显式输入） |

| 指标 | 结果 |
|---|---:|
| 固定 N | 20 |
| valid | 20 |
| exact | **16/20（80.0%）** |
| MAE | **0.25** |
| 漏计 / 多计 | **4 units / 3 frames** 与 **1 unit / 1 frame** |
| failed / missing | 0 / 0 |

真值合计 69，预测合计 66，绝对误差合计 5。

### 真值 canonical 内容

用户真值文件 SHA256 `7350...` 与 joint 路线声明 label SHA256 `c3fd...` 是不同文件/序列化。按 10 个时刻的 `north/south/overlap/unique` 规范化后：

`canonical_sha256 = 78f255b1ae37463e2b36e15befb1ff8092ca87c2c6e946979d880f42cf0e5397`

用户真值、joint 逐行真值、event 三点子集和 9 张用户红框计数全部一致。未改动任何标签。详见 `truth-canonical-v1.json`。

### 旧 17/20 不能作为基线

旧 `accuracy/runs/_baseline_check.json` 报 `17/20`，但它混入了 `grid_aisle` 等视图，且同名样本被后读文件覆盖。最直接的差异：

| 样本 | 旧混合视图 | 纯 aisle | 用户真值 |
|---|---:|---:|---:|
| `north_300` | 3 | 2 | 3 |
| `north_5` | 3 | 4 | 5 |

纯 aisle 固定 20 文件的正确结果是 **16/20**。不要再用 17/20 或旧 `_baseline_check.json` 做验收或对比。

## 文件契约

- 运行目录固定为 `accuracy/runs/aisle_clean/`，恰好 20 个 `*_aisle.json`，另有且仅有 `_provenance.json` 元数据；
- 公共包把这 20 个正式文件复制到 `raw/`，manifest 只写 `raw/<file>`，不指向私有 session；
- PR 分支内的正式原件仍在 `accuracy/runs/aisle_clean/`，与公共 `raw/` 逐字节一致；
- 每个样本只有一次成功运行；
- 拒绝 `grid_aisle`、`grid_grid_aisle` 及其他视图；
- 重复 `sample_id` 直接报错；
- `manifest.json` 中 `directory_check` 记录实际扫描结果，`extra_sample_files`、`missing_sample_files`、`non_aisle_sample_files` 均为空；
- 失败和缺失必须留在固定分母，不能通过删除样本提高 exact rate。

本会话已生成并核验以上契约；20 个文件哈希与 `evaluation-clean-v1.json` 逐条一致。

## 显式跨路线比较

`joint-multiview-v1.summary.json` 与 `event-ledger-v1.summary.json` 是从公共目录已有 `metrics.json` 适配的 `truckflow-route-summary-v1` 文件，未调用模型，未改动原路线目录。适配字段已逐项对照源文件数值。

| 路线 | 固定分母 | 相机计数 exact | MAE | unique | overlap | 自动放行 |
|---|---:|---:|---:|---:|---:|---|
| clean-aisle | 20 | 16/20 | 0.25 | 未测 | 未测 | 未测 |
| joint-multiview | 20 机位 / 10 时刻 | 13/20 | 0.45 | 1/10，MAE 1.3 | 6/10，MAE 0.4 | 8 次放行，0 正确，8 错误 |
| event-ledger | **3** | 1/3 | 0.667 | 未测 | 未测 | 3 次放行，1 正确，2 错误 |

**event-ledger 的 N=3 是三个定向窗口，不是 20 帧的子集分数，不能与 20 帧路线合并排序或求平均。** 它的比较文件单独输出。

20 帧对比见 `route_comparison_20-v1.md`；event 三点见 `route_comparison_event3-v1.md`。

## 工作流审计

| 路线 | 结论 | 说明 |
|---|---|---|
| clean-aisle | PASS | 无人工框/同帧标注/未来帧输入；无数量续填；失败计入分母 |
| joint-multiview | PASS | 同刻南北双图，无未来帧；固定 N=20 |
| event-ledger | FAIL | 3 个窗口中 `north_2100` 同时看到 2130/2160，属于回顾性未来帧；另有带新增证据的账本续状态 WARN |

event 的未来帧问题不影响其“不可作为因果流式准确率”的原报告结论；这里只是用统一审计工具把它显式化。

## 使用

```powershell
python compare_routes.py `
  --summary clean-aisle-baseline-v1.metrics.json joint-multiview-v1.summary.json `
  --out-md route_comparison_20-v1.md `
  --out-json route_comparison_20-v1.json

python compare_routes.py `
  --summary event-ledger-v1.summary.json `
  --out-md route_comparison_event3-v1.md `
  --out-json route_comparison_event3-v1.json

python audit_agent_workflow.py `
  --summary clean-aisle-baseline-v1.metrics.json
```

工具只读取命令行显式给出的文件，不扫描任何 session 目录。缺失字段显示 `未测`，不会当作 0。

## 关键哈希

| 内容 | SHA256 |
|---|---|
| 用户真值 `user-final-review-v2-2026-10-21.json` | `735045af4055d2badae2c3bed1942c5a15c6a872ce548243cd52e6657fda971e` |
| 评测输出 `evaluation-clean-v1.json` | `7f5aedd22da7de94fde7927c61e7621daf7069d9ad6a53da6900f04e2124e885` |
| 20 文件 manifest | `6fa466dfaddc9443cae2fe65e0dc6975c31207a4fd4096fe206e2c85859806d1` |
| raw list | `1305593fe784ac398a9f7c7ae74ede03529348c2faae33e9821280324e9647c5` |
| run set | `44162e6dc763440d94152dbcac394e04506402c9830a8d2fba06025d998fe2e7` |
| 真值内容 canonical | `78f255b1ae37463e2b36e15befb1ff8092ca87c2c6e946979d880f42cf0e5397` |
| joint-multiview 源 metrics | `d964870dd78774b94065ac61c245545bf3772da7d46436f8047ad4f6ed61ed78` |
| event-ledger 源 metrics | `efb7fe453bf41e477377472df6a5a6a3797b106b769fd5722676f7e240eb5f2b` |

## 边界

- 20 帧是 **dev 集**，不是盲测；`16/20` 不是泛化准确率。
- 只测每机位可见货车总数；车辆 ID、车型、跨机位唯一集合、重合对象配对、自动放行与复核指标未测或按来源单独报告。
- 南北数量不能相加当作唯一车辆数。
- 标签未见候选见 `BLIND_TEST_CANDIDATES_v1.md`；公开 60 秒网格、人工复核和事件窗口已审计，当前没有真正的新视频盲测。
- PR #9 未合并。
