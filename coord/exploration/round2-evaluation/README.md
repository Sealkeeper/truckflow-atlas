# Round 2 独立评测公共包

日期：2026-10-21（北京时间）。负责：`round2_evaluator`。

本包只做公开产物、原图和用户终审计数的离线复算。评测器本轮新增 **0 次模型调用、0 次真值写入、0 次数据底座写入、0 次其他路线源码修改**。`roof-only-v1` 的 20 次模型调用是路线已完成的公共结果，本包只读取并审计，不把它们算作评测器调用。

制作本包时的仓库基准为 `main@3bb924594b25e839d222b7d886946bd6b84d75d8`。公共目录已有大量其他会话的未提交产物；本包不把它们混入提交或计分。

## 先看结论

| 路线 | 证据口径 | 固定分母结果 | 关键门禁 | 当前判定 |
|---|---|---:|---|---|
| 单遍 B r1 | `legacy_whole_vehicle` | **18/20** | 60 个运行样本中自动放行 54，**6 错** | 旧口径计数研究参照；生产 `REJECT_FOR_NOW` |
| 单遍 B r2 | `legacy_whole_vehicle` | **18/20** | 同上 | 同上 |
| 单遍 B r3 | `legacy_whole_vehicle` | **18/20** | 同上 | 同上 |
| Doubao Mini v2 | `legacy_whole_vehicle` | **18/20** | 严格 0–1 schema 仅 **6/20** | `LEGACY_REFERENCE_ONLY`，不是 roof-only |
| Doubao Lite | 旧口径 | **0/20, not_run** | 未发起 | 无准确率结论 |
| identity-assembly-v2 | `legacy_whole_vehicle` | 机位 18/20；overlap 3/10；unique 2/10 | 放行 6，正确 1，**错误 5** | 装配负结果，`REJECT_FOR_NOW` |
| roof-only-v1 | `roof_only_v1` | **6/20**；valid 13，failed 7 | 7 个 schema 失败；0 放行 | `FAIL_CONTRACT`，当前配置淘汰 |
| part-relation-v2 | 新协议已计划 | 无结果 | 无 raw/metrics/REPORT | `awaiting_public_artifacts` |
| causal-memory-v2 | 新协议已计划 | 无结果 | 无 raw/metrics/REPORT | `awaiting_public_artifacts` |
| round2-research independent-v1 | 新时刻 | 20 帧已准备 | 人工标签未完成 | `labels_pending` |

B 三轮是同一 20 帧的重复运行，**不是 60 个独立样本**。20 个机位样本来自 10 个开发时刻的南北两机位；overlap/unique 的固定分母是 10 个时刻。所有表里的泛化状态均为 `generalization: not evaluated`。

这些分数只覆盖用户终审口径下的机位物理车计数，以及部分路线的跨机位数量/装配输出。除特别说明外，bbox、顶面实例、车型大小、属性、OCR、跨机位身份、ID precision/recall/IDF1 均为 `not measured`。数量碰巧正确不能替代这些对象级验收。

## 公开文件

| 文件 | 用途 |
|---|---|
| `PLAN.md` | 冻结评测计划 |
| `ROOF_ONLY_AMENDMENT.md` | roof-only 冻结修订与硬契约 |
| `ACCEPTANCE.md` | 统一验收表、门禁和禁止外推项 |
| `STATUS.md` | 各路线完成、淘汰、等待和待标状态 |
| `DIFFERENCES.md` | 独立复算与公共摘要/原报告的可证差异 |
| `ADAPTERS.md` | canonical 输出、坐标、roof-only uncertain 适配规则 |
| `TEST_RESULTS.md` | 评测器单元测试结果和覆盖边界 |
| `results/*.json` / `results/*.md` | 机器结果、机器摘要和原始审计明细 |
| `tools/*.py` | 只读离线复算器；不读取任何其他 session |
| `tools/tests/test_core.py` | 评测核心测试 |

`results/b-input-audit.json` 保留 36 个未公开的 `full/far` 派生图缺口记录。B 的实际模型输入是 20 张 `aisle` 图，20/20 hash 一致；没有把未使用的 `full/far` 变体伪称为已核验。

公共 JSON 只做过展示路径清理：仓库绝对根替换为 `repo://`，临时输出路径替换为 `private://redacted-temp`。数值、哈希、样本 ID、状态和审计结论未改。所有 JSON 已扫描，不含 `ARK_API_KEY`、`Authorization`、`Bearer`、`secret`、`password`、`C:\Users` 或仓库绝对根。

## 复现

所有命令只读公开文件和用户终审计数，不访问网络。工作目录为 `coord/exploration/round2-evaluation/tools`：

```powershell
$truth = '..\..\..\..\accuracy\reviewed\user-final-review-v2-2026-10-21.json'

python .\recompute_b.py `
  --single-pass-root ..\..\single-pass `
  --truth $truth `
  --out-json ..\results\b-recompute.json `
  --out-md ..\results\b-recompute.md `
  --out-input-audit ..\results\b-input-audit.json `
  --out-raw-audit ..\results\b-raw-audit.json `
  --out-evidence-audit ..\results\b-evidence-audit.json

python .\recompute_doubao_v2.py `
  --benchmark-root ..\..\doubao-v2-benchmark `
  --truth $truth `
  --out-json ..\results\doubao-v2-recompute.json `
  --out-md ..\results\doubao-v2-recompute.md `
  --out-coordinate-audit ..\results\doubao-v2-coordinate-audit.json

python .\recompute_identity_v2.py `
  --identity-root ..\..\identity-assembly-v2 `
  --single-pass-root ..\..\single-pass `
  --truth $truth `
  --out-json ..\results\identity-v2-recompute.json `
  --out-md ..\results\identity-v2-recompute.md

python .\recompute_roof_only_v1.py `
  --roof-root ..\..\roof-only-v1 `
  --single-pass-root ..\..\single-pass `
  --truth $truth `
  --out-json ..\results\roof-only-v1-recompute.json `
  --out-md ..\results\roof-only-v1-recompute.md

$env:PYTHONDONTWRITEBYTECODE = '1'
python -m pytest .\tests -q -p no:cacheprovider
```

若重新生成公开 JSON，再执行展示路径清理和泄漏检查：

```powershell
python .\sanitize_publication.py ..\results
```

## 冻结来源

| 内容 | SHA-256 / 约束 |
|---|---|
| 用户终审真值工作区字节 | `c3fddc439da1574e74a6ceb7391297e1c65fedec109d3579da05cad05f34149d` |
| 同一真值的 canonical labels | `78f255b1ae37463e2b36e15befb1ff8092ca87c2c6e946979d880f42cf0e5397` |
| B prompt | `52352ddb245a9bd98c20f5ca71e301d9aca5569366375635a130c42487baf2ab` |
| roof-only-v1 prompt | `9e7a956ccfcd4078b4a13526d5e0f8fe8c856cc84ee42a73723eaa97ccfb9362` |
| B 公共 raw | 180/180 hash 一致 |
| identity evidence manifest | 133/133 hash 一致 |
| roof-only raw manifest | 80/80 hash 一致 |

开发集不是盲测集；独立新时刻没有完成人审标签，因此当前没有泛化准确率。
