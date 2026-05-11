import unittest
from unittest.mock import patch

from scripts import clean_synthesis, judge_synthesis


class SynthesisPostprocessCompatibilityTest(unittest.TestCase):
    def test_clean_deduplicates_current_final_question_field(self):
        results = [
            {"final_question": "同一个最终问题？", "hops": [], "hop_count": 2, "qa_type": "inference"},
            {"final_question": "同一个最终问题？后面略有变化", "hops": [], "hop_count": 2, "qa_type": "inference"},
        ]

        keep, removed = clean_synthesis.dedup_by_question(results, prefix_len=7)

        self.assertEqual(len(keep), 1)
        self.assertEqual(len(removed), 1)

    def test_clean_deduplicates_current_doc_chunk_id_field(self):
        results = [
            {"hops": [{"doc_chunk_id": "chunk_a"}, {"doc_chunk_id": "chunk_b"}]},
            {"hops": [{"doc_chunk_id": "chunk_a"}, {"doc_chunk_id": "chunk_b"}]},
        ]

        keep, removed = clean_synthesis.dedup_by_chunk_overlap(results)

        self.assertEqual(len(keep), 1)
        self.assertEqual(len(removed), 1)

    def test_judge_hop_chain_uses_current_doc_chunk_id_field(self):
        qa = {
            "hops": [
                {
                    "hop_idx": 1,
                    "question": "子问题？",
                    "answer": "子答案",
                    "doc_chunk_id": "manual_0001",
                    "title": "手册",
                }
            ]
        }
        corpus_lookup = {"manual_0001": {"text": "这是证据内容。", "title": "语料标题"}}

        hop_chain = judge_synthesis.build_hop_chain(qa, corpus_lookup)

        self.assertIn("chunk: manual_0001", hop_chain)
        self.assertIn("这是证据内容。", hop_chain)

    def test_judge_one_uses_current_final_question_and_answer_fields(self):
        qa = {
            "final_question": "最终问题？",
            "final_answer": "最终答案",
            "hops": [
                {
                    "hop_idx": 1,
                    "question": "子问题？",
                    "answer": "子答案",
                    "doc_chunk_id": "manual_0001",
                    "title": "手册",
                }
            ],
        }
        corpus_lookup = {"manual_0001": {"text": "这是证据内容。", "title": "语料标题"}}

        with patch.object(judge_synthesis, "llm_call", return_value='{"answer_correctness": 5, "multihop_necessity": 4, "question_clarity": 5}') as llm_call:
            scores = judge_synthesis.judge_one(qa, corpus_lookup, model="test-model", lang="zh")

        prompt = llm_call.call_args.args[0]
        self.assertIn("最终问题？", prompt)
        self.assertIn("最终答案", prompt)
        self.assertEqual(scores["total"], 14)


if __name__ == "__main__":
    unittest.main()
