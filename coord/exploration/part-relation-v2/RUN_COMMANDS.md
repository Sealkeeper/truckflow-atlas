# Reproduce

Run from the repository workspace root:

```powershell
python sessions/part_relation_v2/run_part_relation.py prepare
python sessions/part_relation_v2/run_part_relation.py evaluate
python sessions/part_relation_v2/run_part_relation.py viz
python sessions/part_relation_v2/posthoc_analysis.py
```

The `prepare` command regenerates deterministic overview/far-detail images without calling the model. `evaluate` reads the frozen raw JSON files and truth, and `viz` regenerates overlays. `posthoc_analysis.py` reuses the same raw JSON files and does not call the model.

Do not run `run` again under the frozen plan. The four paid calls are exhausted, and no additional paid call is authorized. The archived scripts in this public directory are for inspection; the canonical executable copies are under `sessions/part_relation_v2`, where the relative path constants resolve correctly.

Expected primary result:

- 4/4 valid responses, 0 failures;
- 1/4 resolved;
- 0/4 exact point counts on the fixed four-sample denominator;
- range contains truth on 2/4.

The post-hoc figures are separate and must not replace the frozen values in `metrics.json`.
