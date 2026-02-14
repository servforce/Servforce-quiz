import unittest


from services.assignment_service import compute_min_submit_seconds


class TestMinSubmitSeconds(unittest.TestCase):
    def test_default_is_ceil_half(self):
        self.assertEqual(compute_min_submit_seconds(7200), 3600)
        self.assertEqual(compute_min_submit_seconds(7201), 3601)
        self.assertEqual(compute_min_submit_seconds(1), 1)

    def test_non_positive_limits_disable(self):
        self.assertEqual(compute_min_submit_seconds(0), 0)
        self.assertEqual(compute_min_submit_seconds(-10), 0)

    def test_given_value_is_bumped_to_half(self):
        self.assertEqual(compute_min_submit_seconds(100, 10), 50)
        self.assertEqual(compute_min_submit_seconds(100, 50), 50)
        self.assertEqual(compute_min_submit_seconds(100, 80), 80)
        self.assertEqual(compute_min_submit_seconds(100, 0), 0)


if __name__ == "__main__":
    unittest.main()
