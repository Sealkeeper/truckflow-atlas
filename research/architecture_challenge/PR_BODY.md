## What this PR adds

Five measured architecture alternatives for truck counting, with reusable code,
full model-call provenance, evidence images, and a route recommendation.

Primary truth is the confirmed user review:
`all-sessions-can-see/accuracy/reviewed/user-final-review-v2-2026-10-21.json`.
The older `camera_counts_v0.json` is retained only as a diagnostic label for
vehicle type and boundary questions.

Two different baselines are kept separate: the five-frame table's control is the
**Doubao whole frame** route (20-frame 16/20, MAE 0.300, miss 5, extra 1); the
production candidate baseline is the **clean aisle** route (16/20, MAE 0.25,
miss 4, extra 1, PR #9 head `f5eb47614494c4a8e4b8df6d5bcd426ac61207ec`).
The historical 15/19 omitted a failed response; 17/20 used mixed-view coverage.
Neither is a valid baseline. The user's red boxes support the current totals, so
the earlier "south 5 should merge to 3" inference is retracted.

## Result (five-frame diagnostic set)

| Route | Count exact | MAE | Miss / extra | Tokens | Wall |
|---|---:|---:|---:|---:|---:|
| Doubao whole frame | 3/5 | 0.600 | 3 / 0 | 18,299 | 79.1 s |
| A perspective bands | 2/5 | 0.600 | 1 / 2 | 129,196 | 417.2 s |
| **A′ tight lane windows** | **4/5** | **0.200** | **0 / 1** | 143,325 | 544.1 s |
| B recursive tree | 1/5 | 1.000 | 1 / 4 | 291,099 | 1,166.5 s |
| C lane scene graph | 2/5 | 0.800 | 4 / 0 | 67,228 | 224.8 s |
| D annotated critic | 3/5 | 0.600 | 3 / 0 | 94,346 | 339.1 s |

## 20-frame regression (all 20 confirmed camera samples)

| Route | Count exact | MAE | Miss / extra | Failures | Tokens | Wall |
|---|---:|---:|---:|---:|---:|---:|
| Doubao whole frame | 16/20 | 0.300 | 5 / 1 | 0 | 72,365 | 344.6 s total |
| Clean aisle baseline (PR #9) | 16/20 | 0.25 | 4 / 1 | 0 | — | — |
| **A′ tight lane windows** | **13/20** | **0.400** | **3 / 5** | 0 | **511,742** | **90.7 s mean, 142.7 s p95** |

A′ fixed the two far-queue misses (`north_300`, `north_600`) but introduced new
errors on five frames the baseline already counted correctly:
`north_900` -1, `south_900` -1, `north_1800` +1, `south_300` +1,
`south_600` +1; `south_2100` grew from +1 to +2.

The failure is bidirectional: some frames merge two distinct stacked container
trailers (undercount), others split a cab and its trailer or keep cross-window
fragments (overcount). A threshold or one more prompt cannot reliably fix both.

## Recommendation

Do **not** advance A′ into implementation and do not keep tuning its prompt.
Keep the clean aisle baseline as the production path (16/20, MAE 0.25). Retain
A′'s `far_b` crop only as evidence for the far container row. Keep the scene
graph only as a `part_of` / `queue_index` relation idea. Eliminate B and D as
standalone counting architectures.

The five-frame diagnostic result (A′ 4/5) was measured on the frames used to
tune the windows; it did not generalize to the 20-frame set.

## Boundaries

- The five-frame table is diagnostic; the 20-frame table above is the regression
  result. A′ fails that regression.
- Only Doubao was reliably available; this is not a multi-model consensus claim.
- Human v2 provides totals only. No human type accuracy is claimed.
- No YOLO, OpenCV detection, or tracking is used. Geometry only proposes crops
  and pairs; all merge/type decisions are multimodal model calls with retained
  raw answers.

See `research/architecture_challenge/ROUTE_REPORT.md` and
`research/architecture_challenge/ARCHITECTURE_BETS.md` for evidence, costs,
kill criteria, and the next experiment gates.

The public experiment record (frozen config, scene-graph method, metrics,
raw runs, failures and reproduction commands) is under
`all-sessions-can-see/coord/exploration/architecture/`.
