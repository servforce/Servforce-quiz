import unittest


class TestResumeFocus(unittest.TestCase):
    def test_focus_includes_tail_awards(self):
        from services.resume_service import focus_resume_text_for_details

        text = (
            "姓名：张三\n电话：13800138000\n\n"
            + ("无关内容\n" * 500)
            + "\n获奖情况\n全国大学生数学建模一等奖\n"
        )
        focused = focus_resume_text_for_details(text, head_chars=200, tail_chars=200, max_chars=8000)
        self.assertIn("姓名：张三", focused)
        self.assertIn("获奖情况", focused)
        self.assertIn("数学建模", focused)

    def test_focus_matches_english_headings(self):
        from services.resume_service import focus_resume_text_for_details

        text = (
            "John Doe\nEmail: a@b.com\n\n"
            "WORK EXPERIENCE\nAcme Inc. Software Engineer 2022-01 - 2024-06\n"
            "PROJECTS\nProject X 2023-02 - 2023-08\n"
        )
        focused = focus_resume_text_for_details(text, head_chars=80, tail_chars=80, max_chars=2000)
        self.assertIn("WORK EXPERIENCE", focused)
        self.assertIn("PROJECTS", focused)

