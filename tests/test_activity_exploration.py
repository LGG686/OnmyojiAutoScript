"""探索流程回归测试，不连接设备。用项目 toolkit Python 执行 unittest。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.exception import GameStuckError
from tasks.ActivityShikigami.activities.exploration import ExplorationAct
from tasks.ActivityShikigami.config import ActivityShikigami, GeneralConfig, ExplorationMode
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig


class ExplorationTests(unittest.TestCase):
    def test_encounter_returns_to_event_twice_then_main(self):
        task = ExplorationAct()
        task.I_EVENT_FIGHT = 'fight'
        task._wait_exp = Mock(return_value=True)
        task.appear = Mock(side_effect=[True, True, False])
        task.time_limit_reached = Mock(return_value=False)
        task._run_exp_event = Mock(return_value=True)
        self.assertTrue(task._finish_exp_encounter_entry())
        self.assertEqual(task._run_exp_event.call_count, 2)
        self.assertTrue(all(call.args == ('encounter',)
                            for call in task._run_exp_event.call_args_list))

    def test_encounter_third_battle_direct_main_needs_no_extra_battle(self):
        task = ExplorationAct()
        task.I_EVENT_FIGHT = 'fight'
        task._wait_exp = Mock(return_value=True)
        task.appear = Mock(return_value=False)
        task._run_exp_event = Mock()
        self.assertTrue(task._finish_exp_encounter_entry())
        task._run_exp_event.assert_not_called()

    def test_story_event_skip_confirm_reward_and_timeouts(self):
        for waits in ([True, True], [False], [True, False]):
            task = ExplorationAct()
            task.I_EVENT_REWARD, task.I_EVENT_FIGHT = 'chest', 'fight'
            task.I_EVENT_STORY, task.I_STORY_SKIP_ENSURE = 'story', 'confirm'
            task.I_EVENT_REWARD_REWARD = 'reward'
            task.screenshot = Mock()
            task.appear = lambda marker: marker == 'story'
            task._wait_exp = Mock(side_effect=waits)
            task._clear_exp_rewards = Mock()
            if all(waits):
                self.assertTrue(task._run_exp_event('main'))
                task._clear_exp_rewards.assert_called_once()
            else:
                with self.assertRaises(GameStuckError):
                    task._run_exp_event('main')
                task._clear_exp_rewards.assert_not_called()
            self.assertEqual([call.kwargs['click'] for call in task._wait_exp.call_args_list],
                             ['story', 'confirm'][:len(waits)])

    def test_story_marker_counts_as_successful_entry(self):
        task = ExplorationAct()
        task.I_EVENT_REWARD, task.I_EVENT_FIGHT, task.I_EVENT_STORY = 'chest', 'fight', 'story'
        task._find_exp_entry = Mock(return_value=SimpleNamespace(burst_count=1))
        task.click = Mock()
        task.appear = lambda marker: marker == 'story'
        task._wait_exp = Mock(side_effect=lambda predicate, timeout: predicate())
        self.assertTrue(task._enter_exp_entry('main', 'rule'))
        task.click.assert_called_once()

    @patch('tasks.ActivityShikigami.activities.exploration.time.sleep')
    def test_image_entries_topmost_and_no_repeated_rewind(self, sleep):
        task = ExplorationAct()
        task.device = SimpleNamespace(image='screen')
        task.screenshot = Mock()
        task.swipe = Mock()
        rule = SimpleNamespace(roi_back=(19, 85, 263, 323), name='main',
                               match_all=Mock(return_value=[(0.95, 24, 250, 58, 34),
                                                            (0.9, 23, 109, 58, 34)]))
        entry = task._find_exp_entry(rule)
        self.assertEqual(entry.roi_front, (19, 109, 263, 34))
        self.assertEqual(task.swipe.call_count, 1)
        self.assertEqual(sleep.call_count, 1)
        task._find_exp_entry(rule)
        self.assertEqual(task.swipe.call_count, 1)
        self.assertEqual(rule.match_all.call_count, 2)

    @patch('tasks.ActivityShikigami.activities.exploration.RuleOcr')
    @patch('tasks.ActivityShikigami.activities.exploration.time.sleep')
    def test_image_scan_bounded_and_detects_after_each_down_swipe(self, sleep, ocr):
        task = ExplorationAct()
        task.device = SimpleNamespace(image='screen')
        task.screenshot = Mock()
        task.swipe = Mock()
        task.time_limit_reached = Mock(return_value=False)
        ocr.return_value.detect_and_ocr.side_effect = [
            [SimpleNamespace(ocr_text=text)] for text in ('任务甲', '任务乙', '任务乙', '任务乙', '任务乙')]
        rule = SimpleNamespace(roi_back=(19, 85, 263, 323), name='branch',
                               match_all=Mock(return_value=[]))
        self.assertFalse(task._find_exp_entry(rule))
        self.assertEqual(task.swipe.call_count, 3)  # 上划一次，下划两次后识别不变
        self.assertEqual(rule.match_all.call_count, 3)
        self.assertTrue(all(call.args == (1,) for call in sleep.call_args_list))
        self.assertFalse(task._exp_list_needs_top)
        down = task.swipe.call_args_list[-1].args[0]
        self.assertEqual(down.roi_front[1] - down.roi_back[1], 120)
        task._find_exp_entry(rule)
        self.assertEqual(task.swipe.call_count, 4)  # 后续只有下划

    def test_entry_click_retries_and_completion(self):
        for mode in ('main', 'branch', 'encounter'):
            for results in ([True], [False]):
                with self.subTest(mode=mode, results=results):
                    task = ExplorationAct()
                    entry = SimpleNamespace(burst_count=3)
                    task._find_exp_entry = Mock(return_value=entry)
                    task.click = Mock()
                    task._wait_exp = Mock(side_effect=results)
                    if not any(results) and mode != 'main':
                        with self.assertRaises(GameStuckError):
                            task._enter_exp_entry(mode, 'rule')
                    else:
                        self.assertEqual(task._enter_exp_entry(mode, 'rule'), any(results))
                    self.assertEqual(task.click.call_count, len(results))
                    self.assertEqual(entry.burst_count, 1)
                    self.assertTrue(all(c.kwargs['timeout'] == 5
                                        for c in task._wait_exp.call_args_list))
                    task._find_exp_entry.assert_called_once_with('rule')

    def test_absent_entry_completes_without_clicking(self):
        for mode in ('main', 'branch', 'encounter'):
            task = ExplorationAct()
            task._find_exp_entry = Mock(return_value=False)
            task.click = Mock()
            self.assertFalse(task._enter_exp_entry(mode, 'rule'))
            task.click.assert_not_called()

    def test_oasx_form_serialization_and_mode_update(self):
        from module.config.config_model import ConfigModel

        config = ConfigModel()
        form = config.script_task('ActivityShikigami')
        fields = form['general_config'][:3]
        self.assertEqual([field['name'] for field in fields],
                         ['task_sequence', 'exploration_modes', 'throw_limit'])
        self.assertEqual(fields[0]['enumEnum'][0], '探索')
        self.assertEqual(fields[1]['type'], 'multi_enum')
        self.assertEqual(fields[1]['enumEnum'], ['主线', '遭遇战', '支线'])
        self.assertIn('exp_encounter_battle_conf', form)
        self.assertEqual(form['switch_soul_config'][0]['name'], 'enable_switch_exp_encounter')
        self.assertTrue(config.script_set_arg(
            'ActivityShikigami', 'general_config', 'exploration_modes', ['遭遇战']))
        updated = config.script_task('ActivityShikigami')
        self.assertEqual(updated['general_config'][1]['value'], ['遭遇战'])

    def test_keyword_maps_to_full_width_fixed_height(self):
        roi = ExplorationAct._exp_entry_roi(
            [(2, 30), (60, 30), (60, 50), (2, 50)], (19, 85, 263, 323), 31,
        )
        self.assertEqual(roi, (19, 110, 263, 31))
        for top in (0, 315):
            self.assertIsNone(ExplorationAct._exp_entry_roi(
                [(0, top), (60, top), (60, top + 8), (0, top + 8)],
                (19, 85, 263, 323), 31,
            ))

    def test_exploration_selected_without_count_limit(self):
        config = GeneralConfig(task_sequence='exploration')
        self.assertEqual(config.task_sequence_v, ['探索'])
        self.assertNotIn('探索', GeneralConfig().task_sequence_v)

    @patch('tasks.ActivityShikigami.activities.exploration.time.sleep')
    def test_modes_run_until_missing(self, _sleep):
        task = ExplorationAct()
        task.I_EXP_MAIN, task.I_EXP_BRANCH, task.I_EXP_ENCOUNTER = 'main', 'branch', 'encounter'
        task.conf = SimpleNamespace(general_config=GeneralConfig())
        task.goto_page = Mock()
        task.screenshot = Mock()
        task.time_limit_reached = Mock(return_value=False)
        task._clear_exp_rewards = Mock(return_value=False)
        task._wait_exp = Mock(return_value=True)
        task._enter_exp_entry = Mock(side_effect=[True, True, False, True, False,
                                                 True, True, True, True, False])
        # 主线完成后执行遭遇战，最后执行支线。
        task._run_exp_event = Mock(return_value=True)
        task._finish_exp_encounter_entry = Mock(return_value=True)
        task.run_exploration()
        self.assertEqual([c.args[0] for c in task._run_exp_event.call_args_list],
                         ['main', 'main', 'encounter', 'branch', 'branch', 'branch', 'branch'])

    def test_system_battle_only_clicks_ready(self):
        task = ExplorationAct()
        task.current_action_type = 'exp_main'
        task.I_PREPARE_HIGHLIGHT = 'ready'
        task.appear_then_click = Mock()
        task._handle_prepare(None, GeneralBattleConfig())
        task.appear_then_click.assert_called_once_with('ready', interval=0.8)

    @patch('tasks.ActivityShikigami.activities.exploration.settlement_random_click')
    def test_reward_click_is_single_and_disappearance_checked(self, factory):
        task = ExplorationAct()
        task.I_EVENT_REWARD_REWARD = SimpleNamespace(name='reward')
        task.I_SHIKIGAMI_HELP = SimpleNamespace(name='help')
        task.appear = Mock(return_value=True)
        task.click = Mock()
        task._wait_exp = Mock(return_value=True)
        click = SimpleNamespace(burst_count=3)
        factory.return_value = click
        self.assertTrue(task._clear_exp_rewards())
        self.assertEqual(click.burst_count, 1)
        task.click.assert_called_once_with(click, interval=0.8)
        task._wait_exp.assert_called_once()
        task._wait_exp.return_value = False
        with self.assertRaises(GameStuckError):
            task._clear_exp_rewards()

    def test_normal_event_does_not_configure_encounter_souls(self):
        task = ExplorationAct()
        task.I_EVENT_REWARD, task.I_EVENT_FIGHT = 'chest', 'fight'
        task.I_EVENT_FIGHT_FIGHT = 'start'
        task.screenshot = Mock()
        task.appear = lambda marker: marker == 'fight'
        task._wait_exp = Mock(return_value=True)
        task._prepare_exp_encounter = Mock()
        task.run_general_battle = Mock()
        self.assertTrue(task._run_exp_event('branch'))
        task._prepare_exp_encounter.assert_not_called()
        config = task.run_general_battle.call_args.args[0]
        self.assertFalse(config.preset_enable)
        self.assertFalse(config.lock_team_enable)


    def test_encounter_ignores_counter_and_exits_on_either_page(self):
        for completed in range(4):
            with self.subTest(completed=completed):
                task = ExplorationAct()
                task.I_EVENT_REWARD, task.I_EVENT_FIGHT = 'chest', 'fight'
                task.I_EVENT_FIGHT_FIGHT, task.I_EVENT_CLOSE = 'start', 'close'
                task.I_EXP_CHECK_EXPLORATION = 'main'
                task.I_SHIKIGAMI_HELP, task.I_EVENT_REWARD_REWARD = 'help', 'reward'
                task.screenshot = Mock()
                task.appear = lambda marker: marker == 'fight'
                task._read_exp_encounter_count = Mock(return_value=completed)
                task._wait_exp = Mock(return_value=True)
                task._prepare_exp_encounter = Mock()
                task.conf = SimpleNamespace(exp_encounter_battle_conf=GeneralBattleConfig())
                task.run_general_battle = Mock()
                self.assertTrue(task._run_exp_event('encounter'))
                task._read_exp_encounter_count.assert_not_called()
                task.run_general_battle.assert_called_once()
                task._prepare_exp_encounter.assert_called_once()
                if completed == 2:
                    # 第三次直接回主页即可退出战斗，不等待再次出现事件或3/3。
                    task.appear = lambda marker: marker == 'main'
                    matcher = task.run_general_battle.call_args.kwargs['exit_matcher']
                    self.assertTrue(matcher())
                    task.appear = lambda marker: marker == 'fight'
                    self.assertTrue(matcher())


    def test_oasx_order_modes_and_legacy_soul_migration(self):
        self.assertEqual(list(GeneralConfig.model_fields)[:3],
                         ['task_sequence', 'exploration_modes', 'throw_limit'])
        cfg = GeneralConfig(task_sequence=['大富翁', '探索'], throw_limit=1)
        self.assertEqual(cfg.task_sequence_v, ['探索', '大富翁'])
        cfg.exploration_modes = []
        self.assertEqual(cfg.task_sequence_v, ['大富翁'])
        migrated = ActivityShikigami(exp_encounter_soul_config={
            'enable': True, 'switch_group_team': '2,3', 'group_name': '组', 'team_name': '队'})
        self.assertTrue(migrated.switch_soul_config.enable_switch_exp_encounter)
        self.assertEqual(migrated.switch_soul_config.exp_encounter_group_team, '2,3')

    def test_selected_encounters_clear_all_and_ignore_legacy_limit(self):
        task = ExplorationAct()
        task.conf = SimpleNamespace(general_config=GeneralConfig(
            exploration_modes=[ExplorationMode.ENCOUNTER], exp_encounter_limit=2))
        task.I_EXP_MAIN, task.I_EXP_BRANCH, task.I_EXP_ENCOUNTER = 'main', 'branch', 'encounter'
        task.goto_page = Mock()
        task.screenshot = Mock()
        task.time_limit_reached = Mock(return_value=False)
        task._clear_exp_rewards = Mock(return_value=False)
        task._wait_exp = Mock(return_value=True)
        task._enter_exp_entry = Mock(side_effect=[True] * 7 + [False])
        task._run_exp_event = Mock(return_value=True)
        task._finish_exp_encounter_entry = Mock(return_value=True)
        task.run_exploration()
        self.assertEqual(task._run_exp_event.call_count, 7)
        self.assertNotIn('exp_encounter_limit', task.conf.general_config.model_dump())
        self.assertTrue(task.conf.general_config.activity_enabled('探索'))
        self.assertTrue(all(c.args[0] == 'encounter' for c in task._run_exp_event.call_args_list))


if __name__ == '__main__':
    unittest.main()
