"""Deterministic red-team cases for the TruckFlow v3 evaluator.

Every case is an in-memory pair of gold/prediction documents.  The audit
runner uses the same builders as the pytest suite, so the reported inputs and
the regression assertions cannot drift apart.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable


def vehicle(identifier: str, x: float, y: float = 0.1) -> dict[str, Any]:
    return {
        "id": identifier,
        "bbox": [x, y, 0.2, 0.2],
        "occlusion": "none",
        "truncation": "none",
    }


def camera(prefix: str, count: int) -> dict[str, Any]:
    return {
        "image": f"{prefix}.png",
        "sha256": "0" * 64,
        "width": 1000,
        "height": 1000,
        "eligible": True,
        "vehicles": [
            vehicle(f"{prefix}{index}", 0.1 + (index - 1) * 0.3)
            for index in range(1, count + 1)
        ],
    }


def gold_moment(
    moment_id: str = "m1",
    time_s: float = 10,
    *,
    south_count: int = 2,
    north_count: int = 2,
    overlap: int = 1,
) -> dict[str, Any]:
    south_prefix = "s" if moment_id == "m1" else f"{moment_id}s"
    north_prefix = "n" if moment_id == "m1" else f"{moment_id}n"
    cross = (
        [[f"{south_prefix}1", f"{north_prefix}1"]] if overlap == 1 else []
    )
    edges = [[f"{south_prefix}1", f"{south_prefix}2"]] if south_count == 2 else []
    return {
        "moment_id": moment_id,
        "time_s": time_s,
        "cameras": {
            "south": camera(south_prefix, south_count),
            "north": camera(north_prefix, north_count),
        },
        "overlap_edges": edges,
        "cross_camera_pairs": cross,
        "quantities": {
            "south": south_count,
            "north": north_count,
            "overlap": overlap,
            "unique": south_count + north_count - overlap,
        },
        "truth_complete": {"quantity": True, "identity": True},
    }


def prediction_moment(
    moment_id: str = "m1",
    *,
    south_count: int = 2,
    north_count: int = 2,
    overlap: int = 1,
) -> dict[str, Any]:
    south_prefix = "ps" if moment_id == "m1" else f"{moment_id}ps"
    north_prefix = "pn" if moment_id == "m1" else f"{moment_id}pn"
    south_vehicles = [
        vehicle(f"{south_prefix}{index}", 0.1 + (index - 1) * 0.3)
        for index in range(1, south_count + 1)
    ]
    north_vehicles = [
        vehicle(f"{north_prefix}{index}", 0.1 + (index - 1) * 0.3)
        for index in range(1, north_count + 1)
    ]
    return {
        "moment_id": moment_id,
        "decision": "auto",
        "cameras": {
            "south": {
                "status": "ok",
                "count": south_count,
                "objects_complete": True,
                "vehicles": south_vehicles,
            },
            "north": {
                "status": "ok",
                "count": north_count,
                "objects_complete": True,
                "vehicles": north_vehicles,
            },
        },
        "overlap_edges": (
            [[f"{south_prefix}1", f"{south_prefix}2"]]
            if south_count == 2
            else []
        ),
        "cross_camera_pairs": (
            [[f"{south_prefix}1", f"{north_prefix}1"]] if overlap == 1 else []
        ),
        "quantities": {
            "south": south_count,
            "north": north_count,
            "overlap": overlap,
            "unique": south_count + north_count - overlap,
        },
    }


def gold_document(moments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "schema": "truckflow-gold-v3",
        "dataset_id": "redteam-set",
        "split": "blind",
        "moments": moments if moments is not None else [gold_moment()],
    }


def prediction_document(
    moments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "truckflow-predictions-v3",
        "dataset_id": "redteam-set",
        "run_id": "redteam-zero-cost",
        "moments": (
            moments if moments is not None else [prediction_moment()]
        ),
    }


@dataclass
class Case:
    case_id: str
    attack: str
    expected: str
    gold: dict[str, Any]
    predictions: dict[str, Any]
    check: Callable[[dict[str, Any] | BaseException], bool]


def _rate(report: dict[str, Any], metric: str) -> float | None:
    return report["primary_metrics"][metric]["rate"]


def rejected(report: dict[str, Any] | BaseException) -> bool:
    """A structure attack passes only if evaluation refuses the document."""

    return isinstance(report, BaseException)


def identity_not_one(report: dict[str, Any] | BaseException) -> bool:
    return not isinstance(report, dict) or _rate(
        report, "identity_all_correct_rate"
    ) != 1.0


def quantity_not_one(report: dict[str, Any] | BaseException) -> bool:
    return not isinstance(report, dict) or _rate(
        report, "quantity_all_correct_rate"
    ) != 1.0


def both_not_one(report: dict[str, Any] | BaseException) -> bool:
    return not isinstance(report, dict) or (
        _rate(report, "quantity_all_correct_rate") != 1.0
        and _rate(report, "identity_all_correct_rate") != 1.0
    )


def _case(
    case_id: str,
    attack: str,
    expected: str,
    gold: dict[str, Any],
    predictions: dict[str, Any],
    check: Callable[[dict[str, Any] | BaseException], bool],
) -> Case:
    return Case(
        case_id=case_id,
        attack=attack,
        expected=expected,
        gold=copy.deepcopy(gold),
        predictions=copy.deepcopy(predictions),
        check=check,
    )


def build_cases() -> list[Case]:
    cases: list[Case] = []

    cases.append(
        _case(
            "A00-perfect",
            "完美 gold + 完美 prediction（防止永远不可能 100%）",
            "quantity=identity=1.0",
            gold_document(),
            prediction_document(),
            lambda r: isinstance(r, dict)
            and _rate(r, "quantity_all_correct_rate") == 1.0
            and _rate(r, "identity_all_correct_rate") == 1.0,
        )
    )

    duplicate_edge = prediction_document()
    duplicate_edge["moments"][0]["overlap_edges"] = [
        ["ps1", "ps2"],
        ["ps1", "ps2"],
    ]
    cases.append(
        _case(
            "A01-overlap-duplicate",
            "同一重叠边重复两次",
            "结构错误不得计身份正确",
            gold_document(),
            duplicate_edge,
            identity_not_one,
        )
    )

    mirrored_edge = prediction_document()
    mirrored_edge["moments"][0]["overlap_edges"] = [
        ["ps1", "ps2"],
        ["ps2", "ps1"],
    ]
    cases.append(
        _case(
            "A02-overlap-mirror",
            "镜像重复边 (a,b)/(b,a)",
            "镜像去重后仍属重复，身份必须失败",
            gold_document(),
            mirrored_edge,
            identity_not_one,
        )
    )

    self_edge = prediction_document()
    self_edge["moments"][0]["overlap_edges"] = [["ps1", "ps1"]]
    cases.append(
        _case(
            "A03-overlap-self-loop",
            "重叠边自环 (a,a)",
            "自环必须被拒绝，身份必须失败",
            gold_document(),
            self_edge,
            identity_not_one,
        )
    )

    duplicate_pair = prediction_document()
    duplicate_pair["moments"][0]["cross_camera_pairs"] = [
        ["ps1", "pn1"],
        ["ps1", "pn1"],
    ]
    cases.append(
        _case(
            "A04-cross-duplicate",
            "跨镜 pair 重复",
            "重复 pair 必须拒绝，身份失败",
            gold_document(),
            duplicate_pair,
            identity_not_one,
        )
    )

    multi_pair = prediction_document()
    multi_pair["moments"][0]["cross_camera_pairs"] = [
        ["ps1", "pn1"],
        ["ps1", "pn2"],
    ]
    cases.append(
        _case(
            "A05-cross-multi",
            "同一 south 同时配两个 north",
            "一对象多配必须拒绝，身份失败",
            gold_document(),
            multi_pair,
            identity_not_one,
        )
    )

    wrong_camera = prediction_document()
    wrong_camera["moments"][0]["cross_camera_pairs"] = [["ps1", "ps2"]]
    cases.append(
        _case(
            "A06-cross-wrong-camera",
            "pair 指向同一机位",
            "必须拒绝同机位 pair，身份失败",
            gold_document(),
            wrong_camera,
            identity_not_one,
        )
    )

    unknown_pair = prediction_document()
    unknown_pair["moments"][0]["cross_camera_pairs"] = [["ps1", "ghost"]]
    cases.append(
        _case(
            "A07-cross-unknown-id",
            "pair 引用不存在的 id",
            "必须拒绝悬空 pair，身份失败",
            gold_document(),
            unknown_pair,
            identity_not_one,
        )
    )

    duplicate_pred_id = prediction_document()
    duplicate_pred_id["moments"][0]["cameras"]["south"]["vehicles"][1][
        "id"
    ] = "ps1"
    cases.append(
        _case(
            "A08-duplicate-id-intra",
            "同一机位两个预测车辆复用同一 id",
            "重复 id 不得被身份指标静默接受（数量诊断可独立保留）",
            gold_document(),
            duplicate_pred_id,
            identity_not_one,
        )
    )

    duplicate_pred_id_cross = prediction_document()
    duplicate_pred_id_cross["moments"][0]["cameras"]["north"]["vehicles"][0][
        "id"
    ] = "ps1"
    cases.append(
        _case(
            "A09-duplicate-id-cross",
            "南北两个预测车辆复用同一 id",
            "跨机位重复 id 不得被身份指标静默接受（数量诊断可独立保留）",
            gold_document(),
            duplicate_pred_id_cross,
            identity_not_one,
        )
    )

    review = prediction_document()
    review["moments"][0]["decision"] = "review"
    cases.append(
        _case(
            "A10-review",
            "原始答案完全正确但 decision=review",
            "两个主指标均计失败",
            gold_document(),
            review,
            both_not_one,
        )
    )

    abstain = prediction_document()
    abstain["moments"][0]["decision"] = "abstain"
    cases.append(
        _case(
            "A11-abstain-moment",
            "原始答案完全正确但 decision=abstain",
            "两个主指标均计失败",
            gold_document(),
            abstain,
            both_not_one,
        )
    )

    invalid_moment = prediction_document()
    invalid_moment["moments"][0]["decision"] = "invalid"
    cases.append(
        _case(
            "A12-invalid-moment",
            "原始答案完全正确但 decision=invalid",
            "两个主指标均计失败",
            gold_document(),
            invalid_moment,
            both_not_one,
        )
    )

    missing_moment = prediction_document([])
    cases.append(
        _case(
            "A13-missing-moment",
            "完全删除预测时刻",
            "固定数量分母仍为 1，且计失败",
            gold_document(),
            missing_moment,
            lambda r: isinstance(r, dict)
            and r["primary_metrics"]["quantity_all_correct_rate"]["denominator"]
            == 1
            and _rate(r, "quantity_all_correct_rate") == 0.0,
        )
    )

    camera_abstain = prediction_document()
    camera_abstain["moments"][0]["cameras"]["south"]["status"] = "abstain"
    cases.append(
        _case(
            "A14-camera-abstain",
            "moment=auto，但 south camera status=abstain，同时手填正确 quantities",
            "拒答机位不得让数量指标自动成功",
            gold_document(),
            camera_abstain,
            both_not_one,
        )
    )

    camera_missing = prediction_document()
    del camera_missing["moments"][0]["cameras"]["south"]
    cases.append(
        _case(
            "A14b-camera-missing",
            "moment=auto，但 south camera 整块缺失，同时手填正确 quantities",
            "缺失机位不得让数量指标自动成功",
            gold_document(),
            camera_missing,
            both_not_one,
        )
    )

    camera_partial = prediction_document()
    camera_partial["moments"][0]["cameras"]["south"][
        "objects_complete"
    ] = False
    cases.append(
        _case(
            "A14c-camera-objects-incomplete",
            "moment=auto，但 south objects_complete=false，同时手填正确 quantities",
            "数量可独立计正确；身份必须失败（两指标分离）",
            gold_document(),
            camera_partial,
            lambda r: isinstance(r, dict)
            and _rate(r, "quantity_all_correct_rate") == 1.0
            and _rate(r, "identity_all_correct_rate") == 0.0,
        )
    )

    camera_count_null = prediction_document()
    camera_count_null["moments"][0]["cameras"]["south"]["count"] = None
    cases.append(
        _case(
            "A14d-camera-count-null",
            "moment=auto、vehicles 完整，但 south camera.count=null，quantities 手填正确",
            "缺失机位计数不得让数量指标自动成功",
            gold_document(),
            camera_count_null,
            quantity_not_one,
        )
    )

    camera_contradiction = prediction_document()
    camera_contradiction["moments"][0]["cameras"]["south"]["count"] = 0
    camera_contradiction["moments"][0]["cameras"]["south"]["vehicles"] = []
    cases.append(
        _case(
            "A14e-camera-contradiction",
            "south camera 报 count=0/vehicles=[]，但 moment quantities.south=2",
            "同一时刻两处数量互相矛盾，不得让数量指标成功",
            gold_document(),
            camera_contradiction,
            quantity_not_one,
        )
    )

    camera_invalid = prediction_document()
    camera_invalid["moments"][0]["cameras"]["south"]["status"] = "invalid"
    cases.append(
        _case(
            "A15-camera-invalid",
            "moment=auto，但 south camera status=invalid，同时手填正确 quantities",
            "无效机位不得让数量指标自动成功",
            gold_document(),
            camera_invalid,
            both_not_one,
        )
    )

    partial_quantity = gold_document()
    partial_quantity["moments"][0]["truth_complete"]["quantity"] = False
    partial_quantity["moments"][0]["quantities"] = {
        "south": None,
        "north": None,
        "overlap": None,
        "unique": None,
    }
    cases.append(
        _case(
            "A16-partial-truth",
            "quantity truth_complete=false 且 quantities 全 null；identity 完整",
            "数量分母=0、身份分母=1，不抛错",
            partial_quantity,
            prediction_document(),
            lambda r: isinstance(r, dict)
            and r["primary_metrics"]["quantity_all_correct_rate"]["denominator"]
            == 0
            and r["primary_metrics"]["identity_all_correct_rate"]["denominator"]
            == 1,
        )
    )

    both_partial = gold_document()
    both_partial["moments"][0]["truth_complete"] = {
        "quantity": False,
        "identity": False,
    }
    both_partial["moments"][0]["quantities"] = {
        "south": None,
        "north": None,
        "overlap": None,
        "unique": None,
    }
    cases.append(
        _case(
            "A17-both-partial-null",
            "两项 truth_complete=false 且 quantities 全 null",
            "两个分母均为 0、rate=null，不抛错",
            both_partial,
            prediction_document(),
            lambda r: isinstance(r, dict)
            and r["primary_metrics"]["quantity_all_correct_rate"]["denominator"]
            == 0
            and r["primary_metrics"]["identity_all_correct_rate"]["denominator"]
            == 0
            and _rate(r, "quantity_all_correct_rate") is None
            and _rate(r, "identity_all_correct_rate") is None,
        )
    )

    nan_prediction = prediction_document()
    nan_prediction["moments"][0]["cameras"]["south"]["vehicles"][0]["bbox"] = [
        0.1,
        0.1,
        float("nan"),
        0.2,
    ]
    cases.append(
        _case(
            "A18-bbox-nan",
            "预测 bbox 含 NaN",
            "不得当作有效框参与成功判定",
            gold_document(),
            nan_prediction,
            identity_not_one,
        )
    )

    zero_area = prediction_document()
    zero_area["moments"][0]["cameras"]["south"]["vehicles"][0]["bbox"] = [
        0.1,
        0.1,
        0.0,
        0.2,
    ]
    cases.append(
        _case(
            "A19-bbox-zero-area",
            "预测 bbox 宽为 0",
            "不得当作有效框参与成功判定",
            gold_document(),
            zero_area,
            identity_not_one,
        )
    )

    half_iou_gold = gold_document(
        [
            {
                "moment_id": "m1",
                "time_s": 10,
                "cameras": {
                    "south": {
                        "image": "s.png",
                        "sha256": "0" * 64,
                        "width": 1000,
                        "height": 1000,
                        "eligible": True,
                        "vehicles": [
                            {
                                "id": "s1",
                                "bbox": [0.0, 0.0, 0.2, 0.2],
                                "occlusion": "none",
                                "truncation": "none",
                            }
                        ],
                    },
                    "north": camera("n", 1),
                },
                "overlap_edges": [],
                "cross_camera_pairs": [],
                "quantities": {
                    "south": 1,
                    "north": 1,
                    "overlap": 0,
                    "unique": 2,
                },
                "truth_complete": {"quantity": True, "identity": True},
            }
        ]
    )
    half_iou_prediction = prediction_document(
        [
            {
                "moment_id": "m1",
                "decision": "auto",
                "cameras": {
                    "south": {
                        "status": "ok",
                        "count": 1,
                        "objects_complete": True,
                        "vehicles": [
                            {
                                "id": "ps1",
                                "bbox": [0.05, 0.0, 0.1, 0.2],
                                "occlusion": "none",
                            }
                        ],
                    },
                    "north": {
                        "status": "ok",
                        "count": 1,
                        "objects_complete": True,
                        "vehicles": [vehicle("pn1", 0.1)],
                    },
                },
                "overlap_edges": [],
                "cross_camera_pairs": [],
                "quantities": {
                    "south": 1,
                    "north": 1,
                    "overlap": 0,
                    "unique": 2,
                },
            }
        ]
    )
    cases.append(
        _case(
            "A20-iou-exactly-0.5",
            "唯一匹配 IoU 恰好 0.5",
            "按协议 IoU>=0.5 应建立匹配，身份=1",
            half_iou_gold,
            half_iou_prediction,
            lambda r: isinstance(r, dict)
            and _rate(r, "identity_all_correct_rate") == 1.0,
        )
    )

    tiny_oob = prediction_document()
    tiny_oob["moments"][0]["cameras"]["south"]["vehicles"][0]["bbox"] = [
        0.9,
        0.1,
        0.1000005,
        0.2,
    ]
    tiny_oob_gold = gold_document()
    tiny_oob_gold["moments"][0]["cameras"]["south"]["vehicles"][0][
        "bbox"
    ] = [0.9, 0.1, 0.1, 0.2]
    cases.append(
        _case(
            "A21-bbox-tiny-oob",
            "bbox 右边界=1.0000005，仅越界 5e-7；其余完全正确",
            "越界框必须被判无效，不得身份=1",
            tiny_oob_gold,
            tiny_oob,
            identity_not_one,
        )
    )

    quantity_right_identity_wrong = prediction_document()
    quantity_right_identity_wrong["moments"][0]["cross_camera_pairs"] = [
        ["ps2", "pn1"]
    ]
    cases.append(
        _case(
            "A22-count-right-identity-wrong",
            "数量完全正确，但跨镜身份配对错误",
            "quantity=1、identity=0，两指标分离",
            gold_document(),
            quantity_right_identity_wrong,
            lambda r: isinstance(r, dict)
            and _rate(r, "quantity_all_correct_rate") == 1.0
            and _rate(r, "identity_all_correct_rate") == 0.0,
        )
    )

    two_moments_gold = gold_document(
        [gold_moment("m1", 10), gold_moment("m2", 20)]
    )
    two_moments_predictions = prediction_document(
        [prediction_moment("m1"), prediction_moment("m2")]
    )
    two_moments_predictions["moments"].pop()
    cases.append(
        _case(
            "A23-delete-failed-moment",
            "删除失败时刻的预测，保留 gold 两时刻",
            "分母固定为 2，缺失时刻计失败",
            two_moments_gold,
            two_moments_predictions,
            lambda r: isinstance(r, dict)
            and r["primary_metrics"]["quantity_all_correct_rate"]["denominator"]
            == 2
            and r["primary_metrics"]["quantity_all_correct_rate"]["numerator"]
            == 1,
        )
    )

    duplicate_gold_moment = gold_document(
        [gold_moment("m1", 10), gold_moment("m1", 20)]
    )
    cases.append(
        _case(
            "A24-duplicate-gold-moment-id",
            "gold 重复 moment_id",
            "必须抛 EvalError",
            duplicate_gold_moment,
            prediction_document(),
            rejected,
        )
    )

    duplicate_pred_moment = prediction_document(
        [prediction_moment("m1"), prediction_moment("m1")]
    )
    cases.append(
        _case(
            "A25-duplicate-prediction-moment-id",
            "prediction 重复 moment_id",
            "必须抛 EvalError",
            gold_document(),
            duplicate_pred_moment,
            rejected,
        )
    )

    duplicate_time_gold = gold_document(
        [gold_moment("m1", 10), gold_moment("m2", 20), gold_moment("m3", 20)]
    )
    duplicate_time_pred = prediction_document(
        [
            prediction_moment("m1"),
            prediction_moment("m2"),
            prediction_moment("m3"),
        ]
    )
    duplicate_time_pred["moments"][1]["quantities"]["south"] = 1
    duplicate_time_pred["moments"][1]["quantities"]["unique"] = 2
    cases.append(
        _case(
            "A26-duplicate-time-s",
            "time_s=20 有两个 moment_id（m2 错误、m3 正确），把正确时刻重复以抬高比例",
            "必须拒绝重复 time_s，或分母仍为 2（正确率为 50%）",
            duplicate_time_gold,
            duplicate_time_pred,
            lambda r: isinstance(r, BaseException)
            or r["primary_metrics"]["quantity_all_correct_rate"]["denominator"]
            == 2,
        )
    )

    return cases
