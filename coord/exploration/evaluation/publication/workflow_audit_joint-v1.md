# Agent workflow audit

| Route | Verdict | Hard failures | Untested | Findings |
|---|---|---:|---:|---|
| joint-multiview-doubao-v1 | PASS | 0 | 0 | PASS human_boxes_used_as_model_input: 人工红框是否进入模型输入：否; PASS same_frame_annotations_exposed: 同帧人工标注是否进入检索上下文：否; PASS future_frames_exposed: 是否使用未来帧/未来观察：否; PASS memory_retrieval_scope: 检索范围=none; PASS previous_count_carryover: 没有仅按上一帧数量续填; PASS failures_skipped: 失败未被跳过; PASS failure_counted_in_denominator: 失败保留在固定分母; PASS fixed_denominator: N=20, valid=20, failed=0, missing=0 |

Hard failures include human red boxes or future frames in the retrieval context, count carry-over without new evidence, skipped API failures, or a broken fixed denominator.
