import unittest


class TestResumeExtractSection(unittest.TestCase):
    def test_stop_keyword_on_same_line(self):
        from services.resume_service import extract_resume_section

        text = (
            "基本信息 张三 13800138000 "
            "项目经历 Project A 2024.01-2024.02 负责XXX "
            "工作经历 Company B 2022.01-至今 做YYY "
            "教育经历 本科\n"
        )
        got = extract_resume_section(
            text,
            section_keywords=["项目经历", "项目经验"],
            stop_keywords=["工作经历", "教育经历"],
            max_chars=9999,
        )
        self.assertIn("项目经历", got)
        self.assertIn("Project A", got)
        self.assertNotIn("工作经历", got)
        self.assertNotIn("Company B", got)

