## What this PR adds

Five measured architecture alternatives for truck counting, with reusable code,
full model-call provenance, evidence images, and a route recommendation.

Primary truth is the confirmed user review:
`all-sessions-can-see/accuracy/reviewed/user-final-review-v2-2026-10-21.json`.
The older `camera_counts_v0.json` is retained only as a diagnostic label for
vehicle type and boundary questions.

## Result (five-frame diagnostic set)

| Route | Count exact | MAE | Miss / extra | Tokens | Wall |
|---|---:|---:|---:|---:|---:|
| Doubao whole frame | 3/5 | 0.600 | 3 / 0 | 18,299 | 79.1 s |
| A perspective bands | 2/5 | 0.600 | 1 / 2 | 129,196 | 417.2 s |
| **A′ tight lane windows** | **4/5** | **0.200** | **0 / 1** | 143,325 | 544.1 s |
| B recursive tree | 1/5 | 1.000 | 1 / 4 | 291,099 | 1,166.5 s |
| C lane scene graph | 2/5 | 0.800 | 4 / 0 | 67,228 | 224.8 s |
| D annotated critic | 3/5 | 0.600 | 3 / 0 | 94,346 | 339.1 s |

## Recommendation

Advance A′ (tight lane-following windows) plus iterative semantic dedupe into a
20-frame regression. Keep the scene graph only as a `part_of` / `queue_index`
relation layer. Do not continue B or D as standalone counting architectures.

A′ still over-counts `south_600` by one because a red cab and a box containing
the gray trailer plus that cab are treated as different physical vehicles.
This is a known, localized failure, not a solved case.

## Boundaries

- This is a five-frame diagnostic set, not a 20-frame acceptance result.
- Only Doubao was reliably available; this is not a multi-model consensus claim.
- Human v2 provides totals only. No human type accuracy is claimed.
- No YOLO, OpenCV detection, or tracking is used. Geometry only proposes crops
  and pairs; all merge/type decisions are multimodal model calls with retained
  raw answers.

See `research/architecture_challenge/ROUTE_REPORT.md` and
`research/architecture_challenge/ARCHITECTURE_BETS.md` for evidence, costs,
kill criteria, and the next experiment gates.
