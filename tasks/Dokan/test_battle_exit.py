import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tasks.Component.GeneralBattle.general_battle import BattleAction, GeneralBattle
from tasks.Dokan.config import DokanBattleConfig
from tasks.Dokan.script_task import ScriptTask


class DokanBattleExitTests(unittest.TestCase):
    def setUp(self):
        self.task = ScriptTask.__new__(ScriptTask)
        self.config = DokanBattleConfig()
        self.context = SimpleNamespace(is_win=False, last_page=None, reward_no_battle_ts=None)
        self.matcher = object()

    def test_return_after_quick_exit_ends_continuous_battle_without_settlement(self):
        self.assertTrue(self.config.continuous_battle)
        self.context.last_page = None
        with patch.object(self.task, '_evaluate_exit_matcher', return_value=True):
            action = self.task._handle_missing_battle_page(self.context, self.config, self.matcher)
        self.assertEqual(action, BattleAction.EXIT_LOSE)

    def test_return_preserves_known_win(self):
        self.context.is_win = True
        with patch.object(self.task, '_evaluate_exit_matcher', return_value=True):
            action = self.task._handle_missing_battle_page(self.context, self.config, self.matcher)
        self.assertEqual(action, BattleAction.EXIT_WIN)

    def test_transition_without_dokan_marker_keeps_original_battle_handler(self):
        with patch.object(self.task, '_evaluate_exit_matcher', return_value=False), \
                patch.object(GeneralBattle, '_handle_missing_battle_page', return_value=BattleAction.CONTINUE) as original:
            action = self.task._handle_missing_battle_page(self.context, self.config, self.matcher)
        self.assertEqual(action, BattleAction.CONTINUE)
        original.assert_called_once_with(self.context, self.config, self.matcher)


if __name__ == '__main__':
    unittest.main()
