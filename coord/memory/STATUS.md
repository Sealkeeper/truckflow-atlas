# 车辆护照记忆状态

分支：`research/vehicle-passport`

提交：`e809725`；后续 PR 链接回填提交另行记录。

PR：#13，https://github.com/Sealkeeper/truckflow-atlas/pull/13 ；保持打开，不合并。

状态：身份分层、记忆缓存和双尺度无记忆消融已完成；组件装配冻结但未运行。结论仍为“复核/证据/回归有条件 go，自动计数和自动跨机位去重 no-go”。

## 已完成

- 从用户最终复核、红框附件、历史主输出、共识输出、配对探针和 L2 补检原响应建立可重放证据集。
- 实现 `research/vehicle_memory/prototype.py`：读取归档响应，生成 provisional 护照、车身裁剪、跨机位门禁、配对指标、成本指标和 L2 定点实验。
- 完成 `ARCHITECTURE.md`、`PASSPORT_SCHEMA.json`、`REPORT.md`。
- 修正成本统计单位：20 个相机帧、22 次调用、平均 1.1 次/相机帧。
- 修正跨机位释放：双机位有观测且没有已验证配对时一律 review。
- 将身份拆为 `cargo_id`、`tractor_id`、`vehicle_session_id`；未分类文字不得进入任一硬身份层。
- 新增 `generated/memory_cache.json` 和 `MEMORY_CACHE_SCHEMA.json`，每条记忆带来源、观测/创建时间、版本、TTL、过期时间、状态、冲突和 supersedes。
- 冻结 `dualscale_v1`（20 次）和 `component_assembly_v1`（8 次）的输入、提示词和配置；本轮预算 28/40。

## 已验证结果

- 归档单机位重放：16/20 exact，MAE 0.25。初始 19 个成功样本为 15/19；失败帧 `south_1200` 单独重跑成功，不能把两个口径混用。
- naive 两机位相加：唯一数 MAE 1.3；14/66 重复，21.2%。
- 跨机位自动放行：0/10；自动放行错误 0；复核 10/10。零错误来自零覆盖。
- 16 个归档配对探针：exact 4/16，review 16/16；明确 yes 的 precision 1.0（2 个 yes），recall 0.25。
- 语义护照候选配对：exact 3/8，自动 yes 0，review 5/8。
- L2 两次补检：`north_600` 2 -> 4（真值 4），`north_5` 4 -> 8（真值 5）；两样本 MAE 1.5 -> 1.5。
- 成本：主调用 20 + L2 2 = 22；75,950 tokens；平均 17.962 s/相机帧；p95 2、最大 2。
- 没有 validated hard ID，可证明的记忆节省调用为 0。
- 记忆缓存：L1 66 条、L2 2 条、L3 4 条；schema 校验通过。
- 双尺度无记忆消融：20/20 请求成功，14/20 exact、MAE 0.35、漏 4、多 2；修复 1、回归 3，当前形式淘汰。
- 双尺度 20 个响应均满足 `counts.total == len(vehicles)`；模型自报跨图去重不等于逐车视觉审计，仍有 2 个过计。
- `cargo_id`、`tractor_id`、`vehicle_session_id` 缺少完整人工真值，身份指标**未测**。
- 零调用离线可行性审计：10 项分层/元数据策略不变量通过；人工身份字段 0、人工换挂事件 0、prior-only/future 切分 0，身份实验 `ready=false`。

## 证据入口

- 指标：`research/vehicle_memory/generated/metrics.json`
- 护照：`research/vehicle_memory/generated/passports.json`
- 架构：`research/vehicle_memory/ARCHITECTURE.md`
- Schema：`research/vehicle_memory/PASSPORT_SCHEMA.json`
- 记忆缓存 schema：`research/vehicle_memory/MEMORY_CACHE_SCHEMA.json`
- 实验预注册：`research/vehicle_memory/experiments/PREREGISTRATION.md`
- 双尺度结果：`research/vehicle_memory/experiments/RESULT.md`
- 离线身份可行性：`research/vehicle_memory/OFFLINE_IDENTITY_FEASIBILITY.md`
- 零调用审计：`research/vehicle_memory/generated/offline_identity_audit.json`
- 公共发布：`coord/exploration/vehicle-memory/`
- 报告：`research/vehicle_memory/REPORT.md`
- 真值：`accuracy/reviewed/user-final-review-v2-2026-10-21.json`
- 红框：`review/user-attachments-20261021/manifest.json`
- 冻结证据：`research/vehicle_memory/evidence/`

## 限制

- 只有 10 个时刻、20 个相机帧、一个场景。
- 所有护照都是 `provisional`；模型可读文字没有独立 OCR/箱号验证。
- 语义配对正例自动覆盖为 0，跨机位自动放行为 0。
- L2 只有两个定点样本，一个修复、一个回归。
- 时间连续性未进入身份确认规则；历史时序实验没有自动修复漏计。
- 未测量人工复核耗时和复核精度，不能声称总运营成本下降。
- 未实测 100%，不声明 100%。

## 下一步

1. 停止重复“全局 + 固定远区”付费机制；输入尺度交给公共 `input-representation` 路线。
2. 优先补齐人工 `cargo_id`、`tractor_id`、`vehicle_session_id` 真值与换挂/OCR 冲突样本。
3. 按 prior-only 建库、future target 评估的隔离协议做离线实验。
4. 扩充正负配对集，报告自动覆盖、precision、recall 和误合并业务影响。
5. 记录复核队列的人工耗时和正确率。
