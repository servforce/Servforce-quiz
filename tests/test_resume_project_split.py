import unittest


class TestResumeProjectSplit(unittest.TestCase):
    def test_split_glued_project_outcome_into_previous_body(self):
        from services.resume_service import split_projects_raw_into_blocks

        raw = (
            "项目经历\n"
            "无表面法向量约束的部分重叠点云配准方法 2024年11月 - 2025年03月\n"
            "内容：对缺失法向量信息和遮挡导致的低质量点云数据，采用端到端的深度学习模型进行部分重叠点云的精确配准。\n"
            "工作：构建概率化重叠预测模型，得到不同帧点云数据的Mask掩码矩阵。\n"
            "项目成果：2025年6月在《计算机辅助设计与图形学学报》发表《无表面法向量约束的部分重叠点云配准方法》论文"
            "基于占用网络的场景三维重建方法 2025年04月 - 2025年08月\n"
            "内容：对缺失法向量信息的场景点云数据，构建隐式占用场，实现三维场景重建。\n"
        )
        blocks = split_projects_raw_into_blocks(raw)
        self.assertEqual(len(blocks), 2)
        self.assertIn("无表面法向量约束", blocks[0]["title"])
        self.assertIn("2024年11月", blocks[0]["period"])
        self.assertIn("项目成果", blocks[0]["body"])
        self.assertIn("发表", blocks[0]["body"])
        self.assertFalse(blocks[0]["body"].rstrip().endswith("\n论文"))
        self.assertEqual(blocks[1]["title"], "基于占用网络的场景三维重建方法")
        self.assertIn("2025年04月", blocks[1]["period"])
        self.assertNotIn("项目成果", blocks[1]["title"])

    def test_split_numeric_period_formats(self):
        from services.resume_service import split_projects_raw_into_blocks

        raw = (
            "项目经验\n"
            "Project A 2024.03 - 2024.06\n"
            "- did something\n"
            "Project B 2024-07 - 2024-09\n"
            "- did another thing\n"
        )
        blocks = split_projects_raw_into_blocks(raw)
        self.assertEqual([b["title"] for b in blocks], ["Project A", "Project B"])
        self.assertIn("2024.03", blocks[0]["period"])
        self.assertIn("2024-07", blocks[1]["period"])

    def test_split_period_with_present(self):
        from services.resume_service import split_projects_raw_into_blocks

        raw = (
            "项目经历\n"
            "项目X 2023年09月 - 至今\n"
            "职责：维护与优化\n"
        )
        blocks = split_projects_raw_into_blocks(raw)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["title"], "项目X")
        self.assertIn("至今", blocks[0]["period"])

    def test_split_drops_education_line_inside_body(self):
        from services.resume_service import split_projects_raw_into_blocks

        raw = (
            "工作经历\n"
            "北京华科城信息科技有限公司 实施顾问 2013.10-2015.07\n"
            "公安部高级警官学院 大专 2012-2014\n"
            "1. 负责XX\n"
        )
        blocks = split_projects_raw_into_blocks(raw)
        self.assertEqual(len(blocks), 1)
        self.assertNotIn("公安部高级警官学院", blocks[0]["body"])

    def test_split_work_block_into_project_items(self):
        from services.resume_service import split_projects_raw_into_blocks

        raw = (
            "工作经历\n"
            "某某公司 实施顾问 2013.10-2015.07\n"
            "一、系统搭建运营\n"
            "1. 负责A\n"
            "项目：山东工大投资有限公司用友财务系统\n"
            "负责：调研、方案、上线\n"
            "项目：武汉江丰华世集团下汇丰银联易贷咨询服务\n"
            "负责：实施与支持\n"
        )
        blocks = split_projects_raw_into_blocks(raw)
        self.assertGreaterEqual(len(blocks), 3)
        titles = [b["title"] for b in blocks]
        self.assertIn("某某公司 实施顾问", titles[0])
        self.assertIn("山东工大投资有限公司用友财务系统", titles)
        self.assertIn("武汉江丰华世集团下汇丰银联易贷咨询服务", titles)
