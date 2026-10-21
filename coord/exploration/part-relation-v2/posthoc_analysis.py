#!/usr/bin/env python3
"""Post-hoc audit of the roof-relation raw outputs.

This does NOT call the model and does NOT replace the frozen primary metrics.
It tests a generic local-pairing rule on the same raw outputs:
  - same_top_surface always merges;
  - a composition_unknown cab+cargo pair may merge only when the two top boxes
    are longitudinally adjacent (small vertical gap, x-overlap) and neither unit
    already has a cab/trailer partner (one-to-one, no transitive chain);
  - tops whose own visible_evidence says forklift/forklift-like are excluded
    from truck count;
  - visible but unconfirmed tops are kept as unresolved candidates for the
    upper bound, not silently dropped.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


SESS = Path(__file__).resolve().parent
PUB = SESS.parents[1] / "all-sessions-can-see" / "coord" / "exploration" / "part-relation-v2"
TRUTH = SESS.parents[1] / "all-sessions-can-see" / "accuracy" / "reviewed" / "user-final-review-v2-2026-10-21.json"
B_RAW = SESS.parents[1] / "all-sessions-can-see" / "coord" / "exploration" / "single-pass" / "raw" / "B_aisle"

CARGO = {"cargo_roof", "trailer_roof", "open_top"}
CAB = {"cab_roof"}
NON_TRUCK_MARKERS = ("叉车", "forklift")


class UF:
    def __init__(self, items: list[str]):
        self.p = {x: x for x in items}

    def find(self, x: str) -> str:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def map_far_bbox(bbox: list[float], rec: dict[str, Any]) -> list[float]:
    x0, y0, x1, y1 = rec["far"]["crop_overview_norm"]
    a, b, c, d = bbox
    return [x0 + a * (x1 - x0), y0 + b * (y1 - y0), x0 + c * (x1 - x0), y0 + d * (y1 - y0)]


def x_overlap(a: list[float], b: list[float]) -> float:
    inter = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    denom = min(a[2] - a[0], b[2] - b[0])
    return inter / denom if denom > 0 else 0.0


def vertical_gap(a: list[float], b: list[float]) -> float:
    return min(abs(a[1] - b[3]), abs(b[1] - a[3]))


def truth_counts() -> dict[str, int]:
    data = json.loads(TRUTH.read_text(encoding="utf-8"))
    out: dict[str, int] = {}
    for s in data["samples"]:
        out[f"north_{s['time']}"] = s["camera_counts"]["north"]
        out[f"south_{s['time']}"] = s["camera_counts"]["south"]
    return out


def b_counts(sid: str) -> list[int | None]:
    out: list[int | None] = []
    for run in ("r1", "r2", "r3"):
        p = B_RAW / run / f"{sid}.json"
        out.append(len(json.loads(p.read_text(encoding="utf-8")).get("vehicles") or []) if p.exists() else None)
    return out


def build_units(tops: dict[str, dict[str, Any]], relations: list[dict[str, Any]]) -> dict[str, list[str]]:
    uf = UF(list(tops))
    for r in relations:
        if r.get("relation") == "same_top_surface" and r.get("a") in tops and r.get("b") in tops:
            uf.union(r["a"], r["b"])
    comps: dict[str, list[str]] = {}
    for k in tops:
        comps.setdefault(uf.find(k), []).append(k)
    return comps


def apply_local_pairs(
    tops: dict[str, dict[str, Any]],
    relations: list[dict[str, Any]],
    base: dict[str, list[str]],
    max_vertical: float,
    max_gap_px: float,
) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    # Work on the same-top components; local composition edges connect components.
    comp_of = {}
    for root, ids in base.items():
        for i in ids:
            comp_of[i] = root
    candidates = []
    for r in relations:
        if r.get("relation") != "composition_unknown":
            continue
        a, b = r.get("a"), r.get("b")
        if a not in tops or b not in tops:
            continue
        ka, kb = tops[a]["kind"], tops[b]["kind"]
        if not ((ka in CAB and kb in CARGO) or (kb in CAB and ka in CARGO)):
            continue
        ab, bb = tops[a].get("_bbox"), tops[b].get("_bbox")
        if not ab or not bb:
            continue
        vg = vertical_gap(ab, bb)
        xo = x_overlap(ab, bb)
        gap = r.get("gap_px")
        if gap is None or gap > max_gap_px:
            continue
        if vg <= max_vertical and xo >= 0.3:
            candidates.append(
                {
                    "a": a,
                    "b": b,
                    "gap_px": gap,
                    "vertical_gap": round(vg, 4),
                    "x_overlap": round(xo, 4),
                    "root_a": comp_of[a],
                    "root_b": comp_of[b],
                }
            )
    candidates.sort(key=lambda x: (x["gap_px"], x["vertical_gap"]))
    # One-to-one greedy matching between top components. This prevents a chain
    # from merging all trucks through adjacent pair edges.
    paired: set[str] = set()
    accepted = []
    for c in candidates:
        if c["root_a"] == c["root_b"]:
            continue
        if c["root_a"] in paired or c["root_b"] in paired:
            continue
        paired.add(c["root_a"])
        paired.add(c["root_b"])
        accepted.append(c)
    # Union accepted pairs by top IDs.
    uf = UF(list(tops))
    for root, ids in base.items():
        for i in ids[1:]:
            uf.union(ids[0], i)
    for c in accepted:
        uf.union(c["a"], c["b"])
    comps: dict[str, list[str]] = {}
    for k in tops:
        comps.setdefault(uf.find(k), []).append(k)
    return comps, accepted


def analyse_sample(sid: str, rec: dict[str, Any], truth: int) -> dict[str, Any]:
    raw = json.loads((SESS / "raw" / f"{sid}.json").read_text(encoding="utf-8"))
    p = raw.get("parsed") or {}
    tops = {t["top_id"]: dict(t) for t in p.get("tops", []) if t.get("top_id")}
    for t in tops.values():
        b = t.get("roof_bbox")
        t["_bbox"] = map_far_bbox(b, rec) if t.get("view") == "far" and b else b
    relations = p.get("relations") or []
    base = build_units(tops, relations)

    result: dict[str, Any] = {
        "sample_id": sid,
        "truth": truth,
        "b_counts": b_counts(sid),
        "top_observations": len(tops),
        "same_top_units": len(base),
        "sensitivity": {},
    }
    for label, max_v, max_gap in [("tight", 0.02, 25.0), ("main", 0.03, 30.0), ("loose", 0.04, 35.0)]:
        comps, accepted = apply_local_pairs(tops, relations, base, max_v, max_gap)
        confirmed = []
        unresolved = []
        non_truck = []
        for ids in comps.values():
            evidence = " ".join(tops[i].get("visible_evidence", "") for i in ids)
            kinds = {tops[i].get("kind") for i in ids}
            locatable = all(tops[i].get("locatable", True) for i in ids)
            unknown = any(tops[i].get("kind") == "unknown" or tops[i].get("top_state") in {"unknown", "occluded"} for i in ids)
            if any(m in evidence for m in NON_TRUCK_MARKERS) and "货车" not in evidence and kinds <= {"cab_roof", "unknown"}:
                non_truck.append(sorted(ids))
            elif locatable and not unknown:
                confirmed.append(sorted(ids))
            else:
                unresolved.append(sorted(ids))
        lower = len(confirmed)
        upper = lower + len(unresolved)
        point = lower if not unresolved else None
        result["sensitivity"][label] = {
            "accepted_local_pairs": accepted,
            "top_units": len(comps),
            "confirmed_units": confirmed,
            "unresolved_units": unresolved,
            "non_truck_units_excluded": non_truck,
            "count_lower": lower,
            "count_upper": upper,
            "count_point": point,
            "point_exact": bool(point is not None and point == truth),
            "range_contains_truth": lower <= truth <= upper,
        }
    result["main"] = result["sensitivity"]["main"]
    return result


def main() -> None:
    frozen = json.loads((SESS / "frozen_inputs.json").read_text(encoding="utf-8"))
    truth = truth_counts()
    rows = [analyse_sample(s["sample_id"], s, truth[s["sample_id"]]) for s in frozen["samples"]]
    primary = json.loads((SESS / "metrics.json").read_text(encoding="utf-8"))
    summary = {
        "schema": "roof-relation-v2-posthoc-local-pairing",
        "created_at": "2026-10-21",
        "new_model_calls": 0,
        "not_a_frozen_score": True,
        "rule": "same_top_surface merge; one-to-one composition_unknown cab+cargo local pairing (vertical gap<=0.03, x-overlap>=0.3, gap_px<=30); evidence-labeled forklift excluded; visible unknown tops kept as upper-bound candidates",
        "primary_frozen": {
            "resolved_count": primary["resolved_count"],
            "exact_point_count": primary["exact_point_count"],
            "range_contains_truth_count": primary["range_contains_truth_count"],
            "valid_count": primary["valid_count"],
        },
        "posthoc": {
            "point_exact_count": sum(1 for r in rows if r["main"]["point_exact"]),
            "range_contains_truth_count": sum(1 for r in rows if r["main"]["range_contains_truth"]),
            "sample_count": len(rows),
        },
        "rows": rows,
        "limits": [
            "post-hoc analysis of the same 4 raw responses; no new calls",
            "thresholds are generic geometry settings, but the analysis was run after seeing the raw outputs",
            "not a substitute for the frozen primary metrics or a 20-frame regression",
            "no complete top/relation gold",
        ],
    }
    (SESS / "posthoc_metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    PUB.mkdir(parents=True, exist_ok=True)
    (PUB / "posthoc_metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for r in rows:
        m = r["main"]
        print(
            r["sample_id"],
            "truth", r["truth"],
            "B", r["b_counts"],
            "tops", r["top_observations"],
            "point", m["count_point"],
            "range", [m["count_lower"], m["count_upper"]],
            "confirmed", len(m["confirmed_units"]),
            "unresolved", m["unresolved_units"],
            "non_truck", m["non_truck_units_excluded"],
            "pairs", len(m["accepted_local_pairs"]),
        )


if __name__ == "__main__":
    main()
