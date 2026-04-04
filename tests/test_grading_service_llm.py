import unittest


class TestGradingServiceLLM(unittest.TestCase):
    def test_objective_only_exam_generates_scored_final_analysis_and_remark(self):
        import backend.md_quiz.services.grading_service as gs

        def fake_call_llm_json(prompt: str, model=None):  # noqa: ARG001
            raise AssertionError("LLM json should not be called for objective-only exam")

        def fake_call_llm_text(prompt: str, model=None):  # noqa: ARG001
            self.assertIn("【可计分题得分】5/5", prompt)
            self.assertNotIn("及格线", prompt)
            self.assertNotIn("是否面试", prompt)
            return "总体表现稳定。基础知识准确，作答完成度较高。建议继续保持。"

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
                        "type": "single",
                        "points": 5,
                        "stem_md": "1+1=?",
                        "options": [
                            {"key": "A", "text": "2", "correct": True},
                            {"key": "B", "text": "3", "correct": False},
                        ],
                    }
                ],
            }
            assignment = {"answers": {"Q1": "A"}}
            grading = gs.grade_attempt(spec, assignment)
            self.assertEqual(grading["result_mode"], "scored")
            self.assertEqual(grading["raw_scored"], 5)
            self.assertEqual(grading["total"], 5)
            self.assertEqual(grading["total_max"], 5)
            self.assertEqual(grading["analysis"], grading["final_analysis"])
            self.assertIn("总体表现稳定", grading["final_analysis"])
            self.assertEqual(grading["overall_reason"], "score=5/5")

            remark = gs.generate_candidate_remark(spec, assignment, grading)
            self.assertEqual(remark, "总体表现稳定。基础知识准确，作答完成度较高。")
        finally:
            gs.call_llm_json = orig_json
            gs.call_llm_text = orig_text

    def test_traits_only_exam_aggregates_traits_and_generates_analysis_and_remark(self):
        import backend.md_quiz.services.grading_service as gs

        def fake_call_llm_json(prompt: str, model=None):  # noqa: ARG001
            raise AssertionError("LLM json should not be called for traits-only exam")

        def fake_call_llm_text(prompt: str, model=None):  # noqa: ARG001
            self.assertIn("【Traits 摘要】", prompt)
            self.assertIn("I/E：winner=I", prompt)
            self.assertIn("固定落位 I", prompt)
            return "结果显示你更偏向 I，表达前更习惯先整理思路。整体偏好清晰，但仍保留一定情境弹性。"

        orig_json = gs.call_llm_json
        orig_text = gs.call_llm_text
        gs.call_llm_json = fake_call_llm_json
        gs.call_llm_text = fake_call_llm_text
        try:
            spec = {
                "title": "traits-demo",
                "trait": {
                    "dimensions": ["I", "E"],
                    "dimension_meanings": {"I": "独处内化", "E": "外向互动"},
                    "analysis_guidance": {
                        "paired_dimensions": ["I/E：比较独处内化与外向互动"],
                        "scoring_method": ["若同组平分，则依次比较 +2 次数、+1 次数；若仍平分，固定落位 I。"],
                        "interpretation": ["差值越大，偏好越稳定。"],
                    },
                },
                "questions": [
                    {
                        "qid": "Q1",
                        "type": "single",
                        "points": 0,
                        "max_points": 0,
                        "stem_md": "更偏向哪种工作方式？",
                        "options": [
                            {"key": "A", "text": "更内化", "traits": {"I": 2}},
                            {"key": "B", "text": "更外放", "traits": {"E": 2}},
                        ],
                    }
                ],
            }
            assignment = {"answers": {"Q1": "A"}}
            grading = gs.grade_attempt(spec, assignment)
            self.assertEqual(grading["result_mode"], "traits")
            self.assertEqual(grading["raw_total"], 0)
            self.assertEqual(grading["total"], 0)
            self.assertEqual(grading["total_max"], 0)
            self.assertEqual(grading["overall_reason"], "")
            self.assertEqual(grading["analysis"], grading["final_analysis"])
            self.assertEqual(grading["traits"]["primary_dimensions"], ["I"])
            self.assertEqual(grading["traits"]["paired_dimensions"][0]["winner"], "I")
            self.assertEqual(grading["traits"]["paired_dimensions"][0]["tie_break"], "score")
            self.assertNotIn("pass_threshold", grading)
            self.assertNotIn("interview", grading)

            remark = gs.generate_candidate_remark(spec, assignment, grading)
            self.assertEqual(remark, "结果显示你更偏向 I，表达前更习惯先整理思路。整体偏好清晰，但仍保留一定情境弹性。")
        finally:
            gs.call_llm_json = orig_json
            gs.call_llm_text = orig_text

    def test_short_answer_scored_and_analyzed(self):
        import backend.md_quiz.services.grading_service as gs

        def fake_call_llm_json(prompt: str, model=None):  # noqa: ARG001
            self.assertIn("【评分标准】", prompt)
            self.assertIn("完全无关", prompt)
            self.assertIn("部分分", prompt)
            return '{"score": 3, "reason": "命中2个要点，少1个要点"}'

        def fake_call_llm_text(prompt: str, model=None):  # noqa: ARG001
            return "总体：表现中等。要点：1) 基础尚可 2) 细节不足 3) 表达一般。总体建议：补问关键点。"

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
            assignment = {"answers": {"Q1": "训练好测试差"}}
            grading = gs.grade_attempt(spec, assignment)
            self.assertEqual(grading["raw_total"], 5)
            self.assertEqual(grading["raw_scored"], 3)
            self.assertEqual(grading["total"], 3)
            self.assertEqual(grading["total_max"], 5)
            self.assertTrue(isinstance(grading.get("analysis"), str))
            self.assertIn("总体建议", grading.get("analysis") or "")
            self.assertNotIn("/100", grading.get("analysis") or "")

            remark = gs.generate_candidate_remark(spec, assignment, grading)
            self.assertNotIn("面试建议", remark)
        finally:
            gs.call_llm_json = orig_json
            gs.call_llm_text = orig_text

    def test_mixed_exam_combines_scored_and_traits_in_final_analysis(self):
        import backend.md_quiz.services.grading_service as gs

        def fake_call_llm_json(prompt: str, model=None):  # noqa: ARG001
            return '{"score": 3, "reason": "命中2个要点，少1个要点"}'

        seen_prompts: list[str] = []

        def fake_call_llm_text(prompt: str, model=None):  # noqa: ARG001
            seen_prompts.append(prompt)
            self.assertIn("【可计分题摘要】", prompt)
            self.assertIn("【Traits 摘要】", prompt)
            self.assertIn("I/E：winner=I", prompt)
            return "可计分题基础尚可，但细节覆盖不完整。traits 结果偏向 I，说明更习惯先整理再表达。建议同时加强知识点完整性和外部沟通速度。"

        orig_json = gs.call_llm_json
        orig_text = gs.call_llm_text
        gs.call_llm_json = fake_call_llm_json
        gs.call_llm_text = fake_call_llm_text
        try:
            spec = {
                "title": "demo",
                "trait": {
                    "dimensions": ["I", "E"],
                    "dimension_meanings": {"I": "独处内化", "E": "外向互动"},
                    "analysis_guidance": {
                        "paired_dimensions": ["I/E：比较独处内化与外向互动"],
                        "scoring_method": ["若同组平分，则依次比较 +2 次数、+1 次数；若仍平分，固定落位 I。"],
                    },
                },
                "questions": [
                    {
                        "qid": "Q1",
                        "type": "single",
                        "points": 5,
                        "stem_md": "客观题",
                        "options": [
                            {"key": "A", "text": "对", "correct": True},
                            {"key": "B", "text": "错", "correct": False},
                        ],
                    },
                    {
                        "qid": "Q2",
                        "type": "single",
                        "points": 0,
                        "max_points": 0,
                        "stem_md": "traits 题",
                        "options": [
                            {"key": "A", "text": "更内化", "traits": {"I": 2}},
                            {"key": "B", "text": "更外放", "traits": {"E": 2}},
                        ],
                    },
                ],
            }
            assignment = {"answers": {"Q1": "A", "Q2": "A"}}
            grading = gs.grade_attempt(spec, assignment)
            self.assertEqual(grading["result_mode"], "mixed")
            self.assertEqual(grading["total"], 5)
            self.assertEqual(grading["total_max"], 5)
            self.assertEqual(grading["traits"]["paired_dimensions"][0]["winner"], "I")
            self.assertEqual(len(seen_prompts), 1)
            self.assertNotIn("/100", grading["final_analysis"])
            self.assertNotIn("阈值", seen_prompts[0])
            self.assertNotIn("是否面试", seen_prompts[0])
        finally:
            gs.call_llm_json = orig_json
            gs.call_llm_text = orig_text

    def test_traits_tie_break_uses_plus2_then_plus1_then_default(self):
        import backend.md_quiz.services.grading_service as gs

        def fake_call_llm_json(prompt: str, model=None):  # noqa: ARG001
            raise AssertionError("traits aggregation should not call llm json")

        def fake_call_llm_text(prompt: str, model=None):  # noqa: ARG001
            return "traits 分析"

        spec = {
            "title": "traits-demo",
            "trait": {
                "dimensions": ["I", "E"],
                "analysis_guidance": {
                    "paired_dimensions": ["I/E：比较独处内化与外向互动"],
                    "scoring_method": ["若同组平分，则依次比较 +2 次数、+1 次数；若仍平分，固定落位 I。"],
                },
            },
            "questions": [
                {
                    "qid": "Q1",
                    "type": "single",
                    "points": 0,
                    "max_points": 0,
                    "stem_md": "Q1",
                    "options": [{"key": "A", "text": "I+1", "traits": {"I": 1}}, {"key": "B", "text": "E+1", "traits": {"E": 1}}],
                },
                {
                    "qid": "Q2",
                    "type": "single",
                    "points": 0,
                    "max_points": 0,
                    "stem_md": "Q2",
                    "options": [{"key": "A", "text": "I+3", "traits": {"I": 3}}, {"key": "B", "text": "E+3", "traits": {"E": 3}}],
                },
                {
                    "qid": "Q3",
                    "type": "single",
                    "points": 0,
                    "max_points": 0,
                    "stem_md": "Q3",
                    "options": [{"key": "A", "text": "I+1", "traits": {"I": 1}}, {"key": "B", "text": "E+2", "traits": {"E": 2}}],
                },
                {
                    "qid": "Q4",
                    "type": "single",
                    "points": 0,
                    "max_points": 0,
                    "stem_md": "Q4",
                    "options": [{"key": "A", "text": "I+1", "traits": {"I": 1}}, {"key": "B", "text": "E+1", "traits": {"E": 1}}],
                },
            ],
        }

        orig_json = gs.call_llm_json
        orig_text = gs.call_llm_text
        gs.call_llm_json = fake_call_llm_json
        gs.call_llm_text = fake_call_llm_text
        try:
            plus2_assignment = {"answers": {"Q1": "A", "Q3": "B", "Q4": "A"}}
            plus2_grading = gs.grade_attempt(spec, plus2_assignment)
            plus2_pair = plus2_grading["traits"]["paired_dimensions"][0]
            self.assertEqual(plus2_pair["left_score"], 2)
            self.assertEqual(plus2_pair["right_score"], 2)
            self.assertEqual(plus2_pair["winner"], "E")
            self.assertEqual(plus2_pair["tie_break"], "plus2")

            plus1_assignment = {"answers": {"Q2": "A", "Q4": "B", "Q1": "", "Q3": ""}}
            plus1_grading = gs.grade_attempt(spec, plus1_assignment)
            plus1_pair = plus1_grading["traits"]["paired_dimensions"][0]
            self.assertEqual(plus1_pair["left_score"], 3)
            self.assertEqual(plus1_pair["right_score"], 1)
            self.assertEqual(plus1_pair["winner"], "I")
            self.assertEqual(plus1_pair["tie_break"], "score")

            plus1_only_spec = {
                "title": "traits-demo-plus1",
                "trait": spec["trait"],
                "questions": [
                    {
                        "qid": "Q1",
                        "type": "single",
                        "points": 0,
                        "max_points": 0,
                        "stem_md": "Q1",
                        "options": [{"key": "A", "text": "I+3", "traits": {"I": 3}}, {"key": "B", "text": "E+3", "traits": {"E": 3}}],
                    },
                    {
                        "qid": "Q2",
                        "type": "single",
                        "points": 0,
                        "max_points": 0,
                        "stem_md": "Q2",
                        "options": [{"key": "A", "text": "I+0", "traits": {}}, {"key": "B", "text": "E+1", "traits": {"E": 1}}],
                    },
                    {
                        "qid": "Q3",
                        "type": "single",
                        "points": 0,
                        "max_points": 0,
                        "stem_md": "Q3",
                        "options": [{"key": "A", "text": "I+0", "traits": {}}, {"key": "B", "text": "E+1", "traits": {"E": 1}}],
                    },
                    {
                        "qid": "Q4",
                        "type": "single",
                        "points": 0,
                        "max_points": 0,
                        "stem_md": "Q4",
                        "options": [{"key": "A", "text": "I+0", "traits": {}}, {"key": "B", "text": "E+1", "traits": {"E": 1}}],
                    },
                ],
            }
            plus1_only_assignment = {"answers": {"Q1": "A", "Q2": "B", "Q3": "B", "Q4": "B"}}
            plus1_only_grading = gs.grade_attempt(plus1_only_spec, plus1_only_assignment)
            plus1_only_pair = plus1_only_grading["traits"]["paired_dimensions"][0]
            self.assertEqual(plus1_only_pair["left_score"], 3)
            self.assertEqual(plus1_only_pair["right_score"], 3)
            self.assertEqual(plus1_only_pair["winner"], "E")
            self.assertEqual(plus1_only_pair["tie_break"], "plus1")

            default_assignment = {"answers": {}}
            default_grading = gs.grade_attempt(spec, default_assignment)
            default_pair = default_grading["traits"]["paired_dimensions"][0]
            self.assertEqual(default_pair["left_score"], 0)
            self.assertEqual(default_pair["right_score"], 0)
            self.assertEqual(default_pair["winner"], "I")
            self.assertEqual(default_pair["tie_break"], "default")
        finally:
            gs.call_llm_json = orig_json
            gs.call_llm_text = orig_text

    def test_empty_short_answer_gets_zero_without_llm_call(self):
        import backend.md_quiz.services.grading_service as gs

        def fake_call_llm_json(prompt: str, model=None):  # noqa: ARG001
            raise AssertionError("LLM should not be called for empty short answer")

        orig_json = gs.call_llm_json
        gs.call_llm_json = fake_call_llm_json
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
            assignment = {"answers": {"Q1": "   \n"}}
            grading = gs.grade_attempt(spec, assignment)
            self.assertEqual(grading["raw_scored"], 0)
            self.assertEqual(grading["subjective"][0]["score"], 0)
            self.assertIn("无意义", grading["subjective"][0]["reason"])
        finally:
            gs.call_llm_json = orig_json

    def test_numeric_only_short_answer_gets_zero_without_llm_call(self):
        import backend.md_quiz.services.grading_service as gs

        def fake_call_llm_json(prompt: str, model=None):  # noqa: ARG001
            raise AssertionError("LLM should not be called for numeric-only short answer")

        orig_json = gs.call_llm_json
        gs.call_llm_json = fake_call_llm_json
        try:
            spec = {
                "title": "demo",
                "questions": [
                    {
                        "qid": "Q1",
                        "type": "short",
                        "max_points": 5,
                        "stem_md": "用不超过150字解释过拟合的定义与危害。",
                        "rubric": "定义+表现+危害",
                    }
                ],
            }
            assignment = {"answers": {"Q1": "1414141123123123"}}
            grading = gs.grade_attempt(spec, assignment)
            self.assertEqual(grading["raw_scored"], 0)
            self.assertEqual(grading["subjective"][0]["score"], 0)
            self.assertIn("无意义", grading["subjective"][0]["reason"])
        finally:
            gs.call_llm_json = orig_json

    def test_contradiction_flag_forces_zero(self):
        import backend.md_quiz.services.grading_service as gs

        def fake_call_llm_json(prompt: str, model=None):  # noqa: ARG001
            return '{"score": 3, "reason": "关键结论说反了", "relevance": 2, "contradiction": true}'

        orig_json = gs.call_llm_json
        gs.call_llm_json = fake_call_llm_json
        try:
            spec = {
                "title": "demo",
                "questions": [
                    {
                        "qid": "Q1",
                        "type": "short",
                        "max_points": 10,
                        "stem_md": "用不超过150字解释过拟合的定义与危害。",
                        "rubric": "定义+表现+危害",
                    }
                ],
            }
            assignment = {"answers": {"Q1": "过拟合是训练损失过大，测试损失过低"}}
            grading = gs.grade_attempt(spec, assignment)
            self.assertEqual(grading["raw_scored"], 0)
            self.assertEqual(grading["subjective"][0]["score"], 0)
            self.assertIn("0", grading["subjective"][0]["reason"])
        finally:
            gs.call_llm_json = orig_json

    def test_relevance_zero_forces_zero(self):
        import backend.md_quiz.services.grading_service as gs

        def fake_call_llm_json(prompt: str, model=None):  # noqa: ARG001
            return '{"score": 4, "reason": "与题目无关", "relevance": 0, "contradiction": false}'

        orig_json = gs.call_llm_json
        gs.call_llm_json = fake_call_llm_json
        try:
            spec = {
                "title": "demo",
                "questions": [
                    {
                        "qid": "Q1",
                        "type": "short",
                        "max_points": 10,
                        "stem_md": "简答题",
                        "rubric": "评分标准",
                    }
                ],
            }
            assignment = {"answers": {"Q1": "随便写点无关的"}}
            grading = gs.grade_attempt(spec, assignment)
            self.assertEqual(grading["raw_scored"], 0)
            self.assertEqual(grading["subjective"][0]["score"], 0)
        finally:
            gs.call_llm_json = orig_json

    def test_contradiction_string_false_does_not_force_zero(self):
        import backend.md_quiz.services.grading_service as gs

        def fake_call_llm_json(prompt: str, model=None):  # noqa: ARG001
            # Some LLM gateways may serialize booleans as strings ("true"/"false").
            return '{"score": 6, "reason": "命中主要要点，少量细节缺失", "relevance": 2, "contradiction": "false"}'

        orig_json = gs.call_llm_json
        gs.call_llm_json = fake_call_llm_json
        try:
            spec = {
                "title": "demo",
                "questions": [
                    {
                        "qid": "Q1",
                        "type": "short",
                        "max_points": 10,
                        "stem_md": "用不超过150字解释过拟合的定义与危害。",
                        "rubric": "定义+表现+危害",
                    }
                ],
            }
            assignment = {"answers": {"Q1": "训练集拟合很好，测试集表现差，泛化能力不足。"}}
            grading = gs.grade_attempt(spec, assignment)
            self.assertEqual(grading["raw_scored"], 6)
            self.assertEqual(grading["subjective"][0]["score"], 6)
        finally:
            gs.call_llm_json = orig_json

    def test_contradiction_string_true_forces_zero(self):
        import backend.md_quiz.services.grading_service as gs

        def fake_call_llm_json(prompt: str, model=None):  # noqa: ARG001
            return '{"score": 8, "reason": "关键结论说反了", "relevance": 2, "contradiction": "true"}'

        orig_json = gs.call_llm_json
        gs.call_llm_json = fake_call_llm_json
        try:
            spec = {
                "title": "demo",
                "questions": [
                    {
                        "qid": "Q1",
                        "type": "short",
                        "max_points": 10,
                        "stem_md": "用不超过150字解释过拟合的定义与危害。",
                        "rubric": "定义+表现+危害",
                    }
                ],
            }
            assignment = {"answers": {"Q1": "过拟合是训练损失过大，测试损失过低"}}
            grading = gs.grade_attempt(spec, assignment)
            self.assertEqual(grading["raw_scored"], 0)
            self.assertEqual(grading["subjective"][0]["score"], 0)
        finally:
            gs.call_llm_json = orig_json

    def test_integer_only_score_triggers_reason_generation(self):
        import backend.md_quiz.services.grading_service as gs

        calls = {"reason": 0}

        def fake_call_llm_json(prompt: str, model=None):  # noqa: ARG001
            return "4"

        def fake_call_llm_text(prompt: str, model=None):  # noqa: ARG001
            if "解释该答案的得分依据" in prompt:
                calls["reason"] += 1
                return "命中主要要点，但缺少举例。"
            return "整体表现良好。关键点覆盖较完整，但例子不足。建议继续补充案例。"

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
            assignment = {"answers": {"Q1": "回答"}}
            grading = gs.grade_attempt(spec, assignment)
            self.assertEqual(grading["raw_scored"], 4)
            self.assertEqual(grading["overall_reason"], "score=4/5")
            self.assertEqual(calls["reason"], 1)
            self.assertEqual(grading["subjective"][0]["reason"], "命中主要要点，但缺少举例。")
        finally:
            gs.call_llm_json = orig_json
            gs.call_llm_text = orig_text

    def test_multiple_short_answers_within_threshold_use_single_batch_json_call(self):
        import backend.md_quiz.services.grading_service as gs

        calls = {"json": 0, "text": 0}

        def fake_call_llm_json(prompt: str, model=None):  # noqa: ARG001
            calls["json"] += 1
            self.assertIn("【待判简答题】", prompt)
            self.assertIn("### Q1", prompt)
            self.assertIn("### Q3", prompt)
            return json_text(
                {
                    "results": [
                        {"qid": "Q1", "score": 2, "reason": "命中两个要点", "relevance": 2, "contradiction": False},
                        {"qid": "Q2", "score": 3, "reason": "覆盖完整", "relevance": 3, "contradiction": False},
                        {"qid": "Q3", "score": 1, "reason": "仅部分相关", "relevance": 1, "contradiction": False},
                    ]
                }
            )

        def fake_call_llm_text(prompt: str, model=None):  # noqa: ARG001
            calls["text"] += 1
            return "综合分析。"

        def json_text(obj):
            import json

            return json.dumps(obj, ensure_ascii=False)

        orig_json = gs.call_llm_json
        orig_text = gs.call_llm_text
        gs.call_llm_json = fake_call_llm_json
        gs.call_llm_text = fake_call_llm_text
        try:
            spec = {
                "title": "batch-demo",
                "questions": [
                    {"qid": "Q1", "type": "short", "max_points": 5, "stem_md": "Q1", "rubric": "r1"},
                    {"qid": "Q2", "type": "short", "max_points": 5, "stem_md": "Q2", "rubric": "r2"},
                    {"qid": "Q3", "type": "short", "max_points": 5, "stem_md": "Q3", "rubric": "r3"},
                ],
            }
            assignment = {"answers": {"Q1": "a1", "Q2": "a2", "Q3": "a3"}}
            grading = gs.grade_attempt(spec, assignment)
            self.assertEqual(calls["json"], 1)
            self.assertEqual(calls["text"], 1)
            self.assertEqual(grading["raw_scored"], 6)
            self.assertEqual(grading["total_max"], 15)
            self.assertEqual([item["score"] for item in grading["subjective"]], [2, 3, 1])
        finally:
            gs.call_llm_json = orig_json
            gs.call_llm_text = orig_text

    def test_many_short_answers_are_chunked_by_five(self):
        import backend.md_quiz.services.grading_service as gs

        calls = {"json": 0}

        def fake_call_llm_json(prompt: str, model=None):  # noqa: ARG001
            calls["json"] += 1
            self.assertIn("【待判简答题】", prompt)
            qids = []
            for qid in ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]:
                if f"### {qid}" in prompt:
                    qids.append(qid)
            self.assertLessEqual(len(qids), 5)
            return json_text(
                {
                    "results": [
                        {"qid": qid, "score": 1, "reason": f"{qid} 命中要点", "relevance": 2, "contradiction": False}
                        for qid in qids
                    ]
                }
            )

        def fake_call_llm_text(prompt: str, model=None):  # noqa: ARG001
            return "综合分析。"

        def json_text(obj):
            import json

            return json.dumps(obj, ensure_ascii=False)

        orig_json = gs.call_llm_json
        orig_text = gs.call_llm_text
        gs.call_llm_json = fake_call_llm_json
        gs.call_llm_text = fake_call_llm_text
        try:
            spec = {
                "title": "batch-demo",
                "questions": [
                    {"qid": f"Q{idx}", "type": "short", "max_points": 2, "stem_md": f"Q{idx}", "rubric": f"r{idx}"}
                    for idx in range(1, 7)
                ],
            }
            assignment = {
                "answers": {f"Q{idx}": f"a{idx}" for idx in range(1, 7)}
            }
            grading = gs.grade_attempt(spec, assignment)
            self.assertEqual(calls["json"], 2)
            self.assertEqual(grading["raw_scored"], 6)
            self.assertEqual(grading["total_max"], 12)
            self.assertEqual(len(grading["subjective"]), 6)
        finally:
            gs.call_llm_json = orig_json
            gs.call_llm_text = orig_text


if __name__ == "__main__":
    unittest.main()
