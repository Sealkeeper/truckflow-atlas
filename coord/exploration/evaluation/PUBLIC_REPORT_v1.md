# 纯净评测公开简报 v1

日期：2026-10-21

分支：`accuracy/clean-baseline`

PR：https://github.com/Sealkeeper/truckflow-atlas/pull/9

本轮只整理和审计已有结果，**没有新增任何模型调用**。

## 结论

在 20 个机位样本的开发集上，单视图 aisle 路线（固定裁剪，每机位一次 Doubao 视觉调用）的相机总数 exact 为 **16/20 = 80%**，MAE 为 **0.25**，工作流审计 **PASS**。

这里的 `16/20` 只表示“每个机位的可见货车总数完全正确”。它不是 100%，也不代表车辆 ID、车型分类、跨机位唯一集合、南北重合车辆数或自动放行策略准确。上述指标本轮均为 **未测**。

## 数据集状态

| 项 | 值 |
|---|---|
| 真值文件 | `accuracy/reviewed/user-final-review-v2-2026-10-21.json` |
| 真值 SHA256 | `735045af4055d2badae2c3bed1942c5a15c6a872ce548243cd52e6657fda971e` |
| 划分 | **dev（开发集）** |
| 机位样本 | 20（10 个时刻 × north/south） |
| 开发暴露 | 20 帧均已用于开发与检查 |

当前 20 帧不能当作盲测结果。盲测候选见 `BLIND_TEST_CANDIDATES_v1.md`，且候选尚未标注、尚未运行。

## 基线指标

| 指标 | 结果 |
|---|---:|
| 固定分母 N | 20 |
| 有效评估 valid / graded | 20 |
| exact | **16/20** |
| exact rate | **80.0%** |
| MAE（valid） | **0.25** |
| 漏计帧 | 4 |
| 多计帧 | 1 |
| failed | 0 |
| missing | 0 |

错误帧：

| 样本 | 人工真值 | 预测 | 误差 |
|---|---:|---:|---:|
| `north_300` | 3 | 2 | -1 |
| `north_5` | 5 | 4 | -1 |
| `north_600` | 4 | 2 | -2 |
| `south_2100` | 3 | 4 | +1 |

## 未测指标

| 能力 | 状态 | 原因 |
|---|---|---|
| 跨机位唯一车辆数 unique | 未测 | 路线只输出每机位计数，不输出唯一集合 |
| 南北重合车辆数 overlap | 未测 | 没有重合预测 |
| 自动放行 coverage / error | 未测 | 基线不含放行或复核策略 |
| 人工复核率 | 未测 | 基线不含复核调度 |
| 车辆 ID / 跨机位配对 | 未测 | 没有 ID 输出 |
| 车型准确率 | 未测 | 没有逐框车型真值与预测配对 |

summary JSON 中这些字段写 `null` 或 `status=not measured`；工具显示为 `未测`，不会当作 0 分或 100%。

## 统一比较工具

`compare_routes.py` 只读取命令行显式给出的 summary 文件，不扫描任何 session 目录。输入契约见 `SUMMARY_SCHEMA.md`。

它按固定分母展示：

- 相机计数 exact / MAE，同时显示 `N`、`failed`、`missing`；
- 唯一车辆集合与重合车辆的 exact / MAE；
- 自动放行正确数、错误数、覆盖率与错误率；
- 复核率、车辆 ID 状态；
- 调用数、图片数、token、平均与 p95 延迟；
- 工作流与数据完整性告警。

基线单文件的实际输出：

| Route | Split | Count exact | Count MAE | Unique exact | Unique MAE | Overlap exact | Overlap MAE | Vehicle ID |
|---|---|---|---|---|---|---|---|---|
| clean-aisle-doubao-v1 | dev | 16/20 (N=20; fail=0; miss=0) | 0.25 (n=20) | 未测 | 未测 | 未测 | 未测 | 未测 |

