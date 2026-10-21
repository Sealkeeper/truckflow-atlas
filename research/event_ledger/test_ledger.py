import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from ledger import EventLedger


def vehicle(vid="a"):
    return {"id": vid, "bbox": [.1, .1, .3, .4], "current_evidence": "red roof in current image"}


class LedgerTest(unittest.TestCase):
    def test_occlusion_is_not_visible_occupancy(self):
        ledger = EventLedger("north")
        ledger.apply({"time_s": 0, "visible_vehicles": [vehicle()]})
        out = ledger.apply({"time_s": 1, "visible_vehicles": [], "events": [{"id": "a", "type": "occluded", "evidence": "behind structure"}]})
        self.assertEqual(out["predicted_count"], 0)
        self.assertEqual(out["states"]["a"], "occluded")

    def test_missing_vehicle_does_not_silently_carry_forward(self):
        ledger = EventLedger("north")
        ledger.apply({"time_s": 0, "visible_vehicles": [vehicle()]})
        out = ledger.apply({"time_s": 1, "visible_vehicles": []})
        self.assertEqual(out["predicted_count"], 0)
        self.assertIn("unexplained_disappearance:a", out["review_reasons"])

    def test_reappearance_requires_current_evidence(self):
        ledger = EventLedger("north")
        out = ledger.apply({"time_s": 0, "visible_vehicles": [], "events": [{"id": "a", "type": "reappeared", "evidence": "same vehicle"}]})
        self.assertEqual(out["predicted_count"], 0)
        self.assertTrue(out["review_required"])

    def test_duplicate_ids_and_out_of_order_rejected(self):
        ledger = EventLedger("south")
        out = ledger.apply({"time_s": 0, "visible_vehicles": [vehicle(), vehicle()]})
        self.assertEqual(out["predicted_count"], 1)
        self.assertIn("duplicate_vehicle_id:a", out["review_reasons"])
        with self.assertRaises(ValueError):
            ledger.apply({"time_s": 0})

    def test_entry_with_visible_support(self):
        ledger = EventLedger("north")
        ledger.apply({"time_s": 0, "visible_vehicles": [vehicle()]})
        out = ledger.apply({"time_s": 1, "visible_vehicles": [vehicle(), vehicle("b")], "events": [{"id": "a", "type": "still_visible", "evidence": "same red roof"}, {"id": "b", "type": "entered", "evidence": "crossed image bottom"}]})
        self.assertEqual(out["predicted_count"], 2)
        self.assertFalse(out["review_required"])


if __name__ == "__main__":
    unittest.main()
