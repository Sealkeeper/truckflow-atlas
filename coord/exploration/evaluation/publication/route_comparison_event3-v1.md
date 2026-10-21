# Route comparison

Count exact is total truck-count exactness only; it is not vehicle-ID or model-class accuracy.
A missing field is `未测`; failures remain visible against the fixed N.

| Route | Split | Count exact | Count MAE | Unique exact | Unique MAE | Overlap exact | Overlap MAE | Vehicle ID |
|---|---|---|---|---|---|---|---|---|
| event-ledger-doubao-v1 | dev | 1/3 (N=3; fail=0; miss=0) | 0.666667 (n=3) | 未测 | 未测 | 未测 | 未测 | 未测 |

| Route | Auto release | Review | Calls | Images | Tokens | Latency mean/p95 | Audit / data notes |
|---|---|---|---:|---:|---:|---|---|
| event-ledger-doubao-v1 | correct=1; errors=2; cov=100.0%; err_rate=66.7% | 0/3 (0.0%) | 3 | 9 | 24,397 | 50.7183 / 94.273 s | workflow FAIL 使用了未来帧信息; workflow FAIL 检索范围=window_includes_future_frames |