| Route | Auto release | Review | Calls | Images | Tokens | Latency mean/p95 | Audit / data notes |
|---|---|---|---:|---:|---:|---|---|
| clean-aisle-doubao-v1 | 未测 | 未测 | 20 | 20 | 67,027 | 15.864 / 21.27 s | workflow OK |

合成契约测试（未发布测试数据）：

- 1 个失败样本：显示 `15/19 (N=20; fail=1; miss=0)`，MAE `0.263 (n=19)`；
- 1 个缺失样本：显示 `15/19 (N=20; fail=0; miss=1)`；
- 缺少 `failed` 字段：显示 `未测`，并给出数据完整性告警；
- 人工红框进入模型输入：审计 `FAIL`；
- 仅续填上一帧数量且无新增图像证据：审计 `FAIL`。

## 工作流审计

`audit_agent_workflow.py` 对基线 summary 的结果：

| 检查 | 结果 |
|---|---|
| 人工红框进入模型输入 | PASS（否） |
| 同帧人工标注进入检索上下文 | PASS（否） |
| 使用未来帧 / 未来观察 | PASS（否） |
| 检索范围 | PASS（`none`） |
| 仅续填上一帧数量 | PASS（否） |
| 调用失败被跳过 | PASS（否） |
| 失败保留在固定分母 | PASS |
| 固定分母一致性 | PASS（N=20, valid=20, failed=0, missing=0） |

审计结论：**PASS，0 个硬失败，0 个未测检查**。

## 公共发布包

公共入口：

`all-sessions-can-see/coord/exploration/evaluation/`

| 文件 | 内容 |
|---|---|
| `README.md` | 公共入口、分母规则、哈希与使用方式 |
| `clean-aisle-baseline-v1.manifest.json` | 固定 20 样本：sample_id、路径、SHA256、字节数、真值、预测、误差、模型、耗时 |
| `clean-aisle-baseline-v1.metrics.json` | `truckflow-route-summary-v1` 指标，可直接作为比较输入 |
| `clean-aisle-baseline-v1.raw-list.json` | 20 个运行文件的精简清单与 SHA256 |
| `joint-multiview-v1.summary.json` | 从公共 joint-multiview metrics 适配的显式 summary |
| `event-ledger-v1.summary.json` | 从公共 event-ledger metrics 适配的显式 summary |

manifest 生成器已逐项核验：

- 20 个唯一 `sample_id`，南北各 10；
- 20 个文件 SHA256 与评测输出一致；
- 每个文件恰好一次成功运行，解析总数等于评测预测；
- 真值合计 69、预测合计 66、绝对误差合计 5；
- 运行目录中无额外样本、无 grid/非 aisle 文件、无缺失文件；
- manifest SHA256 `aa104c5fe03c1b23ced24e3a036b80d7779d77910fcc89ad3db7793bad0e3d5b`。

旧的 `accuracy/runs/_baseline_check.json` 报 17/20，但混入了其他视图并被同名文件覆盖；例如 `north_300` 旧值为 3、纯 aisle 为 2，`north_5` 旧值为 3、纯 aisle 为 4。该文件不再作为基线。

两条外部路线的显式比较结果：

| 路线 | 固定分母 | 相机计数 exact | MAE | unique | overlap | 自动放行 |
|---|---:|---:|---:|---:|---:|---|
| clean-aisle | 20 | **16/20** | **0.25** | 未测 | 未测 | 未测 |
| joint-multiview | 20 | 13/20 | 0.45 | 1/10 | 6/10 | 8 次放行 / 0 正确 |
| event-ledger | **3** | 1/3 | 0.667 | 未测 | 未测 | 3 次放行 / 1 正确 |

event-ledger 的 3 个定向窗口与 20 帧不是同一分母，单独输出，不合并排序。

统一审计对三条路线的结论：

