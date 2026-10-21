# Reproduction commands

All commands are run from
`sessions/architecture_challenger/research/architecture_challenge` on branch
`research/architecture-challenge`.

The model endpoint is read from the repository `.env`
(`DOUBAO_BASE_URL`, `DOUBAO_API_KEY`, `DOUBAO_MODEL`). No key is stored in this
directory. The frozen configuration is in `config.json`.

## 1. A′ 20-frame regression (one run per sample, no overwrite)

The runner returns an existing run file unchanged unless `--force` is passed.
Do not pass `--force` when reproducing the published result.

```powershell
python src/arch_windows.py --frames "north_5,north_300,north_600,north_900,north_1200,north_1500,north_1800,north_2100,north_2400,north_2600,south_5,south_300,south_600,south_900,south_1200,south_1500,south_1800,south_2100,south_2400,south_2600"
```

Each sample writes `runs/windows/<camera>_<time>.json` with the full prompt,
raw answer, reasoning text, usage, latency, every candidate, every adjudication
and every type review. Evidence crops are written under
`evidence/windows/<camera>_<time>/`.

## 2. Recompute metrics

```powershell
python src/evaluate_architectures.py --architectures windows --frame-set regression20 --out reports/evaluation_regression20.json --markdown-out reports/evaluation_regression20.md
python src/evaluate_architectures.py --architectures baseline_whole_frame,bands,windows,tree,scene_graph,critic
```

The first command uses all 20 confirmed camera samples and a fixed denominator
of 20; missing or failed samples stay visible in `missing_samples` /
`failed_samples`. The second reproduces the five-frame diagnostic table.

## 3. Five-frame diagnostic runs (other architectures)

```powershell
python src/arch_bands.py --frames north_300,north_600,south_600,north_1200,south_1200
python src/arch_tree.py --frames north_300,north_600,south_600,north_1200,south_1200
python src/arch_scenegraph.py --frames north_300,north_600,south_600,north_1200,south_1200
python src/arch_critic.py --frames north_300,north_600,south_600,north_1200,south_1200
```

## 4. Render final boxes

```powershell
python src/render_evidence.py --architectures bands,windows,tree,scene_graph,critic
```

The full evidence tree is several hundred images and is intentionally not
published. The final annotated frames referenced by `failures.md` are in the
private worktree under `research/architecture_challenge/evidence/`.
