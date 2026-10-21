# 交付状态

快照日期：2026-10-21。评测器新增模型调用：**0**。

## 已完成

| 项目 | 状态 | 公开证据 |
|---|---|---|
| B r1/r2/r3 独立复算 | 完成 | `results/b-recompute.*`、三项审计 JSON |
| Doubao Mini v2 独立复算 | 完成；旧整车口径 | `results/doubao-v2-recompute.*`、坐标审计 |
| identity-assembly-v2 复算 | 完成；负结果 | `results/identity-v2-recompute.*` |
| roof-only-v1 复算 | 完成；`FAIL_CONTRACT` | `results/roof-only-v1-recompute.*` |
| canonical schema / roof uncertain 规则 | 完成 | `ADAPTERS.md`、`tools/core.py` |
| 单元测试 | 17 passed | `TEST_RESULTS.md` |
| 路径与凭据泄漏扫描 | 通过 | `tools/sanitize_publication.py` |

## 路线状态

| 路线 | 状态 | 下一步允许事项 |
|---|---|---|
| B | 旧口径计数研究参照，不生产 | 只可另立 roof-only run；不得用旧 raw 追认新口径 |
| Doubao Mini | 旧口径模型对照 | 不改 prompt/raw 后混算；严格 schema 需新 run 验证 |
| Doubao Lite | `0/20, not_run` | 需独立预注册和新 roof-only 请求，当前无分数 |
| identity-assembly-v2 | 淘汰当前自动装配配置 | 保留负结果；重新设计须新机制、新 run |
| roof-only-v1 | `FAIL_CONTRACT`，当前配置淘汰 | 修正 schema 后必须是新 run ID；不改写本 run |
| part-relation-v2 | `awaiting_public_artifacts` | 等其公共 `frozen_inputs`、raw、metrics、REPORT 完整 |
| causal-memory-v2 | `awaiting_public_artifacts` | 等公共回放日志、消融 JSON、metrics、REPORT |
| round2-research independent-v1 | `labels_pending` | 等人工标签导出和复核；当前不评分、不调用模型 |

## 未做与禁止代替

本轮没有替任何路线抽帧、追加请求、修改 prompt、重跑模型或补写标签。缺少公共产物时状态保持 `awaiting_public_artifacts`；缺少独立新时刻标签时保持 `labels_pending`。这两种状态都不是 0 分，也不能由评测器自行补造。

当前没有可进入生产或宣称泛化的路线。即使 B/Mini 的旧口径机位计数为 18/20，B 的 6 次错误自动放行和 identity 的 5 次错误放行已构成生产硬门禁失败。

## 后续接入条件

新路线接入统一评测前必须提供：

1. 冻结输入清单、每个模型输入的 SHA-256、prompt、模型 ID、参数、run ID。
2. 固定分母内每个样本的 valid/failed/refused/missing 状态，不删除失败。
3. 明确的 `evidence_scope` 和 `bbox_space`；roof-only 还要给出 physical entity、roof observation 和 uncertain 分组。
4. 完整原始 attempts/usage/耗时和公共 raw，不使用临时文件或私有 session 路径。
5. 显式 `release_decision`；没有决策就写未报告，不能用 confidence 代替。
6. 独立时段只有标签完成并冻结后才可评分；开门看分后改协议只能降级为开发回归。