- clean-aisle：PASS；
- joint-multiview：PASS；
- event-ledger：FAIL。其 `north_2100` 窗口同时看到 2130/2160，属于回顾性未来帧；原报告已明确该点不能作为因果流式准确率。

## 盲测候选

`BLIND_TEST_CANDIDATES_v1.md` 提出 10 个留出时刻、20 个机位样本：

`0060, 0180, 0420, 0750, 1050, 1350, 1650, 1950, 2250, 2550` 秒。

最小批次为 B01、B04、B07、B10，共 4 个时刻 / 8 个机位样本，报告时须标注 `blind_mini`。这批仍来自同一场景、同一视频，只能验证时间窗口泛化，不能替代跨场地泛化。

盲测前必须冻结并隐藏候选帧的人工标注、车辆数、未来观察和记忆库内容。逐车红框只能用于评估与解释，不能进入模型输入。

## 计数口径的未决问题

用户逐框证据已确认按独立货厢/车体计数，牵引车与挂车没有重复计数；此前“南侧 5 应为 3”的推断已撤回。

仍有两个边界问题需要用户裁决，当前真值未改动：

1. `north_5`：左侧远端货厢列是否全部属于要统计的通道；
2. `south_900 / 1200 / 1500 / 2600`：底边红色货厢是否在正式通道范围内。

## 产物

| 内容 | 路径 |
|---|---|
| 20 帧干净运行 | `accuracy/runs/aisle_clean/` |
| 评测输出 | `accuracy/reviewed/evaluation-clean-v1.json` |
| 基线报告 | `accuracy/REPORT_clean_baseline_v1.md` |
| 错误证据图 | `accuracy/evidence/clean_baseline/errors_contact.jpg` |
| 运行来源与补跑记录 | `accuracy/runs/aisle_clean/_provenance.json` |
| summary JSON | `coord/exploration/evaluation/clean-aisle-baseline-v1.summary.json` |
| summary 契约 | `coord/exploration/evaluation/SUMMARY_SCHEMA.md` |
| 比较工具 | `coord/exploration/evaluation/compare_routes.py` |
| 工作流审计工具 | `coord/exploration/evaluation/audit_agent_workflow.py` |
| 比较结果 | `coord/exploration/evaluation/route_comparison_v1.md` |
| 审计结果 | `coord/exploration/evaluation/workflow_audit_v1.md` |
| 盲测候选 | `coord/exploration/evaluation/BLIND_TEST_CANDIDATES_v1.md` |
| 公共 20 文件 manifest | `all-sessions-can-see/coord/exploration/evaluation/clean-aisle-baseline-v1.manifest.json` |
| 公共 metrics / raw list | `all-sessions-can-see/coord/exploration/evaluation/` |
| 跨路线比较 | `all-sessions-can-see/coord/exploration/evaluation/CROSS_ROUTE_v1.md` |

复现比较与审计：

```powershell
python coord/exploration/evaluation/compare_routes.py `
  --summary coord/exploration/evaluation/clean-aisle-baseline-v1.summary.json `
  --out-md coord/exploration/evaluation/route_comparison_v1.md `
  --out-json coord/exploration/evaluation/route_comparison_v1.json

python coord/exploration/evaluation/audit_agent_workflow.py `
  --summary coord/exploration/evaluation/clean-aisle-baseline-v1.summary.json `
  --out-md coord/exploration/evaluation/workflow_audit_v1.md `
  --out-json coord/exploration/evaluation/workflow_audit_v1.json
```

## 限制声明

- 20 帧是开发集，`16/20` 不是盲测泛化结果。
- 只评测每个机位可见货车总数；unique、overlap、release、review、ID、车型全部未测。
- 南北机位数量不能直接相加当作唯一车辆数。
- 基线 19 个成功文件是已有 aisle 运行的逐字节副本；`south_1200` 为同裁剪补跑成功。原始 `ProxyError` 失败记录保留在 provenance 中。
- 当前 PR 未合并。
