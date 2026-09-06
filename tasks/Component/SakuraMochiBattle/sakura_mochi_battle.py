from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from module.base.timer import Timer
from module.exception import GameStuckError
from module.logger import logger
from tasks.Component.GeneralBattle.general_battle import ExitMatcher, GeneralBattle
from tasks.GameUi.common import ActionLike, RecognizerLike
from tasks.GameUi.navigator import GameUi
from tasks.GameUi.page import page_battle, page_battle_prepare, page_battle_result, page_reward
from tasks.GameUi.page_definition import Page


class SakuraMochiBattleState(str, Enum):
    """樱饼挂机观察器能够识别的状态。"""

    TASK_PAGE = 'task_page'
    PREPARE = 'prepare'
    BATTLE = 'battle'
    RESULT = 'result'
    REWARD = 'reward'
    UNKNOWN = 'unknown'


SakuraMochiObserver = Callable[[SakuraMochiBattleState, 'SakuraMochiBattleSummary'], None]


@dataclass(frozen=True)
class SakuraMochiBattleProfile:
    """由支持樱饼挂机的任务声明入口及开关状态。"""

    # OASX/任务配置中的总开关。关闭时组件不会点击入口。
    enabled: bool
    # 任务专用的樱饼入口。可以是图片、点击区域或动作序列。
    entry_action: ActionLike
    # 樱饼挂机已开启和已关闭的任务专用识别标志。
    active_marker: RecognizerLike
    inactive_marker: RecognizerLike | None
    # 仅在任务主页出现时判断开关状态，避免战斗中看不到按钮时误判结束。
    task_page_marker: ExitMatcher
    battle_key: str = 'sakura_mochi'
    activation_timeout: float = 5.0
    inactive_confirm_frames: int = 2
    observer: SakuraMochiObserver | None = None

    def __post_init__(self) -> None:
        if self.activation_timeout <= 0:
            raise ValueError('activation_timeout must be greater than 0')
        if self.inactive_confirm_frames <= 0:
            raise ValueError('inactive_confirm_frames must be greater than 0')


@dataclass
class SakuraMochiBattleSummary:
    """本次樱饼挂机观察结果。"""

    battle_key: str
    rounds: int = 0
    wins: int = 0
    losses: int = 0
    last_state: SakuraMochiBattleState = SakuraMochiBattleState.UNKNOWN
    last_result: bool | None = None


