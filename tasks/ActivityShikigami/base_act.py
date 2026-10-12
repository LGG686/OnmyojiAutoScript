"""式神活动三种玩法共用运行能力。"""

import os
from datetime import datetime

import cv2
from cached_property import cached_property

from module.atom.image import RuleImage
from module.base.protect import random_sleep
from module.exception import TaskEnd
from module.logger import logger
from tasks.ActivityShikigami.assets import ActivityShikigamiAssets
from tasks.ActivityShikigami.config import ActivityShikigami, BATTLE_TYPES
from tasks.GameUi.default_pages import settlement_random_click
from tasks.Component.BaseActivity.base_activity import BaseActivity
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralBattle.general_battle import BattleAction, BattleContext, GeneralBattle
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.GameUi.game_ui import GameUi
import tasks.ActivityShikigami.page as pages


class ActivityResourceNotEnough(Exception):
    """当前子玩法资源不足，可以切换到下一项。"""


class BaseAct(GameUi, GeneralBattle, SwitchSoul, BaseActivity, ActivityShikigamiAssets):
    """统一保存计数、软时间边界、随机休息、御魂和战斗配置。"""

    # 挑战按钮 OCR 引导后的模板缓存位置（log 目录已被 .gitignore 忽略，不会入库）
    # 文件名必须带玩法：图像服务按模板路径缓存（默认 3600s），同名文件换玩法覆盖写不会生效
    FIRE_TPL_FILE = './log/as_fire_tpl/as_fire_tpl_{}.png'
    # 缓存模板相对识别框外扩的搜索余量
    FIRE_TPL_PAD = 20
    # 挑战按钮连续未命中多少轮后放弃，避免匹配不上时死循环
    MAX_FIRE_MISS = 3

    def __init__(self, config, device):
        super().__init__(config, device)
        self.action_count = {name: 0 for name in BATTLE_TYPES}
        climb_consumables = (
            'pass', 'ap_pass', 'boss', 'ap100', 'penta_pass'
        )
        self.climb_consumable_count = {
            name: -1 for name in climb_consumables
        }
        self.climb_pending_consumption = {
            name: 0 for name in climb_consumables
        }
        self.climb_ocr_correction_rounds = {
            name: 0 for name in climb_consumables
        }
        self.penta_pass_active = False
        self.pass_action_count = {'easy': 0, 'hard': 0}
        self.current_pass_mode = None
        self.switched_soul = {name: False for name in BATTLE_TYPES}
        self.current_action_type = ''
        self.activity_time_reached = False
        self._fire_tpl = None
        self._fire_tpl_key = None

    @cached_property
    def conf(self) -> ActivityShikigami:
        return self.config.model.activity_shikigami

    @property
    def scheduled_task_name(self) -> str:
        return 'ActivityShikigami'

    def before_run(self):
        self.C_SAFE_RANDOM_CLICK_AREA_ACT.reset_click_focuses()
        pages.page_battle_result = self.navigator.resolve_page(pages.page_battle_result)
        pages.page_battle_result.recognizer = pages.any_of(
            pages.all_of(
                lambda task: not task.current_action_type.startswith('exp_')
                or not task.appear(task.I_EVENT_FIGHT),
                self.I_UI_BACK_RED,
            ),
            pages.page_battle_result.recognizer,
        )

    def _fire_template(self, action_type: str):
        """返回爬塔挑战按钮规则。

        一轮爬塔要打几百次，每轮都走 OCR 开销太大；而按钮在运行中不会变，
        所以用 OCR 认一次「挑战」，把识别到的位置裁成模板缓存，之后都走模板匹配。
        换玩法（action_type）时会重新 OCR 引导一次，所以各玩法按钮外观不同也能各自适配。
        """
        if self._fire_tpl is not None and self._fire_tpl_key == action_type:
            return self._fire_tpl
        x, y, w, h = (int(v) for v in self.O_FIRE.ocr(self.device.image))
        if (x, y, w, h) == (0, 0, 0, 0):
            return None
        img_h, img_w = self.device.image.shape[:2]
        tpl_file = self.FIRE_TPL_FILE.format(action_type)
        os.makedirs(os.path.dirname(tpl_file), exist_ok=True)
        cv2.imwrite(
            tpl_file,
            cv2.cvtColor(self.device.image[y:y + h, x:x + w], cv2.COLOR_RGB2BGR),
        )
        pad = self.FIRE_TPL_PAD
        back_x, back_y = max(0, x - pad), max(0, y - pad)
        back_w, back_h = min(img_w - back_x, w + pad * 2), min(img_h - back_y, h + pad * 2)
        self._fire_tpl = RuleImage(
            roi_front=(x, y, w, h),
            roi_back=(back_x, back_y, back_w, back_h),
            threshold=0.8,
            method="Template matching",
            file=tpl_file,
            profile="High",
        )
        self._fire_tpl_key = action_type
        logger.info(f'Climb fire template cached from ocr: {action_type} {(x, y, w, h)}')
        return self._fire_tpl

    def _exit_matcher(self):
        if self.current_action_type == 'fakegod':
            return self.I_FG_ACT_FIRE
        if self.current_action_type in ('boss', 'ap', 'pass', 'ap100'):
            # 复用 OCR 引导出来的挑战按钮模板；没有缓存时交给 general_battle 的 2 秒兜底
            if self._fire_tpl is not None and self._fire_tpl_key == self.current_action_type:
                return self._fire_tpl
        return None

    def _handle_result(self, context: BattleContext, config: GeneralBattleConfig) -> BattleAction:
        if self.current_action_type == 'boss':
            self.appear_then_click(self.I_UI_BACK_RED, interval=1.5)
        return super()._handle_result(context, config)

    def battle_config(self, action_type: str) -> GeneralBattleConfig:
        return getattr(self.conf, f'{action_type}_battle_conf')

    def _battle_settlement_click(self):
        return settlement_random_click(self.C_SAFE_RANDOM_CLICK_AREA_ACT)

    def action_limit(self, action_type: str) -> int:
        return self.conf.general_config.limit_for(action_type)

    def time_limit_reached(self) -> bool:
        reached = datetime.now() - self.start_time >= self.conf.general_config.limit_time_v
        if reached and not self.activity_time_reached:
            logger.info('ActivityShikigami task time limit reached; stop before next action')
        self.activity_time_reached = self.activity_time_reached or reached
        return self.activity_time_reached

    def prepare_next_action(self, action_type: str) -> bool:
        """下一次骰子/战斗/行动的唯一软停止与随机休眠节点。"""
        limit = self.action_limit(action_type)
        if limit <= 0 or self.action_count[action_type] >= limit:
            logger.info(
                f'Activity action {action_type} count limit reached: '
                f'{self.action_count[action_type]}/{limit}'
            )
            return False
        if self.time_limit_reached():
            return False

        if self.conf.general_config.random_sleep:
            random_sleep(probability=0.2)
            if self.time_limit_reached():
                return False

        self.current_action_type = action_type
        return True

    def record_action(self, action_type: str):
        self.action_count[action_type] += 1
        logger.info(
            f'Activity action {action_type} count: '
            f'{self.action_count[action_type]}/{self.action_limit(action_type)}'
        )

    def switch_soul_for(
        self,
        action_type: str,
        enter_button: RuleImage,
        *,
        return_page=None,
        exit_records: bool = False,
    ):
        """按六种战斗字段切换一次御魂。"""
        if self.switched_soul[action_type]:
            return
        conf = self.conf.switch_soul_config
        enable_number = getattr(conf, f'enable_switch_{action_type}')
        enable_name = getattr(conf, f'enable_switch_{action_type}_by_name')
        self.switched_soul[action_type] = True
        if not enable_number and not enable_name:
            return

        conf.validate_switch_soul()
        logger.hr(f'Start switch soul: {action_type}', 2)
        self.ui_click(enter_button, stop=self.I_CHECK_RECORDS, interval=1)
        if enable_name:
            group, team = getattr(conf, f'{action_type}_group_team_name').split(',', 1)
            self.run_switch_soul_by_name(group.strip(), team.strip())
        elif enable_number:
            self.run_switch_soul(getattr(conf, f'{action_type}_group_team'))

        if exit_records:
            self.exit_shikigami_records()
        if return_page is not None:
            self.goto_page(return_page)

    def switch_soul_for_from_courtyard(self, action_type: str):
        """从庭院进入式神录，按原配置切换指定玩法的御魂预设。"""
        if self.switched_soul[action_type]:
            return
        conf = self.conf.switch_soul_config
        enable_number = getattr(conf, f'enable_switch_{action_type}')
        enable_name = getattr(conf, f'enable_switch_{action_type}_by_name')
        self.switched_soul[action_type] = True
        if not enable_number and not enable_name:
            return

        conf.validate_switch_soul()
        logger.hr(f'Start switch soul from courtyard: {action_type}', 2)
        self.goto_page(pages.page_main)
        self.goto_page(pages.page_shikigami_records)
        if enable_name:
            group, team = getattr(conf, f'{action_type}_group_team_name').split(',', 1)
            self.run_switch_soul_by_name(group.strip(), team.strip())
        elif enable_number:
            self.run_switch_soul(getattr(conf, f'{action_type}_group_team'))

        self.exit_shikigami_records()
        self.goto_page(pages.page_main)

    def finish_activity_task(self):
        self.goto_page(pages.page_main)
        if self.conf.general_config.active_souls_clean:
            self.set_next_run(task='SoulsTidy', success=False, finish=False, target=datetime.now())
        self.set_next_run(task=self.scheduled_task_name, success=True)
        raise TaskEnd
