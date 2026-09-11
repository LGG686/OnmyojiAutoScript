"""伪神降临兼容占位流程；素材下次复刻时重做。"""

import random
import time

from module.logger import logger
from tasks.ActivityShikigami.base_act import ActivityResourceNotEnough
from tasks.ActivityShikigami.assets import ActivityShikigamiAssets
import tasks.ActivityShikigami.page as pages
from tasks.GlobalGame.assets import GlobalGameAssets


class FakeGodAct:
    def setup_fakegod_pages(self):
        page_act = self.navigator.resolve_page(pages.page_act)
        page_action = self.navigator.resolve_page(pages.page_fakegod_action)

        page_second = self.navigator.add_page(pages.Page(
            ActivityShikigamiAssets.I_FG_AS_CHECK_MAIN_2,
            category='activity_shikigami',
        ))
        page_second.add_enter_success_hooks(GlobalGameAssets.I_UI_BACK_RED)
        page_act.connect(page_second, ActivityShikigamiAssets.I_FG_TO_BATTLE_MAIN, key='activity->fakegod_second')
        page_second.connect(page_act, GlobalGameAssets.I_UI_BACK_CIRCLE, key='fakegod_second->activity')

        page_dark = self.navigator.add_page(pages.Page(
            ActivityShikigamiAssets.I_FG_AS_CLOSE_EYE,
            category='activity_shikigami',
            priority=75,
        ))
        page_dark.add_enter_failure_hooks(GlobalGameAssets.I_UI_BACK_RED)
        page_dark.add_enter_success_hooks(ActivityShikigamiAssets.I_FG_AS_LOCATE)
        page_dark.connect(page_act, GlobalGameAssets.I_UI_BACK_CIRCLE, key='fakegod_dark->activity')
        page_second.connect(page_dark, ActivityShikigamiAssets.I_FG_AS_OPEN_EYE, key='fakegod_second->dark')
        page_action.connect(page_dark, GlobalGameAssets.I_UI_BACK_YELLOW, key='fakegod_action->dark')
        page_dark.connect(page_action, ActivityShikigamiAssets.I_FG_AS_TO_PASS, key='fakegod_dark->action')

    def run_fakegod(self):
        logger.hr('Start activity: Fakegod', 1)
        self.setup_fakegod_pages()
        destination = pages.page_fakegod_action
        self.goto_page(destination)
        self._sync_fakegod_team_lock()

        while True:
            self.screenshot()
            current_page = self.get_current_page()
            if current_page == destination:
                if not self.prepare_next_action('fakegod'):
                    return
                try:
                    self._run_fakegod_action(destination)
                except ActivityResourceNotEnough:
                    logger.info('Fakegod action resource exhausted')
                    return
                continue
            if current_page in (pages.page_battle_prepare, pages.page_battle):
                self.run_general_battle(
                    self.battle_config('fakegod'),
                    battle_key='activity_fakegod',
                )
                continue
            if current_page == pages.page_reward:
                self.click(self._battle_settlement_click(), interval=1.5)
                continue
            if current_page is None:
                time.sleep(0.5)
                continue
            self.goto_page(destination)

    def _run_fakegod_action(self, destination):
        self.screenshot()
        remain = self.O_FG_REMAIN_PASS.ocr_digit(self.device.image)
        trial = remain <= 0
        self.switch_soul_for(
            'fakegod',
            self.I_FG_BATTLE_MAIN_TO_RECORDS,
            return_page=destination,
        )
        if trial:
            entered = self.verify_zero_ticket(
                'ActivityShikigami fakegod action',
                lambda: self._enter_fakegod_battle(max_times=1),
            )
        else:
            entered = self._enter_fakegod_battle()
        if not entered:
            raise ActivityResourceNotEnough
        self.record_action('fakegod')
        self.run_general_battle(
            self.battle_config('fakegod'),
            battle_key='activity_fakegod',
        )

    def _enter_fakegod_battle(self, max_times: int | None = None) -> bool:
        click_times = 0
        fallback = max_times is not None
        max_times = max_times or random.randint(3, 5)
        while True:
            self.screenshot()
            if self.is_in_battle(False):
                return True
            if click_times >= max_times:
                return False if fallback else self._raise_fakegod_resource_error()
            if self.appear(self.I_UI_BACK_RED, interval=1):
                return False if fallback else self._raise_fakegod_resource_error()
            if self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=1) or \
                    self.appear_then_click(self.I_UI_CONFIRM, interval=1):
                continue
            if self.appear_then_click(self.I_FG_ACT_FIRE, interval=1):
                self.device.click_record_clear()
                click_times += 1
                if fallback:
                    return self._wait_fakegod_trial_result(timeout=3.0)

    @staticmethod
    def _raise_fakegod_resource_error():
        raise ActivityResourceNotEnough

    def _wait_fakegod_trial_result(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.screenshot()
            if self.is_in_battle(False):
                return True
            if self.appear(self.I_UI_CONFIRM_SAMLL) or self.appear(self.I_UI_CONFIRM):
                return False
            if self.appear(self.I_UI_BACK_RED):
                return False
            time.sleep(0.2)
        return False

    def _sync_fakegod_team_lock(self):
        if self.battle_config('fakegod').lock_team_enable:
            self.ui_click(self.I_FG_UNLOCK, stop=self.I_FG_LOCK, interval=1.5)
        else:
            self.ui_click(self.I_FG_LOCK, stop=self.I_FG_UNLOCK, interval=1.5)
