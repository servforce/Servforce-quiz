import unittest


class TestCandidateQueryWhereClause(unittest.TestCase):
    def test_numeric_query_matches_phone_prefix_and_id(self):
        from db import _candidate_query_where_clause

        sql, params = _candidate_query_where_clause("13")
        self.assertIn("phone LIKE", sql)
        self.assertIn("id = %s", sql)
        self.assertEqual(params, ["13%", 13])

    def test_numeric_short_query_matches_many_phones(self):
        from db import _candidate_query_where_clause

        sql, params = _candidate_query_where_clause("1")
        self.assertIn("phone LIKE", sql)
        self.assertEqual(params, ["1%", 1])

    def test_id_prefix_forms(self):
        from db import _candidate_query_where_clause

        sql1, params1 = _candidate_query_where_clause("#3")
        sql2, params2 = _candidate_query_where_clause("id:3")
        self.assertEqual(params1, ["3%", 3])
        self.assertEqual(params2, ["3%", 3])
        self.assertIn("phone LIKE", sql1)
        self.assertIn("phone LIKE", sql2)

    def test_text_query_fuzzy_matches_name_or_phone(self):
        from db import _candidate_query_where_clause

        sql, params = _candidate_query_where_clause("王征")
        self.assertIn("name ILIKE", sql)
        self.assertIn("phone LIKE", sql)
        self.assertEqual(params, ["%王征%", "%王征%"])

