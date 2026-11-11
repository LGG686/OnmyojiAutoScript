"""Exploration marker recognition under observed map-layout shifts."""
import json
from pathlib import Path
import unittest

import numpy as np

from module.atom.image import RuleImage
from tasks.GameUi.assets import GameUiAssets


ROOT = Path(__file__).resolve().parents[3]


class ExplorationMarkerTests(unittest.TestCase):
    def rule(self):
        item = next(item for item in json.loads(
            (ROOT / 'tasks/GameUi/page/image_exploration.json').read_text(encoding='utf-8'))
                    if item['itemName'] == 'check_exploration')
        return RuleImage(tuple(map(int, item['roiFront'].split(','))),
                         tuple(map(int, item['roiBack'].split(','))),
                         item['method'], item['threshold'],
                         './tasks/GameUi/page/' + item['imageName'])

    def frame(self, rule, x=1152, y=148):
        frame = np.full((720, 1280, 3), 100, dtype=np.uint8)
        height, width = rule.image.shape[:2]
        frame[y:y + height, x:x + width] = rule.image
        return frame

    def test_detects_both_observed_horizontal_positions(self):
        for x in (1152, 1166):
            with self.subTest(x=x):
                rule = self.rule()
                self.assertTrue(rule.match(self.frame(rule, x=x)))
                self.assertEqual(rule.roi_front[:2], [x, 148])

    def test_old_search_box_reproduces_shifted_map_failure(self):
        rule = self.rule()
        rule.roi_back = (1150, 146, 25, 26)  # Original ROI plus global 2px padding.
        self.assertFalse(rule.match(self.frame(rule, x=1166)))

    def test_marker_elsewhere_does_not_classify_a_map(self):
        rule = self.rule()
        self.assertFalse(rule.match(self.frame(rule, x=900)))

    def test_blank_frame_does_not_classify_a_map(self):
        self.assertFalse(self.rule().match(np.full((720, 1280, 3), 100, dtype=np.uint8)))

    def test_generated_asset_keeps_the_source_search_box(self):
        source = self.rule()
        self.assertEqual(GameUiAssets.I_CHECK_EXPLORATION.roi_back, source.roi_back)
        self.assertEqual(GameUiAssets.I_CHECK_EXPLORATION.threshold, source.threshold)


if __name__ == '__main__':
    unittest.main()
