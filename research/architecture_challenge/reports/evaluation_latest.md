# Architecture challenge evaluation

Primary truth: `accuracy/reviewed/user-final-review-v2-2026-10-21.json` (confirmed user review, per-camera totals).
Required frames: north_300, north_600, south_600, north_1200, south_1200
This is a five-frame diagnostic set, not the 20-frame regression set.

| Architecture | Valid / required | Human count exact (of required) | Count MAE (valid) | Miss | Extra | v0 full exact (diag) | v0 type exact (diag) | Calls | Failed | Images | Tokens | Wall mean s | Wall p95 s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Doubao whole frame | 5/5 | 3/5 | 0.600 | 3 | 0 | 2 | 2 | 5 | 0 | 5 | 18299 | 15.8 | 25.0 |
| A: perspective depth bands | 5/5 | 2/5 | 0.600 | 1 | 2 | 1 | 1 | 48 | 0 | 48 | 129196 | 83.4 | 96.5 |
| A′: tight lane windows | 5/5 | 4/5 | 0.200 | 0 | 1 | 3 | 3 | 51 | 0 | 51 | 143325 | 108.8 | 142.7 |
| B: recursive region tree | 5/5 | 1/5 | 1.000 | 1 | 4 | 0 | 0 | 91 | 0 | 91 | 291099 | 233.3 | 313.3 |
| C: lane scene graph | 5/5 | 2/5 | 0.800 | 4 | 0 | 1 | 1 | 21 | 0 | 21 | 67228 | 45.0 | 70.6 |
| D: annotated critic loop | 5/5 | 3/5 | 0.600 | 3 | 0 | 1 | 1 | 27 | 0 | 32 | 94346 | 67.8 | 112.1 |

## Per-frame total counts (human / prediction)

| Architecture | north_300 | north_600 | south_600 | north_1200 | south_1200 |
|---|---:|---:|---:|---:|---:|
| Doubao whole frame | 3 / 2 | 4 / 2 | 4 / 4 | 3 / 3 | 5 / 5 |
| A: perspective depth bands | 3 / 4 | 4 / 4 | 4 / 4 | 3 / 2 | 5 / 6 |
| A′: tight lane windows | 3 / 3 | 4 / 4 | 4 / 5 | 3 / 3 | 5 / 5 |
| B: recursive region tree | 3 / 4 | 4 / 3 | 4 / 5 | 3 / 5 | 5 / 5 |
| C: lane scene graph | 3 / 2 | 4 / 2 | 4 / 4 | 3 / 3 | 5 / 4 |
| D: annotated critic loop | 3 / 2 | 4 / 2 | 4 / 4 | 3 / 3 | 5 / 5 |

The human v2 export contains totals only, so type accuracy is not a confirmed metric. The v0 full/type columns use the older provisional `camera_counts_v0` labels and are diagnostic only.

## 20-frame regression set (baseline only)

Doubao whole frame: 16/20 human count exact, MAE 0.300, miss 5, extra 1.
