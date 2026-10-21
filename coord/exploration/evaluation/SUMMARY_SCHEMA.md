# 路线 summary JSON 契约 v1

`schema` 固定为 `truckflow-route-summary-v1`。各路线在这个 schema 下发布一个 summary；比较工具只读取命令行显式给出的文件，不扫描任何 session。

## 最小字段

```json
{
  "schema": "truckflow-route-summary-v1",
  "route": {
    "id": "route-id",
    "owner": "session-or-owner",
    "mechanism": "one-sentence mechanism",
    "branch": "branch-name",
    "commit": "full-or-short-sha",
    "status": "candidate|baseline|rejected"
  },
  "dataset": {
    "name": "user-final-review-v2-2026-10-21",
    "split": "dev|blind",
    "n_camera_samples": 20,
    "n_times": 10,
    "truth_sha256": "..."
  },
  "camera_count": {
    "n_total": 20,
    "valid_n": 20,
    "failed": 0,
    "missing": 0,
    "exact": 16,
    "mae": 0.25,
    "under": 4,
    "over": 1,
    "under_frames": 3,
    "over_frames": 1
  },
  "unique": {
    "n_total": 10,
    "valid_n": null,
    "failed": null,
    "missing": null,
    "exact": null,
    "mae": null
  },
  "overlap": {
    "n_total": 10,
    "valid_n": null,
    "failed": null,
    "missing": null,
    "exact": null,
    "mae": null
  },
  "release": {
    "n_total": 20,
    "auto_released": null,
    "correct": null,
    "errors": null,
    "coverage": null
  },
  "review": {
    "reviewed": null,
    "review_rate": null
  },
  "identity": {
    "status": "not measured",
    "n_total": null,
    "exact": null
  },
  "cost": {
    "calls": 20,
    "images": 20,
    "tokens_total": 67027,
    "latency_s_mean": 15.864,
    "latency_s_p95": 21.27,
    "concurrency": 1,
    "peak_memory_mb": null
  },
  "workflow_audit": {
    "human_boxes_used_as_model_input": false,
    "same_frame_annotations_exposed": false,
    "future_frames_exposed": false,
    "memory_retrieval_scope": "none|prior_frames_only",
    "previous_count_carryover": false,
    "carryover_has_new_evidence": null,
    "failures_skipped": false,
    "failure_counted_in_denominator": true
  }
}
```

`null` 表示未测，不表示 0。工具会把未测字段显示为 `未测`。

## 固定分母

- `n_total` 是该数据集的固定分母。
- `valid_n + failed + missing` 必须等于 `n_total`。
- headline 一律写 `exact/n_total`（固定分母）。即使有失败也只能写 `15/20`，不能写成 `15/19` 误导成更高准确率。
- `valid_N=19`、`failed=1` 单列，用来说明 MAE 只覆盖有效预测。
- `under`/`over` 是车辆单位数；`under_frames`/`over_frames` 是出现该方向的机位样本数。两者不可混写。
- MAE 只在 `valid_n` 上计算，不伪造失败样本的预测。
- 不允许因为删除失败样本而提高 exact rate。

## 指标边界

- `camera_count.exact` 只表示“总数完全正确”，不是车型、车辆集合、跨时刻 ID 或跨机位配对全准确。
- `unique` 指同一时刻南北机位合并后的唯一车辆总数；`overlap` 指同刻两机位重合车辆数。
- `release` 记录自动放行策略：放行样本数、其中正确数、错误数、覆盖率。复核率和拒答不算识别正确。
- 没有完整人工真值的车型、ID、框质量字段必须写 `null` 或 `status=not measured`。

## Agent 工作流审计

`audit_agent_workflow.py` 会检查：

- 同一测试时刻的人工红框、答案或车辆数是否进入检索上下文；
- 是否暴露未来帧/未来观察；
- 是否只是把上一帧数量续填给当前帧，且没有新增图像证据；
- 调用失败是否被跳过；
- 失败是否保留在固定分母。

新 Agent 路线发布 summary 时必须填写 `workflow_audit`。缺失字段会被标为 `未测`，不会被当成通过。

## 使用

```powershell
python coord/exploration/evaluation/compare_routes.py `
  --summary <route-a.json> <route-b.json> `
  --out-md coord/exploration/evaluation/route_comparison.md `
  --out-json coord/exploration/evaluation/route_comparison.json

python coord/exploration/evaluation/audit_agent_workflow.py `
  --summary <route-a.json> <route-b.json>
```
