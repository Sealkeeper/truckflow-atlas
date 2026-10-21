# Agent workflow audit

| Route | Verdict | Hard failures | Untested | Findings |
|---|---|---:|---:|---|
| event-ledger-doubao-v1 | FAIL | 2 | 0 | PASS human_boxes_used_as_model_input: 人工红框是否进入模型输入：否; PASS same_frame_annotations_exposed: 同帧人工标注是否进入检索上下文：否; FAIL future_frames_exposed: 是否使用未来帧/未来观察：是; FAIL memory_retrieval_scope: 检索范围=window_includes_future_frames; WARN previous_count_carryover: 有续填，但登记了新增图像证据; PASS failures_skipped: 失败未被跳过; PASS failure_counted_in_denominator: 失败保留在固定分母; PASS fixed_denominator: N=3, valid=3, failed=0, missing=0 |

Hard failures include human red boxes or future frames in the retrieval context, count carry-over without new evidence, skipped API failures, or a broken fixed denominator.
