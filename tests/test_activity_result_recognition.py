import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tasks.ActivityShikigami.base_act import BaseAct
from tasks.ActivityShikigami.assets import ActivityShikigamiAssets
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.GameUi.matcher import any_of


class ActivityResultRecognitionTests(unittest.TestCase):
    def test_exploration_event_excludes_red_close_without_changing_other_modes(self):
        result_page = SimpleNamespace(recognizer=any_of(lambda task: task.real_result))
        task = SimpleNamespace(
            C_SAFE_RANDOM_CLICK_AREA_ACT=Mock(),
            navigator=SimpleNamespace(resolve_page=lambda page: result_page),
            I_UI_BACK_RED=GlobalGameAssets.I_UI_BACK_RED,
            I_EVENT_FIGHT=ActivityShikigamiAssets.I_EVENT_FIGHT,
            current_action_type='exp_encounter', real_result=False,
            appear=Mock(return_value=True),
        )
        with patch('tasks.ActivityShikigami.base_act.pages.page_battle_result', result_page):
            BaseAct.before_run(task)
            self.assertFalse(result_page.recognizer.evaluate(task))
            task.current_action_type = 'ap'
            self.assertTrue(result_page.recognizer.evaluate(task))
            task.current_action_type = 'exp_encounter'
            task.appear = lambda rule: rule is task.I_UI_BACK_RED
            self.assertTrue(result_page.recognizer.evaluate(task))
            task.appear = Mock(return_value=False)
            task.real_result = True
            self.assertTrue(result_page.recognizer.evaluate(task))


if __name__ == '__main__':
    unittest.main()
