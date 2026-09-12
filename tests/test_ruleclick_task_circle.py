import unittest
from unittest.mock import patch

from module.atom.click import RuleClick


class RuleClickCircleTests(unittest.TestCase):
    def setUp(self):
        RuleClick.reset_task_points()

    def test_task_cache_and_reentry(self):
        roi = (10, 20, 100, 50)
        with patch('module.atom.click.np.random.randint', side_effect=[30, 40, 60, 50]) as pick:
            first = RuleClick(roi, roi, 'entry')
            first.coord()
            RuleClick(roi, roi, 'entry').coord_more()
            self.assertEqual(pick.call_count, 2)
            self.assertEqual(RuleClick._task_circles.get()[('entry', roi)], (30, 40, 80))
            RuleClick.reset_task_points()
            first.coord()
            self.assertEqual(pick.call_count, 4)
            self.assertEqual(RuleClick._task_circles.get()[('entry', roi)], (60, 50, 50))

    def test_samples_inside_circle_and_rectangle(self):
        for roi in ((10, 20, 100, 50), (0, 0, 1, 1), (0, 0, 300, 2)):
            rule = RuleClick(roi, roi, str(roi))
            points = [rule.coord() for _ in range(500)]
            cx, cy, radius = RuleClick._task_circles.get()[(str(roi), roi)]
            x, y, width, height = roi
            for px, py in points:
                self.assertTrue(x <= px < x + width and y <= py < y + height)
                self.assertLessEqual((px-cx)**2 + (py-cy)**2, radius**2)

    def test_rejects_outside_points_and_uses_equal_deviation(self):
        rule = RuleClick((0, 0, 100, 100), (0, 0, 100, 100), 'clip')
        with patch('module.atom.click.np.random.randint', side_effect=[50, 50]), \
                patch('module.atom.click.np.random.normal', side_effect=[99, 99, -1, 50, 51, 52]) as normal:
            self.assertEqual(rule.coord(), (51, 52))
            self.assertTrue(all(call.args[1] == 50 / 3 for call in normal.call_args_list))

    def test_invalid_region(self):
        with self.assertRaises(ValueError):
            RuleClick((0, 0, 0, 10), (0, 0, 1, 1)).coord()


if __name__ == '__main__':
    unittest.main()
