import unittest


class TestGradingServiceLLM(unittest.TestCase):
    def test_short_answer_scored_and_analyzed(self):
        import services.grading_service as gs

        def fake_call_llm_json(prompt: str, model=None):  # noqa: ARG001
            self.assertIn("【评分标准】", prompt)
            return '{"score": 3, "reason": "命中2个要点，少1个要点"}'

        def fake_call_llm_text(prompt: str, model=None):  # noqa: ARG001
            if "内部复盘" in prompt:
                return "总体：表现中等。要点：1) 基础尚可 2) 细节不足 3) 表达一般。面试建议：建议，补问关键点。"
            if "能力评价" in prompt:
                return "综合评价：基础尚可。优势：概念清楚。短板：细节不足。建议：加强例题训练。面试建议：建议，需追问细节。"
            return ""

        orig_json = gs.call_llm_json
        orig_text = gs.call_llm_text
        gs.call_llm_json = fake_call_llm_json
        gs.call_llm_text = fake_call_llm_text
        try:
            spec = {
                "title": "demo",
                "questions": [
                    {
                        "qid": "Q1",
                        "type": "short",
                        "max_points": 5,
                        "stem_md": "什么是过拟合？",
                        "rubric": "定义+表现+危害",
                    }
                ],
            }
            assignment = {"answers": {"Q1": "训练好测试差"}, "pass_threshold": 70}
            grading = gs.grade_attempt(spec, assignment)
            self.assertEqual(grading["raw_total"], 5)
            self.assertEqual(grading["raw_scored"], 3)
            self.assertTrue(isinstance(grading.get("analysis"), str))
            self.assertIn("面试建议", grading.get("analysis") or "")

            remark = gs.generate_candidate_remark(spec, assignment, grading)
            self.assertIn("面试建议", remark)
        finally:
            gs.call_llm_json = orig_json
            gs.call_llm_text = orig_text

    def test_integer_only_score_triggers_reason_generation(self):
        import services.grading_service as gs

        calls = {"reason": 0}

        def fake_call_llm_json(prompt: str, model=None):  # noqa: ARG001
            return "4"

        def fake_call_llm_text(prompt: str, model=None):  # noqa: ARG001
            if "解释该答案的得分依据" in prompt:
                calls["reason"] += 1
                return "命中主要要点，但缺少举例。"
            if "内部复盘" in prompt:
                return "总体：良好。要点：1) 关键点覆盖 2) 例子不足 3) 可继续提升。面试建议：建议，追问应用。"
            if "能力评价" in prompt:
                return "综合评价：良好。优势：要点覆盖。短板：例子不足。建议：补充案例。面试建议：建议，验证迁移。"
            return ""

        orig_json = gs.call_llm_json
        orig_text = gs.call_llm_text
        gs.call_llm_json = fake_call_llm_json
        gs.call_llm_text = fake_call_llm_text
        try:
            spec = {
                "title": "demo",
                "questions": [
                    {
                        "qid": "Q1",
                        "type": "short",
                        "max_points": 5,
                        "stem_md": "简答题",
                        "rubric": "评分标准",
                    }
                ],
            }
            assignment = {"answers": {"Q1": "回答"}, "pass_threshold": 70}
            grading = gs.grade_attempt(spec, assignment)
            self.assertEqual(grading["raw_scored"], 4)
            self.assertEqual(calls["reason"], 1)
            self.assertEqual(grading["subjective"][0]["reason"], "命中主要要点，但缺少举例。")
        finally:
            gs.call_llm_json = orig_json
            gs.call_llm_text = orig_text


if __name__ == "__main__":
    unittest.main()

