# Count V2 model experiment

Gold: `data\gold\camera_counts_v0.json` (manual-development-set), 20 development samples.

| run | prompt | successful | exact | exact rate | MAE | under | over |
|---|---|---:|---:|---:|---:|---:|---:|
| aibox_count_v2 | count_v2 | 20/20 | 10/20 | 50.0% | 0.50 | 1 | 9 |
| doubao_count_v2 | count_v2 | 20/20 | 15/20 | 75.0% | 0.25 | 3 | 2 |
| doubao_baseline_v1 | truck-count-v1 | 20/20 | 16/20 | 80.0% | 0.25 | 3 | 1 |

## Cascade

- rule: Use Doubao as primary. Trigger Aibox review when Doubao fails, its boxes show geometric/distant/edge/overlap risk, or its count differs from the Aibox second opinion. On trigger, use Aibox count; fall back to Doubao if Aibox fails.
- trigger: 20/20 (100.0%)
- base errors caught: 5/5
- exact: 10/20 (50.0%)
- MAE: 0.50

## Per-sample

| sample | gold | aibox_count_v2 | doubao_count_v2 | doubao_baseline_v1 |
|---|---:|---:|---:|---:|
| north_1200 | 3 | 3 (+0) | 3 (+0) | 3 (+0) |
| north_1500 | 2 | 2 (+0) | 2 (+0) | 2 (+0) |
| north_1800 | 2 | 2 (+0) | 2 (+0) | 2 (+0) |
| north_2100 | 2 | 2 (+0) | 2 (+0) | 2 (+0) |
| north_2400 | 3 | 4 (+1) | 3 (+0) | 3 (+0) |
| north_2600 | 2 | 2 (+0) | 2 (+0) | 2 (+0) |
| north_300 | 3 | 4 (+1) | 2 (-1) | 2 (-1) |
| north_5 | 3 | 4 (+1) | 3 (+0) | 3 (+0) |
| north_600 | 4 | 3 (-1) | 3 (-1) | 2 (-2) |
| north_900 | 3 | 3 (+0) | 3 (+0) | 3 (+0) |
| south_1200 | 5 | 5 (+0) | 5 (+0) | 5 (+0) |
| south_1500 | 5 | 6 (+1) | 6 (+1) | 5 (+0) |
| south_1800 | 4 | 5 (+1) | 4 (+0) | 4 (+0) |
| south_2100 | 4 | 4 (+0) | 4 (+0) | 4 (+0) |
| south_2400 | 3 | 4 (+1) | 3 (+0) | 3 (+0) |
| south_2600 | 3 | 4 (+1) | 4 (+1) | 4 (+1) |
| south_300 | 4 | 5 (+1) | 4 (+0) | 4 (+0) |
| south_5 | 3 | 4 (+1) | 3 (+0) | 3 (+0) |
| south_600 | 5 | 5 (+0) | 4 (-1) | 4 (-1) |
| south_900 | 5 | 5 (+0) | 5 (+0) | 5 (+0) |

## Assessment (computed, no manual arithmetic)

- Aibox 503 rate of HTTP attempts: 0.0
- Aibox failed samples: 0
- Aibox systematically better: False
- Worth review channel at <=5% failure: False
- Aibox worse samples: [{'sample_id': 'north_5', 'gold': 3, 'doubao_count_v2': 3, 'aibox_count_v2': 4, 'left_abs_error': 0, 'right_abs_error': 1}, {'sample_id': 'north_2400', 'gold': 3, 'doubao_count_v2': 3, 'aibox_count_v2': 4, 'left_abs_error': 0, 'right_abs_error': 1}, {'sample_id': 'south_5', 'gold': 3, 'doubao_count_v2': 3, 'aibox_count_v2': 4, 'left_abs_error': 0, 'right_abs_error': 1}, {'sample_id': 'south_300', 'gold': 4, 'doubao_count_v2': 4, 'aibox_count_v2': 5, 'left_abs_error': 0, 'right_abs_error': 1}, {'sample_id': 'south_1800', 'gold': 4, 'doubao_count_v2': 4, 'aibox_count_v2': 5, 'left_abs_error': 0, 'right_abs_error': 1}, {'sample_id': 'south_2400', 'gold': 3, 'doubao_count_v2': 3, 'aibox_count_v2': 4, 'left_abs_error': 0, 'right_abs_error': 1}]
