from __future__ import annotations

import unittest

from scripts.build_blind_review_packet_v2 import build_packet


class BlindReviewPacketTests(unittest.TestCase):
    def test_packet_excludes_condition_and_auxiliary_evaluator_data(self) -> None:
        source = [
            {
                "review_item_id": "source-1",
                "eval_id": "eval-1",
                "axis_id": "calm-agitated",
                "target_pole": "calm",
                "contrast_pole": "agitated",
                "user_prompt": "Prompt",
                "heuristic_scores": {"base": 1},
                "external_judge": {"winner": "base"},
                "ai_preannotation": {"winner": "base"},
                "outputs": {
                    "base": {"condition": "base", "text": "Output A", "metadata": {"model": "hidden"}},
                    "prompt": {"condition": "prompt-only", "text": "Output B", "metadata": {"model": "hidden"}},
                },
            }
        ]
        packet, condition_key = build_packet(source, seed=7, max_items=1)
        serialized_packet = str(packet)
        self.assertNotIn("base", serialized_packet)
        self.assertNotIn("prompt-only", serialized_packet)
        self.assertNotIn("heuristic", serialized_packet)
        self.assertNotIn("judge", serialized_packet.casefold())
        self.assertEqual(len(condition_key), 2)

    def test_packet_is_deterministic_for_seed(self) -> None:
        source = [
            {
                "review_item_id": "source-1",
                "eval_id": "eval-1",
                "axis_id": "calm-agitated",
                "target_pole": "calm",
                "contrast_pole": "agitated",
                "user_prompt": "Prompt",
                "outputs": {
                    "a": {"condition": "a", "text": "A"},
                    "b": {"condition": "b", "text": "B"},
                },
            }
        ]
        self.assertEqual(build_packet(source, 11, 1), build_packet(source, 11, 1))

    def test_retest_uses_new_blind_ids_but_same_canonical_outputs(self) -> None:
        source = [
            {
                "review_item_id": "source-1",
                "eval_id": "eval-1",
                "axis_id": "calm-agitated",
                "target_pole": "calm",
                "contrast_pole": "agitated",
                "user_prompt": "Prompt",
                "outputs": {"a": {"text": "A"}, "b": {"text": "B"}},
            }
        ]
        round_1, key_1 = build_packet(source, 11, 1, review_round=1)
        round_2, key_2 = build_packet(source, 12, 1, review_round=2)
        self.assertNotEqual(
            {item["blind_output_id"] for item in round_1[0]["blind_outputs"]},
            {item["blind_output_id"] for item in round_2[0]["blind_outputs"]},
        )
        self.assertEqual(
            {item["canonical_output_id"] for item in key_1},
            {item["canonical_output_id"] for item in key_2},
        )

    def test_packet_excludes_missing_output_text(self) -> None:
        source = [
            {
                "review_item_id": "source-1",
                "eval_id": "eval-1",
                "axis_id": "calm-agitated",
                "target_pole": "calm",
                "contrast_pole": "agitated",
                "user_prompt": "Prompt",
                "outputs": {"a": {"text": "A"}, "b": {"text": "B"}, "missing": {"text": None}},
            }
        ]
        packet, key = build_packet(source, 11, 1)
        self.assertEqual(len(packet[0]["blind_outputs"]), 2)
        self.assertEqual(len(key), 2)


if __name__ == "__main__":
    unittest.main()
