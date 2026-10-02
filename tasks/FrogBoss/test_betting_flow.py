import unittest
from unittest.mock import patch

from module.exception import GameStuckError
from tasks.FrogBoss.script_task import ScriptTask


class FrameTimer:
    """Bound waits by simulated frames without sleeping or using a device."""

    def __init__(self, *_args):
        self.frames = 0

    def start(self):
        return self

    def reached(self):
        self.frames += 1
        return self.frames > 12


class BettingTask(ScriptTask):
    def __init__(self, frames):
        self.frames = iter(frames)
        self.visible = set()
        self.clicks = []

    def screenshot(self):
        self.visible = next(self.frames, self.visible)

    def appear(self, rule):
        return rule.name in self.visible

    def click(self, rule, interval=None):
        self.clicks.append(rule)
        return True

    def appear_then_click(self, rule, interval=None):
        if not self.appear(rule):
            return False
        return self.click(rule, interval=interval)


@patch('tasks.FrogBoss.script_task.Timer', FrameTimer)
class BettingFlowTests(unittest.TestCase):
    @patch('tasks.FrogBoss.script_task.sleep')
    def test_finish_requires_same_marker_in_second_frame(self, delay):
        for marker in (ScriptTask.I_BETTED, ScriptTask.I_FROG_BOSS_REST):
            for second_frame, expected in (({marker.name}, marker), (set(), None),
                                            ({ScriptTask.I_FROG_MALL.name, marker.name}, None)):
                with self.subTest(marker=marker.name, second_frame=second_frame):
                    task = BettingTask([second_frame])
                    task.visible = {marker.name}
                    self.assertEqual(task.confirmed_finish_marker(), expected)
                    delay.assert_called_with(0.2)

    def test_mall_has_priority_over_betting_and_resumes_after_close(self):
        panel = {ScriptTask.I_GOLD_30.name, ScriptTask.I_BET_SURE.name}
        mall = {ScriptTask.I_FROG_MALL.name, ScriptTask.I_FORG_MALL_CLOSE.name}
        task = BettingTask([
            panel | mall,
            panel,  # 关闭后立即刷新，禁止继续使用弹窗后方的旧画面。
            panel,
            panel,
            {ScriptTask.I_BETTED.name},
        ])
        task.confirm_bet()
        self.assertEqual([rule.name for rule in task.clicks], [
            ScriptTask.I_FORG_MALL_CLOSE.name,
            'FB_GOLD_30_SELECT',
            ScriptTask.I_BET_SURE.name,
        ])

    def test_mall_returning_to_bet_entries_hands_back_to_main_loop(self):
        entries = {ScriptTask.I_BET_LEFT.name, ScriptTask.I_BET_RIGHT.name}
        task = BettingTask([
            {ScriptTask.I_FROG_MALL.name, ScriptTask.I_FORG_MALL_CLOSE.name},
            entries,
            entries,
        ])
        task.confirm_bet()
        self.assertEqual([rule.name for rule in task.clicks], [ScriptTask.I_FORG_MALL_CLOSE.name])

    def test_reward_overlay_and_confirmation_hide_clickable_background(self):
        panel = {ScriptTask.I_GOLD_30.name, ScriptTask.I_BET_SURE.name}
        task = BettingTask([
            panel | {ScriptTask.I_GOLD_30_CHECK.name},
            panel,
            panel,
            panel | {ScriptTask.I_UI_CONFIRM.name},
            {ScriptTask.I_BETTED.name},
        ])
        task.confirm_bet()
        self.assertEqual([rule.name for rule in task.clicks], [
            ScriptTask.C_BET_REWARD_CLOSE.name,
            'FB_GOLD_30_SELECT',
            ScriptTask.I_BET_SURE.name,
            ScriptTask.I_UI_CONFIRM.name,
        ])
        self.assertEqual(task.clicks[0].coord(), (1075, 452))
        selection = task.clicks[1]
        x, y, width, height = ScriptTask.I_GOLD_30.roi_front
        sx, sy, sw, sh = selection.roi_front
        self.assertEqual(selection.profile, 'High')
        self.assertGreaterEqual(sx, x)
        self.assertLessEqual(sx + sw, x + width)
        self.assertGreaterEqual(sy, y)
        self.assertLess(sy + sh, y + height // 2)

    def test_cannot_submit_before_selecting_amount(self):
        task = BettingTask([{ScriptTask.I_BET_SURE.name}])
        with self.assertRaisesRegex(GameStuckError, 'gold_selected=False'):
            task.confirm_bet()
        self.assertEqual(task.clicks, [])

    def test_no_response_limits_submit_retries_without_reselecting_amount(self):
        panel = {ScriptTask.I_GOLD_30.name, ScriptTask.I_BET_SURE.name}
        task = BettingTask([panel])
        with self.assertRaisesRegex(GameStuckError, 'submit_attempts=3'):
            task.confirm_bet()
        self.assertEqual([rule.name for rule in task.clicks], [
            'FB_GOLD_30_SELECT',
            ScriptTask.I_BET_SURE.name,
            ScriptTask.I_BET_SURE.name,
            ScriptTask.I_BET_SURE.name,
        ])

    def test_already_betted_and_rest_end_without_clicking(self):
        for marker in (ScriptTask.I_BETTED, ScriptTask.I_FROG_BOSS_REST):
            with self.subTest(marker=marker.name):
                task = BettingTask([{marker.name}])
                task.confirm_bet()
                self.assertEqual(task.clicks, [])


if __name__ == '__main__':
    unittest.main()
