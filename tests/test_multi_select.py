import unittest
from unittest.mock import patch

from module.config.config_model import ConfigModel
from tasks.ActivityShikigami.config import GeneralConfig


class MultiSelectTests(unittest.TestCase):
    def test_single_multiple_and_legacy_values(self):
        for value in ('探索', ['探索'], '["探索"]', '"探索"', ['["探索"]']):
            self.assertEqual(GeneralConfig(task_sequence=value).task_sequence, ['探索'])
        for value in (['探索', '爬塔'], '["探索","爬塔"]', '探索，爬塔'):
            self.assertEqual(GeneralConfig(task_sequence=value).task_sequence, ['探索', '爬塔'])
        for value in ('主线', ['主线'], '["主线"]'):
            self.assertEqual(GeneralConfig(exploration_modes=value).exploration_modes, ['主线'])
        self.assertEqual(GeneralConfig(task_sequence='[]').task_sequence, [])
        self.assertEqual(GeneralConfig(exploration_modes='[]').exploration_modes, [])

    def test_broken_saved_config_can_open_form(self):
        config = ConfigModel(activity_shikigami={'general_config': {
            'task_sequence': '["探索","爬塔"]', 'exploration_modes': '["主线"]'}})
        form = config.script_task('ActivityShikigami')
        self.assertEqual(form['general_config'][0]['value'], ['探索', '爬塔'])
        self.assertEqual(form['general_config'][1]['value'], ['主线'])

    def test_save_normalizes_and_rejects_invalid_option(self):
        config = ConfigModel()
        with patch.object(ConfigModel, 'save') as save:
            self.assertTrue(config.script_set_arg('ActivityShikigami', 'general_config',
                                                 'task_sequence', '["探索"]'))
            self.assertEqual(config.activity_shikigami.general_config.task_sequence, ['探索'])
            self.assertFalse(config.script_set_arg('ActivityShikigami', 'general_config',
                                                  'task_sequence', '["不存在"]'))
            self.assertEqual(config.activity_shikigami.general_config.task_sequence, ['探索'])
            self.assertEqual(save.call_count, 1)


if __name__ == '__main__':
    unittest.main()
