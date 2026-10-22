#!/usr/bin/env python3
"""Independent recomputation of the headline numbers in the 2026-10-22 reports.

This script does not call a model and does not modify truth or frozen raw.  It
recomputes:

  * shipped results-old10.json : all-ok / 10
  * pair oracle               : all-ok / 10
  * both oracle               : all-ok / 10
  * single-camera oracle      : all-ok / 10 (subset enumeration)
  * V3b / V5 before/after     : all-ok / 10 and exact / 20
  * self-consistency C rule   : exact / 20

Usage:
  python number_audit.py --json number_audit.json
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


TIMES = [5, 300, 600, 900, 1200, 1500, 1800, 2100, 2400, 2600]
REPO = Path(__file__).resolve().parents[3]
OPT = REPO / "coord/optimization-20261022"
RAW = REPO / "coord/exploration/roof-bands-v1/raw_lite"
RESULTS = OPT / "invention/lane_queue/results-old10.json"
TRUTH = REPO / "accuracy/reviewed/user-final-review-v2-2026-10-21.json"
SELF_CONSISTENCY = OPT / "error-atlas/self_consistency.json"
CEILING = OPT / "tournament/runs/ceiling-decomp/results.json"
ROBUST = OPT / "tournament/runs/v3b-robust/robustness.json"
PAIR_BRACKET = OPT / "tournament/runs/pair-bracket"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def all_ok(pred: Dict[str, int], truth: Dict[str, int]) -> bool:
    return all(int(pred[k]) == int(truth[k]) for k in ("south", "north", "overlap"))


def counts(south: Sequence[Any], north: Sequence[Any], overlap: int) -> Dict[str, int]:
    return {"south": len(south), "north": len(north), "overlap": int(overlap)}


def load_exclusions(path: Path) -> Dict[Tuple[str, int], List[str]]:
    """Parse the same narrow explicit-exclusion rule as the v3b report.

    We deliberately re-parse the sentences instead of importing the v3b
    function, so the audit does not share that implementation.
    """
    payload = load(path)
    out: Dict[Tuple[str, int], List[str]] = {}
    for frame in payload["frames"]:
        excl = frame.get("explicit_exclusions") or []
        if not excl:
            continue
        cam = frame["camera"]
        time_s = int(frame["time"])
        ids: List[str] = []
        for item in excl:
            for rid in re.findall(r"\bR(\d+)\b", item["sentence"]):
                key = f"{cam[0]}R{rid}"
                if key not in ids:
                    ids.append(key)
        want = max(int(i["n"]) for i in excl)
        if len(ids) != want:
            raise RuntimeError(
                f"{frame['frame']}: parsed {len(ids)} ids {ids}, audit expects {want}"
            )
        out[(cam, time_s)] = ids
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    sys.path.insert(0, str(OPT / "invention"))
    sys.path.insert(0, str(PAIR_BRACKET))
    from lane_queue.align import AlignConfig, align_queues
    from lane_queue.dataio import load_roofs, load_truth, moment_files
    from lane_queue.dedup import QueueConfig, build_queue
    from pair_bracket import align_custom

    results = load(RESULTS)
    truth = load_truth(TRUTH)
    ceiling = load(CEILING)
    robust = load(ROBUST)
    selfc = load(SELF_CONSISTENCY)

    audit: Dict[str, Any] = {
        "schema": "truckflow-number-audit-v1",
        "inputs": {
            "results_old10": {
                "path": str(RESULTS.relative_to(REPO)),
                "sha256": sha256_file(RESULTS),
            },
            "truth": {
                "path": str(TRUTH.relative_to(REPO)),
                "sha256": sha256_file(TRUTH),
            },
            "self_consistency": {
                "path": str(SELF_CONSISTENCY.relative_to(REPO)),
                "sha256": sha256_file(SELF_CONSISTENCY),
            },
            "ceiling_results": {
                "path": str(CEILING.relative_to(REPO)),
                "sha256": sha256_file(CEILING),
            },
            "robustness_results": {
                "path": str(ROBUST.relative_to(REPO)),
                "sha256": sha256_file(ROBUST),
            },
        },
    }

    # ---- 1. shipped 5/10 -------------------------------------------------
    shipped_rows = []
    shipped_ok = 0
    compare_flag_mismatch = []
    unique_formula_bad = []
    for rec in results:
        t = int(rec["time"])
        pred = rec["pred"]
        gold = rec["truth"]
        ok = all_ok(pred, gold)
        shipped_ok += int(ok)
        flag = bool(rec.get("compare", {}).get("checks", {}).get("quantity_all_ok"))
        if flag != ok:
            compare_flag_mismatch.append(t)
        if pred.get("unique") != pred["south"] + pred["north"] - pred["overlap"]:
            unique_formula_bad.append(t)
        shipped_rows.append(
            {
                "time": t,
                "pred": pred,
                "truth": gold,
                "ok": ok,
                "compare_quantity_all_ok": flag,
            }
        )
    audit["shipped"] = {
        "denominator": len(results),
        "all_ok": shipped_ok,
        "rows": shipped_rows,
        "failed": [r["time"] for r in shipped_rows if not r["ok"]],
        "compare_flag_mismatch": compare_flag_mismatch,
        "unique_formula_bad": unique_formula_bad,
    }
    audit["shipped_by_field"] = {
        k: {
            "correct": sum(
                1 for r in shipped_rows if int(r["pred"][k]) == int(r["truth"][k])
            ),
            "denominator": len(shipped_rows),
        }
        for k in ("south", "north", "overlap")
    }

    # Structural claim in CEILING_DECOMPOSITION.md: the existing one-to-one DP
    # already satisfies pairs <= min(S, N) and uses every endpoint at most once.
    pair_cap_violations = []
    for rec in results:
        pairs = rec.get("pairs") or []
        used_s = [p["south"] for p in pairs]
        used_n = [p["north"] for p in pairs]
        cap = min(len(rec["queue"]["south"]), len(rec["queue"]["north"]))
        if (
            len(pairs) > cap
            or len(set(used_s)) != len(used_s)
            or len(set(used_n)) != len(used_n)
        ):
            pair_cap_violations.append(int(rec["time"]))
    audit["pair_cap"] = {
        "moments_checked": len(results),
        "violations": pair_cap_violations,
    }

    # ---- 2. pair oracle 8/10 ---------------------------------------------
    pair_rows = []
    pair_ok = 0
    queue_count_mismatch = []
    for rec in results:
        t = int(rec["time"])
        gold = rec["truth"]
        s = len(rec["queue"]["south"])
        n = len(rec["queue"]["north"])
        if (s, n) != (int(rec["pred"]["south"]), int(rec["pred"]["north"])):
            queue_count_mismatch.append(t)
        pred = {"south": s, "north": n, "overlap": int(gold["overlap"])}
        ok = all_ok(pred, gold)
        pair_ok += int(ok)
        pair_rows.append({"time": t, "pred": pred, "truth": gold, "ok": ok})
    audit["pair_oracle"] = {
        "denominator": len(results),
        "all_ok": pair_ok,
        "rows": pair_rows,
        "failed": [r["time"] for r in pair_rows if not r["ok"]],
        "queue_count_mismatch": queue_count_mismatch,
    }

    # ---- 3. both oracle 10/10 --------------------------------------------
    both_rows = []
    truth_file_mismatch = []
    for rec in results:
        t = int(rec["time"])
        gold = rec["truth"]
        key = f"t{t}"
        if key not in truth:
            truth_file_mismatch.append(key)
            continue
        for k in ("south", "north", "overlap"):
            if int(truth[key][k]) != int(gold[k]):
                truth_file_mismatch.append(f"{key}.{k}")
        both_rows.append(
            {
                "time": t,
                "pred": dict(gold),
                "truth": gold,
                "ok": all_ok(gold, gold),
            }
        )
    audit["both_oracle"] = {
        "denominator": len(both_rows),
        "all_ok": sum(1 for r in both_rows if r["ok"]),
        "rows": both_rows,
        "truth_file_mismatch": truth_file_mismatch,
    }

    # ---- 4. single-camera oracle 7/10 ------------------------------------
    cfg = AlignConfig()
    single_rows = []
    single_ok = 0
    queue_replay_mismatch = []
    pair_replay_mismatch = []
    for rec in results:
        t = int(rec["time"])
        files = moment_files(RAW, t)
        south = build_queue(load_roofs(files["south"], "south"), QueueConfig())
        north = build_queue(load_roofs(files["north"], "north"), QueueConfig())
        shipped_s = {q["id"] for q in rec["queue"]["south"]}
        shipped_n = {q["id"] for q in rec["queue"]["north"]}
        if shipped_s != {q.id for q in south} or shipped_n != {q.id for q in north}:
            queue_replay_mismatch.append(t)
        replay = align_queues(south, north, cfg)
        if replay.overlap != int(rec["pred"]["overlap"]):
            pair_replay_mismatch.append(t)

        gold = truth[f"t{t}"]
        s_target = int(gold["south"])
        n_target = int(gold["north"])
        subset_count = 0
        best_overlap = -1
        hits = 0
        examples = []
        if s_target <= len(south) and n_target <= len(north):
            for ss in itertools.combinations(south, s_target):
                for nn in itertools.combinations(north, n_target):
                    subset_count += 1
                    al = align_queues(list(ss), list(nn), cfg)
                    best_overlap = max(best_overlap, al.overlap)
                    if al.overlap == int(gold["overlap"]):
                        hits += 1
                        if len(examples) < 3:
                            examples.append(
                                {
                                    "south": [i.id for i in ss],
                                    "north": [i.id for i in nn],
                                    "overlap": al.overlap,
                                    "pairs": [[p.south_id, p.north_id] for p in al.pairs],
                                }
                            )
        ok = hits > 0
        single_ok += int(ok)
        single_rows.append(
            {
                "time": t,
                "actual_counts": {"south": len(south), "north": len(north)},
                "target_counts": {"south": s_target, "north": n_target},
                "gold_overlap": int(gold["overlap"]),
                "subset_count": subset_count,
                "best_overlap": best_overlap,
                "target_subsets": hits,
                "ok": ok,
                "examples": examples,
            }
        )

    # Compare against the reported ceiling JSON per moment.
    ceiling_by_t = {int(m["time"]): m for m in ceiling["single_camera_oracle"]["moments"]}
    ceiling_mismatch = []
    for row in single_rows:
        rep = ceiling_by_t.get(row["time"])
        if not rep:
            ceiling_mismatch.append({"time": row["time"], "field": "missing"})
            continue
        for key in ("subset_count", "best_overlap", "target_subsets", "ok"):
            if row[key] != rep[key]:
                ceiling_mismatch.append(
                    {"time": row["time"], "field": key, "audit": row[key], "report": rep[key]}
                )
    audit["single_camera_oracle"] = {
        "denominator": len(single_rows),
        "all_ok": single_ok,
        "rows": single_rows,
        "failed": [r["time"] for r in single_rows if not r["ok"]],
        "queue_replay_mismatch": queue_replay_mismatch,
        "pair_replay_mismatch": pair_replay_mismatch,
        "ceiling_mismatch": ceiling_mismatch,
    }

    # ---- 5. V3b / V5 before/after ----------------------------------------
    exclusions = load_exclusions(SELF_CONSISTENCY)

    def build_items(drop: bool) -> Dict[int, Tuple[List[Any], List[Any]]]:
        items: Dict[int, Tuple[List[Any], List[Any]]] = {}
        for t in TIMES:
            files = moment_files(RAW, t)
            row = []
            for view in ("south", "north"):
                roofs = load_roofs(files[view], view)
                if drop:
                    banned = set(exclusions.get((view, t), []))
                    kept = [r for r in roofs if r.id not in banned]
                    if len(roofs) - len(kept) != len(banned & {r.id for r in roofs}):
                        raise RuntimeError(f"{view}_{t}: exclusion id not found")
                    roofs = kept
                row.append(build_queue(roofs, QueueConfig()))
            items[t] = (row[0], row[1])
        return items

    base_items = build_items(False)
    clean_items = build_items(True)

    def run_v0(items, cfg) -> Dict[int, List[Any]]:
        return {t: list(align_queues(items[t][0], items[t][1], cfg).pairs) for t in TIMES}

    def run_prior(
        items, cfg, beta: float, scale: float, gate: int, collapse_guard: bool = False
    ) -> Dict[int, List[Any]]:
        emitted: Dict[int, List[Any]] = {}
        prior: List[Tuple[float, float]] = []
        for t in TIMES:
            south, north = items[t]
            active = prior if len(prior) >= gate else []
            pairs = align_custom(
                south,
                north,
                cfg,
                mirror_s=True,
                skip_increment=0.0,
                previous_matches=active,
                prior_beta=beta,
                prior_scale=scale,
            )
            if collapse_guard and active and not pairs:
                fallback = align_custom(
                    south,
                    north,
                    cfg,
                    mirror_s=True,
                    skip_increment=0.0,
                    previous_matches=None,
                    prior_beta=beta,
                    prior_scale=scale,
                )
                if fallback:
                    pairs = fallback
            emitted[t] = list(pairs)
            by_s = {i.id: i for i in south}
            by_n = {i.id: i for i in north}
            prior = [
                (by_s[p.south_id].s, 1.0 - by_n[p.north_id].s)
                for p in pairs
                if p.south_id in by_s and p.north_id in by_n
            ]
        return emitted

    def score(items, pairs_by_t) -> Dict[str, Any]:
        moments = []
        for t in TIMES:
            south, north = items[t]
            pred = {
                "south": len(south),
                "north": len(north),
                "overlap": len(pairs_by_t[t]),
            }
            gold = truth[f"t{t}"]
            ok = all_ok(pred, gold)
            moments.append(
                {
                    "time": t,
                    "pred": pred,
                    "truth": gold,
                    "ok": ok,
                    "pairs": [[p.south_id, p.north_id] for p in pairs_by_t[t]],
                }
            )
        return {
            "all_ok": sum(1 for m in moments if m["ok"]),
            "failed": [m["time"] for m in moments if not m["ok"]],
            "moments": moments,
        }

    def single_camera_exact(items) -> Dict[str, Any]:
        rows = []
        for t in TIMES:
            for idx, view in enumerate(("south", "north")):
                pred = len(items[t][idx])
                gold = int(truth[f"t{t}"][view])
                rows.append(
                    {"time": t, "view": view, "pred": pred, "truth": gold, "ok": pred == gold}
                )
        return {
            "exact": sum(1 for r in rows if r["ok"]),
            "denominator": len(rows),
            "wrong": [r for r in rows if not r["ok"]],
        }

    base_cfg = AlignConfig()
    base_v0 = score(base_items, run_v0(base_items, base_cfg))
    base_v3 = score(base_items, run_prior(base_items, base_cfg, 0.25, 0.20, 1))
    base_v3b = score(base_items, run_prior(base_items, base_cfg, 0.25, 0.20, 2))
    base_v5 = score(
        base_items, run_prior(base_items, base_cfg, 0.25, 0.20, 1, collapse_guard=True)
    )
    clean_v0 = score(clean_items, run_v0(clean_items, base_cfg))
    clean_v3 = score(clean_items, run_prior(clean_items, base_cfg, 0.25, 0.20, 1))
    clean_v3b = score(clean_items, run_prior(clean_items, base_cfg, 0.25, 0.20, 2))
    clean_v5 = score(
        clean_items, run_prior(clean_items, base_cfg, 0.25, 0.20, 1, collapse_guard=True)
    )
    sc_base = single_camera_exact(base_items)
    sc_clean = single_camera_exact(clean_items)

    audit["v3b_merge"] = {
        "joint": {
            "V0": {"before": base_v0["all_ok"], "after": clean_v0["all_ok"]},
            "V3": {"before": base_v3["all_ok"], "after": clean_v3["all_ok"]},
            "V3b": {"before": base_v3b["all_ok"], "after": clean_v3b["all_ok"]},
            "V5": {"before": base_v5["all_ok"], "after": clean_v5["all_ok"]},
        },
        "failed_after": {
            "V3b": clean_v3b["failed"],
            "V5": clean_v5["failed"],
            "V0": clean_v0["failed"],
        },
        "single_camera_exact": {
            "before": sc_base["exact"],
            "after": sc_clean["exact"],
            "denominator": sc_base["denominator"],
            "before_wrong": sc_base["wrong"],
            "after_wrong": sc_clean["wrong"],
        },
        "exclusions": {f"{c}_{t}": ids for (c, t), ids in sorted(exclusions.items())},
        "details": {
            "base_v0": base_v0,
            "base_v3": base_v3,
            "base_v3b": base_v3b,
            "base_v5": base_v5,
            "clean_v0": clean_v0,
            "clean_v3": clean_v3,
            "clean_v3b": clean_v3b,
            "clean_v5": clean_v5,
        },
    }

    # Compare to the reported robustness JSON.
    rep_joint = robust["part_b_merge"]["joint"]
    rep_sc = robust["part_b_merge"]["single_camera_exact"]
    robust_mismatch = []
    for name, vals in audit["v3b_merge"]["joint"].items():
        for phase in ("before", "after"):
            if vals[phase] != rep_joint[name][phase]:
                robust_mismatch.append(
                    {
                        "field": f"joint.{name}.{phase}",
                        "audit": vals[phase],
                        "report": rep_joint[name][phase],
                    }
                )
    for key in ("before", "after", "denominator"):
        if audit["v3b_merge"]["single_camera_exact"][key] != rep_sc[key]:
            robust_mismatch.append(
                {
                    "field": f"single_camera_exact.{key}",
                    "audit": audit["v3b_merge"]["single_camera_exact"][key],
                    "report": rep_sc[key],
                }
            )
    audit["v3b_merge"]["robustness_mismatch"] = robust_mismatch

    # ---- 6. self-consistency 17/20 -> 19/20 ------------------------------
    frames = selfc["frames"]
    before_rows = []
    after_rows = []
    for frame in frames:
        count = int(frame["count"])
        gold = int(frame["truth"])
        excluded = int(frame.get("excluded_n_max") or 0)
        after = max(0, count - excluded)
        before_rows.append({"frame": frame["frame"], "count": count, "truth": gold, "ok": count == gold})
        after_rows.append(
            {
                "frame": frame["frame"],
                "count": count,
                "after": after,
                "truth": gold,
                "excluded": excluded,
                "ok": after == gold,
            }
        )
    changes = [r for r in after_rows if r["after"] != r["count"]]
    audit["self_consistency"] = {
        "denominator": len(frames),
        "exact_before": sum(1 for r in before_rows if r["ok"]),
        "exact_after": sum(1 for r in after_rows if r["ok"]),
        "frames_changed": len(changes),
        "fixed": sum(1 for r in changes if r["ok"]),
        "broken": sum(1 for r in changes if not r["ok"]),
        "changes": changes,
        "reported_counterfactual": next(
            c for c in selfc["counterfactuals"] if c["id"] == "C_drop_ever_excluded"
        ),
    }

    # ---- 7. robustness aggregate arithmetic ------------------------------
    fact = robust["part_a_perturbation"]["factorial"]
    hist = fact["all_ok_histogram"]
    audit["robustness_aggregate"] = {
        "n_configs": fact["n_configs"],
        "histogram": hist,
        "histogram_sum": sum(int(v) for v in hist.values()),
        "stable_ge_6": fact["stable_ge_6"],
        "stable_ge_6_from_histogram": sum(
            int(v) for k, v in hist.items() if int(k) >= 6
        ),
        "reported_stable_ge_6": robust["part_a_perturbation"]["factorial"]["stable_ge_6"],
        "note": "aggregate-only cross-check; the 6,561-row grid is replayed separately",
    }

    # ---- 7b. supporting numbers in CEILING_DECOMPOSITION.md ---------------
    band = ceiling["pair_cap_and_band"]
    audit["ceiling_support"] = {
        "cap_only_all_ok": band["cap_only"]["all_ok"],
        "data_derived_s_all_ok": band["data_derived_s_intersection"]["all_ok"],
        "strict_s_all_ok": band["strict_s_intersection"]["all_ok"],
        "pixel_band_all_ok": band["estimated_pixel_band_sensitivity"]["all_ok"],
        "shipped_pairs_total": sum(len(rec["pairs"]) for rec in results),
        "data_derived_rejected_total": sum(
            len(m["rejected"]) for m in band["data_derived_s_intersection"]["moments"]
        ),
        "strict_rejected_total": sum(
            len(m["rejected"]) for m in band["strict_s_intersection"]["moments"]
        ),
        "pixel_rejected_total": sum(
            len(m["rejected"])
            for m in band["estimated_pixel_band_sensitivity"]["moments"]
        ),
    }

    # ---- 7c. supporting numbers in V3B_ROBUSTNESS.md ----------------------
    loo = robust["part_a_perturbation"]["loo"]
    v0_five = fact["v0_eq_5_regime"]
    clean_fact = robust["part_b_merge"]["clean_factorial"]
    audit["robustness_support"] = {
        "n_configs": fact["n_configs"],
        "stable_ge_6": fact["stable_ge_6"],
        "stable_ge_6_rate": fact["stable_ge_6_rate"],
        "loo_rows": len(loo),
        "loo_ge_6": sum(1 for r in loo if int(r["v3b_all_ok"]) >= 6),
        "loo_v3b_gt_v0": sum(1 for r in loo if int(r["v3b_all_ok"]) > int(r["v0_all_ok"])),
        "loo_v3b_lt_v0": sum(1 for r in loo if int(r["v3b_all_ok"]) < int(r["v0_all_ok"])),
        "v3b_gt_v0": fact["v3b_gt_v0"],
        "v3b_eq_v0": fact["v3b_eq_v0"],
        "v3b_lt_v0": fact["v3b_lt_v0"],
        "gt_eq_lt_sum": fact["v3b_gt_v0"] + fact["v3b_eq_v0"] + fact["v3b_lt_v0"],
        "broke_baseline_moment": fact["broke_baseline_moment"],
        "broke_baseline_rate": fact["broke_baseline_rate"],
        "v0_eq_5_n": v0_five["n"],
        "v0_eq_5_v3b_ge_6": v0_five["v3b_ge_6"],
        "v0_eq_5_v3b_le_4": sum(
            int(v) for k, v in v0_five["v3b_all_ok_histogram"].items() if int(k) <= 4
        ),
        "v0_eq_5_v3b_le_3": sum(
            int(v) for k, v in v0_five["v3b_all_ok_histogram"].items() if int(k) <= 3
        ),
        "v0_eq_5_mean_v3b": v0_five["mean_v3b_all_ok"],
        "clean_v5_ge_7": clean_fact["v5_ge_7"],
        "clean_v5_ge_7_rate": clean_fact["v5_ge_7_rate"],
        "clean_v5_ge_6": clean_fact["v5"]["stable_ge_6"],
        "clean_v5_ge_6_rate": clean_fact["v5"]["stable_ge_6_rate"],
    }

    # ---- 7d. supporting numbers in SELF_CONSISTENCY.md -------------------
    struct_bad = [f["frame"] for f in frames if f["flags"]["structurally_inconsistent"]]
    narrative_changed = [
        {"frame": f["frame"], "n_claim_changes": f["n_claim_changes"]}
        for f in frames
        if int(f["n_claim_changes"]) > 0
    ]
    excl_frames = [
        {"frame": f["frame"], "excluded_n_max": f["excluded_n_max"]}
        for f in frames
        if int(f["excluded_n_max"]) > 0
    ]
    audit["self_consistency_support"] = {
        "frames": len(frames),
        "sum_n_roofs": sum(int(f["n_roofs"]) for f in frames),
        "sum_n_vehicles": sum(int(f["n_vehicles"]) for f in frames),
        "sum_n_uncertain": sum(int(f["n_uncertain"]) for f in frames),
        "structural_bad_frames": struct_bad,
        "narrative_changed_frames": narrative_changed,
        "exclusion_frames": excl_frames,
        "exclusion_instances": sum(int(f["excluded_n_max"]) for f in frames),
    }

    # ---- 7e. machine-check every number quoted in NUMBER_AUDIT.md ---------
    rs = audit["robustness_support"]
    cs = audit["ceiling_support"]
    ss = audit["self_consistency_support"]
    vm = audit["v3b_merge"]
    checks = [
        ("shipped_all_ok", "CEILING_DECOMPOSITION.md:12", 5, audit["shipped"]["all_ok"]),
        (
            "single_camera_oracle",
            "CEILING_DECOMPOSITION.md:13",
            7,
            audit["single_camera_oracle"]["all_ok"],
        ),
        ("pair_oracle", "CEILING_DECOMPOSITION.md:14", 8, audit["pair_oracle"]["all_ok"]),
        ("both_oracle", "CEILING_DECOMPOSITION.md:15", 10, audit["both_oracle"]["all_ok"]),
        ("pair_cap_all_ok", "CEILING_DECOMPOSITION.md:44", 5, cs["cap_only_all_ok"]),
        (
            "data_derived_band_all_ok",
            "CEILING_DECOMPOSITION.md:45",
            5,
            cs["data_derived_s_all_ok"],
        ),
        ("strict_band_all_ok", "CEILING_DECOMPOSITION.md:46", 2, cs["strict_s_all_ok"]),
        ("pixel_band_all_ok", "CEILING_DECOMPOSITION.md:47", 0, cs["pixel_band_all_ok"]),
        (
            "shipped_pairs_total",
            "CEILING_DECOMPOSITION.md:55",
            16,
            cs["shipped_pairs_total"],
        ),
        (
            "data_derived_rejected",
            "CEILING_DECOMPOSITION.md:53",
            0,
            cs["data_derived_rejected_total"],
        ),
        ("strict_rejected", "CEILING_DECOMPOSITION.md:47-55", 12, cs["strict_rejected_total"]),
        ("pixel_rejected", "CEILING_DECOMPOSITION.md:55", 16, cs["pixel_rejected_total"]),
        ("factorial_configs", "V3B_ROBUSTNESS.md:11", 6561, rs["n_configs"]),
        ("stable_ge_6", "V3B_ROBUSTNESS.md:12", 433, rs["stable_ge_6"]),
        ("stable_ge_6_pct", "V3B_ROBUSTNESS.md:12", 6.6, 433 / 6561 * 100),
        ("loo_ge_6", "V3B_ROBUSTNESS.md:12", 5, rs["loo_ge_6"]),
        ("loo_rows", "V3B_ROBUSTNESS.md:12", 16, rs["loo_rows"]),
        ("v3b_gt_v0", "V3B_ROBUSTNESS.md:13", 1451, rs["v3b_gt_v0"]),
        ("v3b_eq_v0", "V3B_ROBUSTNESS.md:13", 4062, rs["v3b_eq_v0"]),
        ("v3b_lt_v0", "V3B_ROBUSTNESS.md:13", 1048, rs["v3b_lt_v0"]),
        (
            "broke_baseline",
            "V3B_ROBUSTNESS.md:14",
            1728,
            rs["broke_baseline_moment"],
        ),
        (
            "broke_baseline_pct",
            "V3B_ROBUSTNESS.md:14",
            26.3,
            rs["broke_baseline_rate"] * 100,
        ),
        ("v0_eq_5_n", "V3B_ROBUSTNESS.md:15", 1566, rs["v0_eq_5_n"]),
        ("v0_eq_5_v3b_ge_6", "V3B_ROBUSTNESS.md:15", 298, rs["v0_eq_5_v3b_ge_6"]),
        (
            "v0_eq_5_v3b_ge_6_pct",
            "V3B_ROBUSTNESS.md:15",
            19.0,
            rs["v0_eq_5_v3b_ge_6"] / rs["v0_eq_5_n"] * 100,
        ),
        ("v0_eq_5_v3b_le_4", "V3B_ROBUSTNESS.md:16", 267, rs["v0_eq_5_v3b_le_4"]),
        ("v0_eq_5_v3b_le_3", "V3B_ROBUSTNESS.md:16 (alternative reading)", 267, rs["v0_eq_5_v3b_le_3"]),
        ("v3b_before", "V3B_ROBUSTNESS.md:21", 6, vm["joint"]["V3b"]["before"]),
        ("v3b_after", "V3B_ROBUSTNESS.md:21", 6, vm["joint"]["V3b"]["after"]),
        ("v5_before", "V3B_ROBUSTNESS.md:25", 6, vm["joint"]["V5"]["before"]),
        ("v5_after", "V3B_ROBUSTNESS.md:25", 7, vm["joint"]["V5"]["after"]),
        (
            "single_camera_before",
            "V3B_ROBUSTNESS.md:18",
            17,
            vm["single_camera_exact"]["before"],
        ),
        (
            "single_camera_after",
            "V3B_ROBUSTNESS.md:18",
            19,
            vm["single_camera_exact"]["after"],
        ),
        (
            "single_camera_denominator",
            "V3B_ROBUSTNESS.md:18",
            20,
            vm["single_camera_exact"]["denominator"],
        ),
        ("clean_v5_ge_7", "V3B_ROBUSTNESS.md:26", 765, rs["clean_v5_ge_7"]),
        (
            "clean_v5_ge_7_pct",
            "V3B_ROBUSTNESS.md:26",
            11.7,
            rs["clean_v5_ge_7_rate"] * 100,
        ),
        (
            "clean_v5_ge_6_pct",
            "V3B_ROBUSTNESS.md:27",
            39.1,
            rs["clean_v5_ge_6_rate"] * 100,
        ),
        ("clean_v0_ge_7", "V3B_ROBUSTNESS.md:27", 297, robust["part_b_merge"]["clean_factorial"]["v0_ge_7"]),
        (
            "clean_v0_ge_7_pct",
            "V3B_ROBUSTNESS.md:27",
            4.5,
            robust["part_b_merge"]["clean_factorial"]["v0_ge_7"] / 6561 * 100,
        ),
        (
            "clean_v5_mean_delta",
            "V3B_ROBUSTNESS.md:27",
            0.78,
            robust["part_b_merge"]["clean_factorial"]["v5"]["mean_delta"],
        ),
        ("self_frames", "SELF_CONSISTENCY.md:4", 20, ss["frames"]),
        ("self_roofs", "SELF_CONSISTENCY.md:4", 81, ss["sum_n_roofs"]),
        ("self_vehicles", "SELF_CONSISTENCY.md:4", 73, ss["sum_n_vehicles"]),
        ("self_uncertain", "SELF_CONSISTENCY.md:4", 1, ss["sum_n_uncertain"]),
        (
            "self_structural_bad",
            "SELF_CONSISTENCY.md:12",
            0,
            len(ss["structural_bad_frames"]),
        ),
        (
            "self_narrative_changed",
            "SELF_CONSISTENCY.md:14",
            2,
            len(ss["narrative_changed_frames"]),
        ),
        (
            "self_c_changed",
            "SELF_CONSISTENCY.md:17",
            2,
            audit["self_consistency"]["frames_changed"],
        ),
        (
            "self_c_fixed",
            "SELF_CONSISTENCY.md:17",
            2,
            audit["self_consistency"]["fixed"],
        ),
        (
            "self_c_broken",
            "SELF_CONSISTENCY.md:17",
            0,
            audit["self_consistency"]["broken"],
        ),
        (
            "self_c_before",
            "SELF_CONSISTENCY.md:17",
            17,
            audit["self_consistency"]["exact_before"],
        ),
        (
            "self_c_after",
            "SELF_CONSISTENCY.md:17",
            19,
            audit["self_consistency"]["exact_after"],
        ),
    ]
    checked = []
    for cid, src, report, value in checks:
        if isinstance(report, float):
            match = abs(float(report) - float(value)) <= 0.051
        else:
            match = int(report) == int(round(float(value)))
        checked.append(
            {
                "id": cid,
                "source": src,
                "report": report,
                "audit": round(float(value), 3),
                "match": match,
            }
        )
    audit["number_checks"] = {
        "checked": len(checked),
        "mismatches": [c for c in checked if not c["match"]],
        "rows": checked,
    }

    # ---- 8. root hashes ---------------------------------------------------
    audit["hashes"] = {
        "results_old10": sha256_file(RESULTS).upper(),
        "truth": sha256_file(TRUTH).upper(),
        "self_consistency": sha256_file(SELF_CONSISTENCY).upper(),
        "ceiling_results": sha256_file(CEILING).upper(),
        "robustness_results": sha256_file(ROBUST).upper(),
    }

    text = json.dumps(audit, ensure_ascii=False, indent=2)
    if args.json:
        out = Path(args.json)
        out.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {out}")
    print(
        "shipped=%d/%d pair_oracle=%d/%d both=%d/%d single_oracle=%d/%d"
        % (
            audit["shipped"]["all_ok"],
            audit["shipped"]["denominator"],
            audit["pair_oracle"]["all_ok"],
            audit["pair_oracle"]["denominator"],
            audit["both_oracle"]["all_ok"],
            audit["both_oracle"]["denominator"],
            audit["single_camera_oracle"]["all_ok"],
            audit["single_camera_oracle"]["denominator"],
        )
    )
    print(
        "V3b=%d->%d V5=%d->%d exact=%d/%d->%d/%d"
        % (
            audit["v3b_merge"]["joint"]["V3b"]["before"],
            audit["v3b_merge"]["joint"]["V3b"]["after"],
            audit["v3b_merge"]["joint"]["V5"]["before"],
            audit["v3b_merge"]["joint"]["V5"]["after"],
            audit["v3b_merge"]["single_camera_exact"]["before"],
            audit["v3b_merge"]["single_camera_exact"]["denominator"],
            audit["v3b_merge"]["single_camera_exact"]["after"],
            audit["v3b_merge"]["single_camera_exact"]["denominator"],
        )
    )
    print(
        "self_consistency=%d/%d->%d/%d changes=%d fixed=%d broken=%d"
        % (
            audit["self_consistency"]["exact_before"],
            audit["self_consistency"]["denominator"],
            audit["self_consistency"]["exact_after"],
            audit["self_consistency"]["denominator"],
            audit["self_consistency"]["frames_changed"],
            audit["self_consistency"]["fixed"],
            audit["self_consistency"]["broken"],
        )
    )
    print(
        "mismatches: ceiling=%d robustness=%d queue=%d pair=%d compare_flag=%d quoted=%d"
        % (
            len(audit["single_camera_oracle"]["ceiling_mismatch"]),
            len(audit["v3b_merge"]["robustness_mismatch"]),
            len(audit["single_camera_oracle"]["queue_replay_mismatch"]),
            len(audit["single_camera_oracle"]["pair_replay_mismatch"]),
            len(audit["shipped"]["compare_flag_mismatch"]),
            len(audit["number_checks"]["mismatches"]),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
