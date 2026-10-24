"""Deterministic checks for the published roof-counting post-processor."""

from __future__ import annotations

import unittest

from roofs import (
    ROOF_PROMPT_VERSION,
    ROOF_SCHEME_ID,
    absorb,
    count_units,
    roots_from_payload,
)


def root(
    group_id: str,
    width: float,
    *,
    x: float = 0.2,
    y: float = 0.2,
    origin: str = "vehicle",
) -> dict:
    return {
        "id": group_id,
        "bbox": [x, y, x + width, y + 0.2],
        "origin": origin,
        "size": "large",
        "roof_ids": [group_id],
    }


class RoofAbsorptionTests(unittest.TestCase):
    def test_scheme_id_and_prompt_version_are_published(self):
        self.assertEqual(ROOF_PROMPT_VERSION, "roof-count-v1")
        self.assertIn("full+far55", ROOF_SCHEME_ID)
        self.assertIn("absorb-0.55-0.15-0.02", ROOF_SCHEME_ID)

    def test_narrow_fragment_is_folded_into_wide_body(self):
        units = absorb([root("wide", 0.40), root("fragment", 0.20)])
        self.assertEqual([unit["id"] for unit in units], ["wide"])
        self.assertEqual(count_units({
            "roofs": [
                {"roof_id": "R1", "roof_bbox": [0.2, 0.2, 0.6, 0.4]},
                {"roof_id": "R2", "roof_bbox": [0.2, 0.4, 0.4, 0.6]},
            ],
            "vehicles": [
                {"vehicle_id": "V1", "roof_ids": ["R1"]},
                {"vehicle_id": "V2", "roof_ids": ["R2"]},
            ],
            "uncertain": [],
        })[1], 2)

    def test_wide_and_narrow_distinct_bodies_remain_two(self):
        units = absorb([root("left", 0.40), root("right", 0.30, x=0.70)])
        self.assertEqual(len(units), 2)

    def test_uncertain_group_uses_looser_width_limit(self):
        roots = [root("wide", 0.40), root("fragment", 0.23, origin="uncertain")]
        self.assertEqual(len(absorb(roots)), 1)

    def test_normal_group_rejects_the_same_ratio(self):
        roots = [root("wide", 0.40), root("fragment", 0.23)]
        self.assertEqual(len(absorb(roots)), 2)

    def test_uncertain_group_still_requires_vertical_proximity(self):
        roots = [root("wide", 0.40), root("fragment", 0.20, y=0.60, origin="uncertain")]
        self.assertEqual(len(absorb(roots)), 2)

    def test_group_bbox_is_union_of_roofs(self):
        roots = roots_from_payload({
            "roofs": [
                {"roof_id": "R1", "roof_bbox": [0.1, 0.1, 0.4, 0.2]},
                {"roof_id": "R2", "roof_bbox": [0.3, 0.2, 0.5, 0.3]},
            ],
            "vehicles": [{"vehicle_id": "V1", "roof_ids": ["R1", "R2"]}],
            "uncertain": [],
        })
        self.assertEqual(roots[0]["bbox"], [0.1, 0.1, 0.5, 0.3])


if __name__ == "__main__":
    unittest.main()
