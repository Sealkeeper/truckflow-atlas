# Architecture challenge evaluation

Primary truth: `accuracy/reviewed/user-final-review-v2-2026-10-21.json` (confirmed user review, per-camera totals).
Required frames: north_5, south_5, north_300, south_300, north_600, south_600, north_900, south_900, north_1200, south_1200, north_1500, south_1500, north_1800, south_1800, north_2100, south_2100, north_2400, south_2400, north_2600, south_2600
This is the 20-camera regression set (development data).

| Architecture | Valid / required | Human count exact (of required) | Count MAE (valid) | Miss | Extra | v0 full exact (diag) | v0 type exact (diag) | Calls | Failed | Images | Tokens | Wall mean s | Wall p95 s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A′: tight lane windows | 20/20 | 13/20 | 0.400 | 3 | 5 | 7 | 7 | 186 | 0 | 186 | 511742 | 90.7 | 142.7 |

## Per-frame total counts (human / prediction)

| Architecture | north_5 | south_5 | north_300 | south_300 | north_600 | south_600 | north_900 | south_900 | north_1200 | south_1200 | north_1500 | south_1500 | north_1800 | south_1800 | north_2100 | south_2100 | north_2400 | south_2400 | north_2600 | south_2600 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A′: tight lane windows | 5 / 4 | 3 / 3 | 3 / 3 | 4 / 5 | 4 / 4 | 4 / 5 | 3 / 2 | 5 / 4 | 3 / 3 | 5 / 5 | 2 / 2 | 5 / 5 | 2 / 3 | 4 / 4 | 2 / 2 | 3 / 5 | 3 / 3 | 3 / 3 | 2 / 2 | 4 / 4 |

The human v2 export contains totals only, so type accuracy is not a confirmed metric. The v0 full/type columns use the older provisional `camera_counts_v0` labels and are diagnostic only.