class SakuraMochiBattle(GeneralBattle):
    """启动樱饼后只观察战斗状态，不接管任何后续点击。"""

    _SAKURA_BATTLE_PAGES = (
        page_battle_prepare,
        page_battle,
        page_battle_result,
        page_reward,
    )

    def _match_sakura_marker(self, marker: ExitMatcher | None) -> bool:
        if marker is None:
            return False
        return self._evaluate_exit_matcher(marker)

    def _notify_sakura_state(
        self,
        profile: SakuraMochiBattleProfile,
        state: SakuraMochiBattleState,
        summary: SakuraMochiBattleSummary,
    ) -> None:
        if summary.last_state == state:
            return
        logger.info(f'Sakura mochi battle state: {summary.last_state.value} -> {state.value}')
        summary.last_state = state
        if profile.observer is not None:
            profile.observer(state, summary)

    def _activate_sakura_mochi(self, profile: SakuraMochiBattleProfile) -> None:
        """只执行一次任务声明的入口动作，并等待开启态出现。"""

        self.screenshot()
        if self._match_sakura_marker(profile.active_marker):
            logger.info('Sakura mochi auto battle is already enabled')
            return
        if not self._match_sakura_marker(profile.task_page_marker):
            raise GameStuckError('Sakura mochi task page marker was not found')
        if profile.inactive_marker is not None and not self._match_sakura_marker(profile.inactive_marker):
            raise GameStuckError('Sakura mochi switch state could not be confirmed')

        if not self._execute_action(profile.entry_action, interval=0.8, skip_first_screenshot=True):
            raise GameStuckError('Sakura mochi entry action was not executed')

        timer = Timer(profile.activation_timeout).start()
        while True:
            self.screenshot()
            if self._match_sakura_marker(profile.active_marker):
                logger.info('Sakura mochi auto battle enabled')
                return
            if timer.reached():
                raise GameStuckError(
                    f'Sakura mochi enabled marker not found within {profile.activation_timeout}s'
                )

    @staticmethod
    def _state_from_page(page: Page | None) -> SakuraMochiBattleState:
        if page == page_battle_prepare:
            return SakuraMochiBattleState.PREPARE
        if page == page_battle:
            return SakuraMochiBattleState.BATTLE
        if page == page_battle_result:
            return SakuraMochiBattleState.RESULT
        if page == page_reward:
            return SakuraMochiBattleState.REWARD
        return SakuraMochiBattleState.UNKNOWN

    def _start_observed_sakura_round(
        self,
        summary: SakuraMochiBattleSummary,
    ) -> None:
        logger.hr('General battle start', 2)
        self.current_count += 1
        summary.rounds += 1
        logger.info(f'Current count: {self.current_count}')
        logger.info(f'Sakura mochi observed round: {summary.rounds}')

    def run_sakura_mochi_battle(
        self,
        profile: SakuraMochiBattleProfile,
    ) -> SakuraMochiBattleSummary:
        """开启樱饼挂机并被动记录完整战斗流程。

        启动后本方法只调用截图和识别接口，不点击准备、战斗、结算、奖励、
        自动模式或任务主页。樱饼关闭并在任务主页稳定出现后返回统计结果。
        """

        summary = SakuraMochiBattleSummary(battle_key=profile.battle_key)
        if not profile.enabled:
            logger.info('Sakura mochi auto battle is disabled')
            return summary

        self._activate_sakura_mochi(profile)
        if not self._custom_pages_registered:
            self._register_custom_pages()
            self._custom_pages_registered = True

        self.device.stuck_record_add('BATTLE_STATUS_S')
        long_refresh_timer = Timer(180).start()
        round_active = False
        settlement_seen = False
        result_recorded = False
        inactive_frames = 0

        try:
            while True:
                self.screenshot()
                if long_refresh_timer.reached():
                    logger.info('Refresh sakura mochi battle stuck timer')
                    self.device.stuck_record_clear()
                    self.device.stuck_record_add('BATTLE_STATUS_S')
                    long_refresh_timer.reset()

                page = GameUi.detect_page_in(
                    self,
                    *self._SAKURA_BATTLE_PAGES,
                    include_global=False,
                )
                state = self._state_from_page(page)
                self.device.screenshot_interval_set(
                    'combat' if state == SakuraMochiBattleState.BATTLE else None
                )

                if state in {SakuraMochiBattleState.PREPARE, SakuraMochiBattleState.BATTLE}:
                    if settlement_seen:
                        round_active = False
                        settlement_seen = False
                        result_recorded = False
                    if not round_active:
                        self._start_observed_sakura_round(summary)
                        round_active = True
                    inactive_frames = 0
                elif state in {SakuraMochiBattleState.RESULT, SakuraMochiBattleState.REWARD}:
                    if not round_active:
                        self._start_observed_sakura_round(summary)
                        round_active = True
                    settlement_seen = True
                    inactive_frames = 0
                    if not result_recorded:
                        is_win = state == SakuraMochiBattleState.REWARD or not self.appear(
                            self.I_FALSE,
                            threshold=0.8,
                        )
                        summary.last_result = is_win
                        summary.wins += int(is_win)
                        summary.losses += int(not is_win)
                        logger.info(f'Battle result: {"Win" if is_win else "Lose"}')
                        result_recorded = True
                elif self._match_sakura_marker(profile.task_page_marker):
                    state = SakuraMochiBattleState.TASK_PAGE
                    if settlement_seen:
                        round_active = False
                    if self._match_sakura_marker(profile.active_marker):
                        inactive_frames = 0
                    elif profile.inactive_marker is None or self._match_sakura_marker(profile.inactive_marker):
                        inactive_frames += 1
                        if inactive_frames >= profile.inactive_confirm_frames:
                            self._notify_sakura_state(profile, state, summary)
                            logger.info(
                                'Sakura mochi auto battle finished: '
                                f'rounds={summary.rounds}, wins={summary.wins}, losses={summary.losses}'
                            )
                            return summary
                    else:
                        inactive_frames = 0
                else:
                    inactive_frames = 0

                self._notify_sakura_state(profile, state, summary)
        finally:
            self.device.screenshot_interval_set()
