"""Minimal repros for PROTOCOL_FROZEN / parity.md. Read-only: builds documents
in memory and calls evaluator.evaluate(); never touches gold files or the network.

    python coord/evaluation-v3/parity_probe.py            # human table
    python coord/evaluation-v3/parity_probe.py --json out.json
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("evaluator", HERE / "evaluator.py")
evaluator = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(evaluator)


def vehicles(prefix: str, count: int) -> list[dict]:
    return [
        {
            "id": f"{prefix}{index}",
            "bbox": [0.05 + 0.2 * (index - 1), 0.1, 0.15, 0.2],
            "occlusion": "none",
            "truncation": "none",
        }
        for index in range(1, count + 1)
    ]


def camera(prefix: str, count: int) -> dict:
    return {
        "image": f"{prefix}.jpg",
        "sha256": "a" * 64,
        "width": 1280,
        "height": 960,
        "eligible": True,
        "vehicles": vehicles(prefix, count),
    }


def gold_doc(*, south: int = 2, north: int = 2, overlap: int = 1,
             quantity_truth: bool = True, identity_truth: bool = True,
             blank_counts: bool = False, vehicle_lists: bool = True,
             blank_lists_edges: bool = False) -> dict:
    quantities = (
        {"south": None, "north": None, "overlap": None, "unique": None}
        if blank_counts
        else {"south": south, "north": north, "overlap": overlap,
              "unique": south + north - overlap}
    )
    return {
        "schema": "truckflow-gold-v3",
        "dataset_id": "probe",
        "split": "development",
        "moments": [
            {
                "moment_id": "m1",
                "time_s": 1,
                "cameras": (
                    {"south": camera("s", south), "north": camera("n", north)}
                    if vehicle_lists
                    else {
                        "south": {**camera("s", 0), "vehicles": []},
                        "north": {**camera("n", 0), "vehicles": []},
                    }
                ),
                "overlap_edges": [] if blank_lists_edges else ([["s1", "s2"]] if south >= 2 else []),
                "cross_camera_pairs": [] if blank_lists_edges else ([["s1", "n1"]] if overlap >= 1 else []),
                "quantities": quantities,
                "truth_complete": {"quantity": quantity_truth, "identity": identity_truth},
            }
        ],
    }


def pred_doc(decision: str = "auto", *, south: int = 2, north: int = 2,
             overlap: int = 1, unique: int | None = None,
             extra_moment: bool = False) -> dict:
    unique = south + north - overlap if unique is None else unique
    return {
        "schema": "truckflow-predictions-v3",
        "dataset_id": "probe",
        "run_id": "probe",
        "moments": [
            {
                "moment_id": "m1",
                "decision": decision,
                "cameras": {
                    "south": {"status": "ok", "count": south, "objects_complete": True,
                              "vehicles": vehicles("s", south)},
                    "north": {"status": "ok", "count": north, "objects_complete": True,
                              "vehicles": vehicles("n", north)},
                },
                "overlap_edges": [["s1", "s2"]] if south >= 2 else [],
                "cross_camera_pairs": [["s1", "n1"]] if overlap >= 1 else [],
                "quantities": {"south": south, "north": north, "overlap": overlap, "unique": unique},
            }
        ],
    }


def mutate(doc: dict, moment: int = 0, **fields) -> dict:
    out = copy.deepcopy(doc)
    out["moments"][moment].update(fields)
    return out


def edge_gold(x: float, width: float) -> dict:
    doc = gold_doc()
    doc["moments"][0]["cameras"]["south"]["vehicles"][0]["bbox"] = [x, 0.1, width, 0.2]
    return doc


def edge_pred(x: float, width: float) -> dict:
    doc = pred_doc()
    doc["moments"][0]["cameras"]["south"]["vehicles"][0]["bbox"] = [x, 0.1, width, 0.2]
    return doc


def run(name: str, gold: dict, pred: dict | None) -> dict:
    try:
        report = evaluator.evaluate(gold, pred)
    except evaluator.EvalError as error:
        return {"case": name, "status": "EvalError", "detail": str(error)}
    quantity = report["primary_metrics"]["quantity_all_correct_rate"]
    identity = report["primary_metrics"]["identity_all_correct_rate"]
    return {
        "case": name,
        "status": "evaluated",
        "quantity": f'{quantity["numerator"]}/{quantity["denominator"]}',
        "identity": f'{identity["numerator"]}/{identity["denominator"]}',
        "decisions": report.get("decision_coverage"),
        "reasons": report["rows"][0]["reasons"],
    }


def cases() -> list[tuple[str, dict, dict | None]]:
    base_gold = gold_doc()
    base_pred = pred_doc()
    out: list[tuple[str, dict, dict | None]] = [
        ("P1 基线：两指标全对", base_gold, base_pred),
        ("P2 decision=review 但数字全对", base_gold, pred_doc("review")),
        ("P3 预测缺失该时刻", base_gold, {"schema": "truckflow-predictions-v3",
                                          "dataset_id": "probe", "run_id": "x", "moments": []}),
        ("P4 同机位重复 ID（objects_complete=true）", base_gold,
         mutate(base_pred, cameras={
             "south": {"status": "ok", "count": 2, "objects_complete": True,
                       "vehicles": [{"id": "s1", "bbox": [0.05, 0.1, 0.15, 0.2]},
                                    {"id": "s1", "bbox": [0.25, 0.1, 0.15, 0.2]}]},
             "north": base_pred["moments"][0]["cameras"]["north"]})),
        ("P5 南北同用一个 ID", base_gold,
         mutate(base_pred, cameras={
             "south": {"status": "ok", "count": 2, "objects_complete": True,
                       "vehicles": [{"id": "s1", "bbox": [0.05, 0.1, 0.15, 0.2]},
                                    {"id": "s2", "bbox": [0.25, 0.1, 0.15, 0.2]}]},
             "north": {"status": "ok", "count": 2, "objects_complete": True,
                       "vehicles": [{"id": "s1", "bbox": [0.05, 0.1, 0.15, 0.2]},
                                    {"id": "n2", "bbox": [0.25, 0.1, 0.15, 0.2]}]}})),
        ("P6 两个计数字段互相矛盾", base_gold,
         mutate(base_pred, cameras={
             "south": {"status": "ok", "count": 3, "objects_complete": False, "vehicles": []},
             "north": base_pred["moments"][0]["cameras"]["north"]})),
        ("P7 unique 违反公式（三项仍正确）", base_gold, pred_doc(unique=9)),
        ("P8 多出一个 gold 没有的预测时刻", base_gold,
         {"schema": "truckflow-predictions-v3", "dataset_id": "probe", "run_id": "x",
          "moments": base_pred["moments"] + [dict(base_pred["moments"][0], moment_id="m2")]}),
        ("P9 数量真值完整但车辆列表为空", gold_doc(vehicle_lists=False, blank_lists_edges=True),
         base_pred),
        ("P10 身份真值完整、数量真值留空", gold_doc(blank_counts=True, quantity_truth=False),
         base_pred),
        ("P11 重叠边重复", base_gold, mutate(base_pred, overlap_edges=[["s1", "s2"], ["s2", "s1"]])),
        ("P12 跨镜 pair 重复使用同一辆车", base_gold,
         mutate(base_pred, cross_camera_pairs=[["s1", "n1"], ["s1", "n2"]])),
        ("P13 预测 bbox 越界（x+w=1.5）但数量对", base_gold,
         mutate(pred_doc(), cameras={
             "south": {"status": "ok", "count": 2, "objects_complete": True,
                       "vehicles": [{"id": "s1", "bbox": [0.5, 0.1, 1.0, 0.2]},
                                    {"id": "s2", "bbox": [0.25, 0.1, 0.15, 0.2]}]},
             "north": base_pred["moments"][0]["cameras"]["north"]})),
        ("P14 预测 bbox 正好贴右边界（x+w=1）", edge_gold(0.85, 0.15), edge_pred(0.85, 0.15)),
        ("P15 bbox 超界 5e-10（在 1e-9 容差内）", edge_gold(0.85, 0.15),
         edge_pred(0.85, 0.1500000005)),
        ("P16 bbox 明显超界（0.9+0.2=1.1）", edge_gold(0.85, 0.15), edge_pred(0.9, 0.2)),
        ("P17 预测缺 decision 字段", base_gold,
         mutate(base_pred, decision=None, **{})),
        ("P18 gold unique 违反公式", gold_doc(), base_pred),
        ("P19 预测缺 quantities 字段", base_gold,
         mutate(base_pred, quantities=None)),
    ]
    # P17 must delete the key rather than set it to null.
    no_decision = copy.deepcopy(base_pred)
    no_decision["moments"][0].pop("decision")
    out[16] = ("P17 预测缺 decision 字段", base_gold, no_decision)
    # P18: gold says unique=99 while 2+2-1=3.
    bad_unique = gold_doc()
    bad_unique["moments"][0]["quantities"]["unique"] = 99
    out[17] = ("P18 gold unique 违反公式", bad_unique, base_pred)
    # P19: drop the whole quantities block.
    no_quantities = copy.deepcopy(base_pred)
    no_quantities["moments"][0].pop("quantities")
    out[18] = ("P19 预测缺 quantities 字段", base_gold, no_quantities)
    return out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default=None)
    args = parser.parse_args()
    results = [run(name, gold, pred) for name, gold, pred in cases()]
    width = max(len(row["case"]) for row in results)
    print(f'{"case".ljust(width)}  quantity  identity  status')
    for row in results:
        q = row.get("quantity", "-")
        i = row.get("identity", "-")
        print(f'{row["case"].ljust(width)}  {q:>8}  {i:>8}  {row["status"]}')
        if row["status"] == "EvalError":
            print(f'{"":{width}}  ! {row["detail"]}')
    print("\nis_bbox 边界表")
    for box in (
        [0.8, 0.1, 0.2, 0.2],
        [0.8, 0.1, 0.2000000001, 0.2],
        [0.8, 0.1, 0.200001, 0.2],
        [0.9, 0.1, 0.2, 0.2],
        [0.1, 0.1, 0.0, 0.2],
    ):
        print(f"  {box} -> {evaluator.is_bbox(box)}")
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
