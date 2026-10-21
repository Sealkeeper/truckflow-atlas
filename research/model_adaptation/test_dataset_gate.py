"""Synthetic metadata tests only; no real labels, files, network, weights or training."""
import copy
import unittest

from dataset_gate import export_row, validate


def sample(sid="a", split="train"):
    return {
        "sample_id": sid, "split": split, "capture_session_id": "session-" + sid,
        "camera": "north", "time_block": "block-" + sid, "near_duplicate_group": "near-" + sid,
        "near_duplicate_audited": True, "sha256": ("a" if sid == "a" else "b") * 64,
        "image": f"raw/{sid}.jpg", "image_kind": "raw_unannotated", "width": 1280, "height": 960,
        "context_start_s": 100, "context_end_s": 100, "review_status": "dual_agreed",
        "reviewers": ["synthetic_reviewer_1", "synthetic_reviewer_2"], "label_source": "human",
        "training_rights_confirmed": True, "evaluation_only": False, "source_set": "synthetic_test",
        "all_visible_trucks_labeled": True, "count": 1,
        "vehicles": [{"observation_id": "observation-1", "bbox_px": [128, 192, 640, 768],
                      "type": "unknown", "visibility": "partial", "evidence": "synthetic visible cargo roof",
                      "vehicle_session_id": "vehicle-" + sid}],
    }


class DatasetGateTests(unittest.TestCase):
    def test_valid_independent_splits(self):
        self.assertEqual(validate([sample(), sample("b", "blind")]), [])

    def test_exact_and_near_duplicates_fail(self):
        b = sample("b", "blind")
        b["sha256"] = "a" * 64
        b["near_duplicate_group"] = "near-a"
        self.assertTrue(any("cross_split_group:hash" in e for e in validate([sample(), b])))
        self.assertTrue(any("cross_split_group:near" in e for e in validate([sample(), b])))

    def test_same_time_other_camera_fails(self):
        b = sample("b", "blind")
        b.update(capture_session_id="session-a", camera="south", time_block="block-a")
        errors = validate([sample(), b])
        self.assertTrue(any("cross_split_temporal_guard" in e for e in errors))
        self.assertTrue(any("cross_split_group:block" in e for e in errors))

    def test_same_vehicle_distant_time_fails(self):
        b = sample("b", "blind")
        b.update(context_start_s=2000, context_end_s=2000)
        b["vehicles"][0]["vehicle_session_id"] = "vehicle-a"
        self.assertTrue(any("cross_split_group:vehicle" in e for e in validate([sample(), b])))

    def test_existing_review_cannot_become_training(self):
        row = sample()
        row.update(source_set="existing_user_review_v2", evaluation_only=True)
        self.assertTrue(any("existing_review_set_stays_regression" in e for e in validate([row])))

    def test_redbox_and_teacher_only_fail(self):
        row = sample()
        row.update(image_kind="user_redbox_screenshot", label_source="teacher_only")
        errors = validate([row])
        self.assertTrue(any("annotated_or_generated_input_forbidden" in e for e in errors))
        self.assertTrue(any("unverified_pseudolabel_forbidden" in e for e in errors))

    def test_type_unknown_not_invented(self):
        row = sample()
        row["vehicles"][0]["type"] = "large"
        self.assertTrue(any("unverified_type" in e for e in validate([row])))

    def test_string_reviewers_not_two_independent_people(self):
        row = sample()
        row["reviewers"] = "two_people"
        self.assertTrue(any("two_independent_human_reviews_required" in e for e in validate([row])))

    def test_training_and_teacher_rights_required(self):
        row = sample()
        row.update(training_rights_confirmed=False, label_source="teacher_human_corrected")
        errors = validate([row])
        self.assertTrue(any("training_rights_unconfirmed" in e for e in errors))
        self.assertTrue(any("teacher_rights_unconfirmed" in e for e in errors))

    def test_blind_and_regression_not_exportable_even_directly(self):
        for split in ("blind", "regression"):
            with self.assertRaisesRegex(ValueError, "cannot_export_evaluation_split"):
                export_row(sample(split=split))

    def test_count_and_bbox_integrity(self):
        row = sample()
        row["count"] = 2
        row["vehicles"][0]["bbox_px"] = [100, 100, 50, 200]
        errors = validate([row])
        self.assertTrue(any("count_object_list_mismatch" in e for e in errors))
        self.assertTrue(any("invalid_bbox" in e for e in errors))

    def test_quantization_collapse_rejected(self):
        row = sample()
        row["vehicles"][0]["bbox_px"] = [1.01, 1, 1.02, 2]
        with self.assertRaisesRegex(ValueError, "bbox_quantization_collapse"):
            export_row(row)

    def test_export_has_only_image_in_prompt_and_grounding_in_answer(self):
        import json
        original = sample()
        before = copy.deepcopy(original)
        out = export_row(original)
        self.assertEqual(out["conversations"][0]["value"].count("<image>"), 1)
        self.assertNotIn("synthetic visible", out["conversations"][0]["value"])
        answer = json.loads(out["conversations"][1]["value"])
        self.assertEqual(answer["vehicles"][0]["bbox_2d"], [100, 200, 500, 800])
        self.assertEqual(answer["vehicles"][0]["type"], "unknown")
        self.assertNotIn("vehicle_session_id", answer["vehicles"][0])
        self.assertEqual(original, before)


if __name__ == "__main__":
    unittest.main()
