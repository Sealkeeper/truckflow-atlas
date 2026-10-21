# Route comparison

Count exact is total truck-count exactness only; it is not vehicle-ID or model-class accuracy.
A missing field is `未测`; failures remain visible against the fixed N.

| Route | Split | Count exact | Count MAE | Unique exact | Unique MAE | Overlap exact | Overlap MAE | Vehicle ID |
|---|---|---|---|---|---|---|---|---|
| clean-aisle-doubao-v1 | dev | 16/20 (valid=20; fail=0; miss=0) | 0.25 (valid n=20) | 未测 | 未测 | 未测 | 未测 | 未测 |

| Route | Auto release | Review | Calls | Images | Tokens | Latency mean/p95 | Audit / data notes |
|---|---|---|---:|---:|---:|---|---|
| clean-aisle-doubao-v1 | 未测 | 未测 | 20 | 20 | 67,027 | 15.864 / 21.27 s | workflow OK |
