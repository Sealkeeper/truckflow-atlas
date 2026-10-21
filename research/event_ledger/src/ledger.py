"""Evidence-bound event ledger; never propagate a count without current evidence."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

EVENTS = {"entered", "exited", "still_visible", "occluded", "reappeared", "seed_corrected"}


@dataclass
class EventLedger:
    camera: str
    previous_time: float | None = None
    states: dict[str, dict[str, Any]] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)

    def apply(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        time_s = float(snapshot["time_s"])
        if self.previous_time is not None and time_s <= self.previous_time:
            raise ValueError("snapshots must have strictly increasing timestamps")
        problems: list[str] = []
        observed: dict[str, dict[str, Any]] = {}
        for item in snapshot.get("visible_vehicles", []):
            vehicle_id = item.get("id")
            if not isinstance(vehicle_id, str) or not vehicle_id:
                problems.append("missing_vehicle_id")
                continue
            if vehicle_id in observed:
                problems.append(f"duplicate_vehicle_id:{vehicle_id}")
                continue
            bbox = item.get("bbox")
            valid_bbox = isinstance(bbox, list) and len(bbox) == 4 and all(
                isinstance(x, (int, float)) and 0 <= x <= 1 for x in bbox
            ) and bbox[0] < bbox[2] and bbox[1] < bbox[3]
            if not valid_bbox or not str(item.get("current_evidence", "")).strip():
                problems.append(f"missing_current_evidence:{vehicle_id}")
                continue
            observed[vehicle_id] = item
        events = snapshot.get("events", [])
        event_ids: dict[str, str] = {}
        for event in events:
            kind, vehicle_id = event.get("type"), event.get("id")
            if kind not in EVENTS or not vehicle_id or not event.get("evidence"):
                problems.append("invalid_event")
                continue
            if vehicle_id in event_ids:
                problems.append(f"conflicting_events:{vehicle_id}")
            event_ids[vehicle_id] = kind
            was_visible = self.states.get(vehicle_id, {}).get("status") == "visible"
            if kind in {"entered", "reappeared", "still_visible", "seed_corrected"} and vehicle_id not in observed:
                problems.append(f"event_without_current_vehicle:{vehicle_id}")
            if kind in {"exited", "occluded"} and vehicle_id in observed:
                problems.append(f"hidden_event_has_visible_vehicle:{vehicle_id}")
            if kind == "entered" and was_visible:
                problems.append(f"repeated_entry:{vehicle_id}")
            if kind == "reappeared" and vehicle_id not in self.states:
                problems.append(f"unknown_reappearance:{vehicle_id}")
        for vehicle_id in set(self.states) - set(observed):
            if self.states[vehicle_id]["status"] == "visible":
                kind = event_ids.get(vehicle_id)
                status = {"occluded": "occluded", "exited": "exited"}.get(kind, "unresolved_missing")
                self.states[vehicle_id] = {**self.states[vehicle_id], "status": status}
                if status == "unresolved_missing":
                    problems.append(f"unexplained_disappearance:{vehicle_id}")
        for vehicle_id, item in observed.items():
            if self.previous_time is not None and vehicle_id not in self.states and vehicle_id not in event_ids:
                problems.append(f"unexplained_new_vehicle:{vehicle_id}")
            self.states[vehicle_id] = {"status": "visible", "last_seen": time_s, "evidence": item}
        declared = snapshot.get("declared_total")
        if declared is not None and declared != len(observed):
            problems.append("declared_total_differs_from_current_evidence")
        problems.extend(str(x) for x in snapshot.get("uncertainties", []))
        row = {
            "camera": self.camera, "time_s": time_s,
            "visible_ids": sorted(observed), "predicted_count": len(observed),
            "events": events, "states": {k: v["status"] for k, v in self.states.items()},
            "review_required": bool(problems), "review_reasons": sorted(set(problems)),
        }
        self.previous_time = time_s
        self.history.append(row)
        return row
