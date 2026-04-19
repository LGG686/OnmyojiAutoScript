# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from enum import Enum
from tasks.GameUi.default_pages import random_click
from typing import Union

from module.atom.gif import RuleGif
from module.atom.image import RuleImage
from module.atom.ocr import RuleOcr
from module.base.timer import Timer
from module.base.utils import color_similar, get_color
from module.logger import logger
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig, GreenMarkType
from tasks.Component.GeneralBuff.config_buff import BuffClass
from tasks.Component.GeneralBuff.general_buff import GeneralBuff
from tasks.GameUi.common import RecognizerLike, invoke_task_callable
from tasks.GameUi.matcher import Matcher, ensure_matcher
from tasks.GameUi.navigator import GameUi
from tasks.GameUi.page import page_battle, page_battle_prepare, page_battle_result, page_reward
from tasks.GameUi.page_definition import Page


# 战斗结束后用于确认“已经回到任务自身页面”的识别条件。
# 推荐优先复用调用方战后原本就会 `wait_until_appear(...)` 的稳定特征。
ExitMatcher = Union[Matcher | RecognizerLike | Page]


@dataclass
class OnceFlags:
    preset_done: bool = False
    buff_done: bool = False
    green_done: bool = False


@dataclass
class BattleRuntime:
    battle_timer: Timer
    long_refresh_timer: Timer
    last_page: Page | None = None
    continuous_count: int = 1
    reward_no_battle_ts: float | None = None
    quick_exit: bool = False
    is_win: bool = False


class BattleAction(str, Enum):
    CONTINUE = "continue"
    EXIT_WIN = "exit_win"
    EXIT_LOSE = "exit_lose"
    QUICK_EXIT = "quick_exit"


class GeneralBattle(GeneralBuff, GeneralBattleAssets):
    """
    使用这个通用的战斗必须要求这个任务的 config 有 general_battle_config。
    """

    def __init__(self, config, device) -> None:
        """初始化通用战斗运行时缓存。

        Args:
            config: 当前任务配置对象。
            device: 当前设备对象。
        """
        super().__init__(config, device)
        self._battle_once_flags: dict[str, OnceFlags] = {}
        self._custom_pages_registered: bool = False

    def _register_custom_pages(self) -> None:
        """供子任务在 session 内覆写战斗页面识别规则。

        Returns:
            None: 基类默认不做任何处理。
        """

    def _exit_matcher(self) -> ExitMatcher | None:
        """返回任务级默认的战斗结束识别条件。

        子任务可覆写此方法，声明“战斗结算完成后，理论上应该回到哪里”。
        典型返回值是任务主界面的按钮、房间页标记或一个 `Page` 对象。
        若任务内不同调用点会回到不同页面，优先在 `run_general_battle(..., exit_matcher=...)`
        里显式传参覆盖，而不是在这里写复杂分支。

        Returns:
            ExitMatcher | None: 默认结束识别条件；`None` 表示禁用快速结束，回退到 2 秒兜底。
        """

        return None

    def _evaluate_exit_matcher(self, target: ExitMatcher | None) -> bool:
        """执行一次 exit matcher 判断。

        分派规则保持最小化，不引入新的识别栈：

        - `None`：直接返回 `False`
        - `Page`：解析为当前 session page 后用 `_match_page_once()` 判定
        - 自定义 callable：透传当前任务实例，兼容零参/单参函数
        - 其他 Rule/Matcher：统一走 `ensure_matcher(...).evaluate(self)`

        Args:
            target: 待判定的结束识别条件。

        Returns:
            bool: 当前截图是否已经满足该结束识别条件。
        """

        if target is None:
            return False
        if isinstance(target, Page):
            session_page = self.navigator.resolve_page(target)
            if session_page is None:
                return False
            return bool(self._match_page_once(session_page))
        if callable(target) and not isinstance(target, (RuleImage, RuleGif, RuleOcr)):
            return bool(invoke_task_callable(target, self))

        matcher = ensure_matcher(target)
        if matcher is None:
            return False
        return bool(matcher.evaluate(self))

    def is_in_battle(self, is_screenshot: bool = True) -> bool:
        """兼容旧任务的战斗态快速检测。

        Args:
            is_screenshot: 是否先执行一次截图。

        Returns:
            bool: 当前是否处于准备、战斗、结算或奖励相关页面。
        """

        if is_screenshot:
            self.screenshot()
        return (
            self.appear(self.I_BATTLE_INFO)
            or self.appear(self.I_FRIENDS)
            or self.appear(self.I_WIN)
            or self.appear(self.I_DE_WIN)
            or self.appear(self.I_FALSE)
            or self.appear(self.I_REWARD)
            or self.appear(self.I_REWARD_GOLD)
        )

    def is_in_real_battle(self, is_screenshot: bool = True) -> bool:
        """兼容旧任务的纯战斗中检测。

        Args:
            is_screenshot: 是否先执行一次截图。

        Returns:
            bool: 当前是否处于真正的战斗中页面。
        """

        if is_screenshot:
            self.screenshot()
        return self.appear(self.I_BATTLE_INFO)

    def is_in_prepare(self, is_screenshot: bool = True) -> bool:
        """兼容旧任务的准备页检测。

        Args:
            is_screenshot: 是否先执行一次截图。

        Returns:
            bool: 当前是否处于准备页。
        """

        if is_screenshot:
            self.screenshot()
        return (
            self.appear(self.I_BUFF)
            or self.appear(self.I_PREPARE_HIGHLIGHT)
            or self.appear(self.I_PREPARE_DARK)
            or self.appear(self.I_PRESET)
            or self.appear(self.I_PRESET_WIT_NUMBER)
        )

    def _resolve_battle_timeout(self, config: GeneralBattleConfig) -> int:
        """解析当前战斗应使用的硬超时时间。

        Args:
            config: 当前通用战斗配置。

        Returns:
            int: 本次战斗的超时秒数。
        """
        if config.battle_timeout is not None and config.battle_timeout > 0:
            return config.battle_timeout
        global_battle = getattr(getattr(self.config, "global_game", None), "battle", None)
        return getattr(global_battle, "battle_timeout", 420)

    def _build_runtime(self, config: GeneralBattleConfig) -> BattleRuntime:
        """构建一次战斗调用期使用的运行时状态。

        Args:
            config: 当前通用战斗配置。

        Returns:
            BattleRuntime: 初始化后的战斗运行时对象。
        """
        timeout = self._resolve_battle_timeout(config)
        return BattleRuntime(
            battle_timer=Timer(timeout).start(),
            long_refresh_timer=Timer(180).start(),
            quick_exit=bool(config.quick_exit),
        )

    @staticmethod
    def build_quick_exit_config(config: GeneralBattleConfig | None = None) -> GeneralBattleConfig:
        """基于现有配置构造一个快速退出专用配置副本。

        Args:
            config: 原始通用战斗配置；为空时使用默认配置。

        Returns:
            GeneralBattleConfig: 仅将 `quick_exit` 置为 `True` 的配置副本。
        """
        base_config = config if config is not None else GeneralBattleConfig()
        return base_config.model_copy(update={"quick_exit": True})

    def _reset_round_runtime(self, runtime: BattleRuntime, config: GeneralBattleConfig, *, continuous_count: int) -> None:
        """在连战开启时重置下一轮战斗的运行时字段。

        Args:
            runtime: 当前战斗运行时对象。
            config: 当前通用战斗配置。
            continuous_count: 下一轮连战计数。

        Returns:
            None: 直接原地修改 `runtime`。
        """
        runtime.battle_timer = Timer(self._resolve_battle_timeout(config)).start()
        runtime.long_refresh_timer = Timer(180).start()
        runtime.last_page = None
        runtime.reward_no_battle_ts = None
        runtime.quick_exit = bool(config.quick_exit)
        runtime.continuous_count = continuous_count

    def _tick_long_battle(self, runtime: BattleRuntime) -> None:
        """按固定周期刷新长战斗卡死保护标记。

        Args:
            runtime: 当前战斗运行时对象。

        Returns:
            None: 需要刷新时原地重置底层长等待状态。
        """
        if runtime.long_refresh_timer.reached():
            logger.info("Refresh long battle stuck timer")
            self.device.stuck_record_clear()
            self.device.stuck_record_add("BATTLE_STATUS_S")
            runtime.long_refresh_timer.reset()

    def _ensure_battle_stuck_guard(self, runtime: BattleRuntime, page: Page) -> None:
        """在准备/战斗中阶段确保底层长等待标记始终存在。

        Args:
            runtime: 当前战斗运行时对象。
            page: 当前识别到的战斗页面。

        Returns:
            None: 需要时原地补挂战斗卡死保护标记。
        """

        if page not in {page_battle_prepare, page_battle}:
            return
        if runtime.last_page not in {page_battle_prepare, page_battle}:
            logger.info("Arm battle stuck guard")
            if "BATTLE_STATUS_S" not in self.device.detect_record:
                self.device.stuck_record_add("BATTLE_STATUS_S")
            runtime.battle_timer.reset()
            runtime.long_refresh_timer.reset()
            return
        if "BATTLE_STATUS_S" in self.device.detect_record:
            return

        self.device.stuck_record_add("BATTLE_STATUS_S")
        runtime.long_refresh_timer.reset()

    def _tick_timeout(self, runtime: BattleRuntime) -> None:
        """推进战斗超时检测。

        Args:
            runtime: 当前战斗运行时对象。

        Returns:
            None: 超时时将 `runtime.quick_exit` 置为 `True`。
        """
        if runtime.quick_exit:
            return
        if runtime.last_page not in {page_battle_prepare, page_battle}:
            return
        if runtime.battle_timer.reached():
            logger.warning(f"Battle timeout reached: {runtime.battle_timer.limit}s")
            runtime.quick_exit = True

    def _handle_prepare(
        self,
        runtime: BattleRuntime,
        once: OnceFlags,
        config: GeneralBattleConfig,
        buff: Union[BuffClass | list[BuffClass] | None],
    ) -> BattleAction:
        """处理准备页逻辑。

        Args:
            runtime: 当前战斗运行时对象。
            once: 当前 `battle_key` 对应的一次性标志。
            config: 当前通用战斗配置。
            buff: 需要开启的 buff 配置。

        Returns:
            BattleAction: 当前轮准备页处理后的动作决策。
        """
        if runtime.last_page in {page_battle_result, page_reward}:
            action = self._handle_continuous_prepare(runtime, config)
            if action != BattleAction.CONTINUE:
                return action
            if not config.continuous_battle:
                return BattleAction.EXIT_WIN if runtime.is_win else BattleAction.EXIT_LOSE

        if self.appear_then_click(self.I_DISABLE_7DAYS_DIFF_SOUL, interval=0.6):
            return BattleAction.CONTINUE
        if self.appear_then_click(self.I_CONFIRM_CLOSE_DIFF_SOUL, interval=0.6):
            return BattleAction.CONTINUE

        if not once.preset_done:
            self.switch_preset_team(config.preset_enable, config.preset_group, config.preset_team)
            once.preset_done = True
        if not once.buff_done:
            self.check_and_open_buff(buff)
            once.buff_done = True

        self.appear_then_click(self.I_PREPARE_HIGHLIGHT, interval=0.8)
        return BattleAction.CONTINUE

    def _handle_in_battle(
        self,
        runtime: BattleRuntime,
        once: OnceFlags,
        config: GeneralBattleConfig,
        buff: Union[BuffClass | list[BuffClass] | None],
    ) -> BattleAction:
        """处理战斗中页面逻辑。

        Args:
            runtime: 当前战斗运行时对象。
            once: 当前 `battle_key` 对应的一次性标志。
            config: 当前通用战斗配置。
            buff: 保留的 buff 参数，供覆写方法复用。

        Returns:
            BattleAction: 当前轮战斗中处理后的动作决策。
        """
        if not once.green_done:
            self.green_mark(config.green_enable, config.green_mark)
            once.green_done = True
        if config.random_click_swipt_enable:
            self.random_click_swipt()
        if runtime.quick_exit:
            return BattleAction.QUICK_EXIT
        return BattleAction.CONTINUE

    def _handle_result(
        self,
        runtime: BattleRuntime,
        once: OnceFlags,
        config: GeneralBattleConfig,
        buff: Union[BuffClass | list[BuffClass] | None],
    ) -> BattleAction:
        """处理结算页面逻辑。

        Args:
            runtime: 当前战斗运行时对象。
            once: 当前 `battle_key` 对应的一次性标志。
            config: 当前通用战斗配置。
            buff: 保留的 buff 参数，供覆写方法复用。

        Returns:
            BattleAction: 当前轮结算页处理后的动作决策。
        """
        runtime.reward_no_battle_ts = None
        runtime.is_win = not self.appear(self.I_FALSE, threshold=0.8)
        logger.info(f"Battle result is {'win' if runtime.is_win else 'false'}")
        if runtime.is_win:
            self.appear_then_click(self.I_WIN, action=random_click(), interval=0.5)
            self.appear_then_click(self.I_DE_WIN, action=random_click(), interval=0.5)
        else:
            self.appear_then_click(self.I_FALSE, threshold=0.6, interval=0.5)
        return BattleAction.CONTINUE

    def _handle_reward(
        self,
        runtime: BattleRuntime,
        once: OnceFlags,
        config: GeneralBattleConfig,
        buff: Union[BuffClass | list[BuffClass] | None],
    ) -> BattleAction:
        """处理奖励页面逻辑。

        Args:
            runtime: 当前战斗运行时对象。
            once: 当前 `battle_key` 对应的一次性标志。
            config: 当前通用战斗配置。
            buff: 保留的 buff 参数，供覆写方法复用。

        Returns:
            BattleAction: 当前轮奖励页处理后的动作决策。
        """
        runtime.reward_no_battle_ts = None
        self.click(random_click(), interval=0.6)
        return BattleAction.CONTINUE

    def _handle_missing_battle_page(
        self,
        runtime: BattleRuntime,
        config: GeneralBattleConfig,
        exit_matcher: ExitMatcher | None,
    ) -> BattleAction:
        """处理暂时未识别到任何战斗页面的过渡状态。

        Args:
            runtime: 当前战斗运行时对象。
            config: 当前通用战斗配置。
            exit_matcher: 战斗结束后的任务页面识别条件。
                仅在最近一页是 `page_battle_result/page_reward` 且未开启连战时参与快速退出判定。

        Returns:
            BattleAction: 根据结算收尾状态推导出的动作决策。
        """
        if (
            runtime.last_page in {page_battle_result, page_reward}
            and not config.continuous_battle
            and exit_matcher is not None
            and self._evaluate_exit_matcher(exit_matcher)
        ):
            logger.info("Exit matcher hit, battle confirmed ended")
            return BattleAction.EXIT_WIN if runtime.is_win else BattleAction.EXIT_LOSE
        if runtime.last_page not in {page_battle_result, page_reward} and runtime.reward_no_battle_ts is None:
            return BattleAction.CONTINUE
        if runtime.reward_no_battle_ts is None:
            runtime.reward_no_battle_ts = time.time()
            return BattleAction.CONTINUE
        if time.time() - runtime.reward_no_battle_ts >= 2:
            return BattleAction.EXIT_WIN if runtime.is_win else BattleAction.EXIT_LOSE
        return BattleAction.CONTINUE

    def _handle_continuous_prepare(self, runtime: BattleRuntime, config: GeneralBattleConfig) -> BattleAction:
        """处理结算后回到准备页时的连战分支。

        Args:
            runtime: 当前战斗运行时对象。
            config: 当前通用战斗配置。

        Returns:
            BattleAction: 连战继续、按结果退出等动作决策。
        """
        if not config.continuous_battle or runtime.last_page not in {page_battle_result, page_reward}:
            return BattleAction.CONTINUE
        if 0 < config.max_continuous <= runtime.continuous_count:
            return BattleAction.EXIT_WIN if runtime.is_win else BattleAction.EXIT_LOSE
        next_count = runtime.continuous_count + 1
        logger.info(f"Continue battle round: {next_count}")
        self._reset_round_runtime(runtime, config, continuous_count=next_count)
        return BattleAction.CONTINUE

    def _resolve_action(self, action: BattleAction) -> bool | None:
        """统一处理内部动作枚举并解析最终返回值。

        Args:
            action: 当前处理得到的动作枚举。

        Returns:
            bool | None: `True/False` 表示战斗结束结果，`None` 表示继续主循环。
        """
        if action == BattleAction.EXIT_WIN:
            return True
        if action == BattleAction.EXIT_LOSE:
            return False
        if action == BattleAction.QUICK_EXIT:
            self.exit_battle()
        return None

    def run_general_battle(
        self,
        config: GeneralBattleConfig = None,
        buff: Union[BuffClass | list[BuffClass]] = None,
        battle_key: str = "default",
        exit_matcher: ExitMatcher | None = None,
    ) -> bool:
        """
        运行基于 Page FSM 的通用战斗。

        Args:
            config: 当前通用战斗配置；为空时使用默认配置。
            buff: 本轮战斗需要开启的 buff 配置。
            battle_key: 一次性步骤缓存键；同 key 可复用预设、buff、绿标状态。
            exit_matcher: 本次调用专用的结束识别条件。
                优先级高于 `_exit_matcher()`；适合同一任务不同入口回不同页面的场景。
                传 `None` 时会继续尝试任务级 `_exit_matcher()`，若仍为空则回退到 2 秒兜底。

        Returns:
            bool: `True` 表示本轮战斗获胜，`False` 表示失败或主动退出。
        """
        logger.hr("General battle start", 2)
        if config is None:
            config = GeneralBattleConfig()

        if not self._custom_pages_registered:
            self._register_custom_pages()
            self._custom_pages_registered = True

        self.current_count += 1
        logger.info(f"Current count: {self.current_count}")
        self.device.stuck_record_add("BATTLE_STATUS_S")
        self.device.click_record_clear()

        runtime = self._build_runtime(config)
        once = self._battle_once_flags.setdefault(battle_key, OnceFlags())
        resolved_exit_matcher = exit_matcher if exit_matcher is not None else self._exit_matcher()

        while True:
            self.screenshot()
            self._tick_long_battle(runtime)
            self._tick_timeout(runtime)
            runtime.quick_exit = runtime.quick_exit or bool(config.quick_exit)

            page = GameUi.detect_page_in(
                self,
                page_battle_prepare,
                page_battle,
                page_battle_result,
                page_reward,
                include_global=False,
            )
            if page is None:
                action = self._handle_missing_battle_page(runtime, config, resolved_exit_matcher)
                resolved = self._resolve_action(action)
                if resolved is not None:
                    return resolved
                time.sleep(0.3)
                continue

            runtime.reward_no_battle_ts = None
            self._ensure_battle_stuck_guard(runtime, page)

            match page:
                case current if current == page_battle_prepare:
                    action = self._handle_prepare(runtime, once, config, buff)
                case current if current == page_battle:
                    action = self._handle_in_battle(runtime, once, config, buff)
                case current if current == page_battle_result:
                    action = self._handle_result(runtime, once, config, buff)
                case current if current == page_reward:
                    action = self._handle_reward(runtime, once, config, buff)
                case _:
                    action = BattleAction.CONTINUE

            resolved = self._resolve_action(action)
            if resolved is not None:
                return resolved

            runtime.last_page = page
        return False

    def exit_battle(self, skip_first: bool = False) -> bool:
        """
        在战斗的时候强制退出战斗。

        Args:
            skip_first: 是否跳过第一次截图，直接复用当前帧判断。

        Returns:
            bool: 是否识别到可退出的战斗页面并执行了退出流程。
        """
        if skip_first:
            self.screenshot()
        if not self.appear(self.I_EXIT):
            return False
        timeout = Timer(5).start()
        while True:
            self.screenshot()
            if timeout.reached():
                logger.info('Exit battle success')
                break
            if self.appear_then_click(self.I_EXIT_ENSURE, interval=2):
                timeout.reset()
                continue
            if self.appear_then_click(self.I_EXIT, interval=5):
                timeout.reset()
                continue
        return True

    def green_mark(self, enable: bool = False, mark_mode: GreenMarkType = GreenMarkType.GREEN_MAIN):
        """
        绿标， 如果不使能就直接返回。

        Args:
            enable: 是否启用绿标操作。
            mark_mode: 绿标目标位置。

        Returns:
            None: 直接执行绿标相关点击。
        """
        if enable:
            logger.info("Green is enable")
            x, y = None, None
            match mark_mode:
                case GreenMarkType.GREEN_LEFT1:
                    x, y = self.C_GREEN_LEFT_1.coord()
                    logger.info("Green left 1")
                case GreenMarkType.GREEN_LEFT2:
                    x, y = self.C_GREEN_LEFT_2.coord()
                    logger.info("Green left 2")
                case GreenMarkType.GREEN_LEFT3:
                    x, y = self.C_GREEN_LEFT_3.coord()
                    logger.info("Green left 3")
                case GreenMarkType.GREEN_LEFT4:
                    x, y = self.C_GREEN_LEFT_4.coord()
                    logger.info("Green left 4")
                case GreenMarkType.GREEN_LEFT5:
                    x, y = self.C_GREEN_LEFT_5.coord()
                    logger.info("Green left 5")
                case GreenMarkType.GREEN_MAIN:
                    x, y = self.C_GREEN_MAIN.coord()
                    logger.info("Green main")

            while 1:
                self.screenshot()
                if not self.appear(self.I_PREPARE_HIGHLIGHT):
                    break

            self.appear_then_click(self.I_LOCAL)
            time.sleep(0.3)
            self.device.click(x, y)

    def switch_preset_team(self, enable: bool = False, preset_group: int = 1, preset_team: int = 1):
        """
        切换预设的队伍，要求是在不锁定队伍时的情况下。

        Args:
            enable: 是否启用切换预设。
            preset_group: 目标预设组编号。
            preset_team: 目标预设队伍编号。

        Returns:
            None: 成功时切换到目标预设，失败时保留当前阵容。
        """
        if not enable:
            logger.info("Preset is disable")
            return None

        logger.info("Preset is enable")
        timeout_warning = "Switch preset timeout, use current team"

        wait_preset_timer = Timer(4).start()
        while 1:
            if wait_preset_timer.reached():
                logger.warning(timeout_warning)
                return
            self.screenshot()

            if self.appear(self.I_PRESET_ENSURE):
                break
            if self.appear(self.I_PRESENT_LESS_THAN_5):
                break
            if self.appear_then_click(self.I_PRESET, threshold=0.8, interval=1):
                continue
            if self.appear_then_click(self.I_PRESET_WIT_NUMBER, threshold=0.8, interval=1):
                continue
            if self.ocr_appear(self.O_PRESET):
                self.click(self.O_PRESET, interval=1)
                continue
            if self.ocr_appear(self.O_PRESET_FULL):
                self.click(self.O_PRESET_FULL, interval=1)
                continue
        logger.info("Click preset button")

        def get_unselect_color(tmp1, tmp2, tmp3, size):
            color_1 = get_color(
                self.device.image,
                (tmp1.roi_back[0], tmp1.roi_back[1], tmp1.roi_back[0] + size[0], tmp1.roi_back[1] + size[1]),
            )
            color_2 = get_color(
                self.device.image,
                (tmp2.roi_back[0], tmp2.roi_back[1], tmp2.roi_back[0] + size[0], tmp2.roi_back[1] + size[1]),
            )
            color_3 = get_color(
                self.device.image,
                (tmp3.roi_back[0], tmp3.roi_back[1], tmp3.roi_back[0] + size[0], tmp3.roi_back[1] + size[1]),
            )

            if color_similar(color_1, color_2):
                return color_1
            if color_similar(color_2, color_3):
                return color_2
            return color_3

        tmp = self.__getattribute__("C_PRESET_GROUP_" + str(preset_group))
        if tmp is None:
            tmp = self.C_PRESET_GROUP_1
        color_size = [self.C_PRESET_GROUP_1.roi_back[2], self.C_PRESET_GROUP_1.roi_back[3]]
        # 保留原颜色策略以兼容旧资源。
        _ = get_unselect_color
        unselected_color = (224.9, 208.3, 187.4)
        choose_group_timer = Timer(4).start()
        while True:
            if choose_group_timer.reached():
                logger.warning(timeout_warning)
                return
            self.screenshot()
            color_tmp = get_color(
                self.device.image,
                (tmp.roi_back[0], tmp.roi_back[1], tmp.roi_back[0] + color_size[0], tmp.roi_back[1] + color_size[1]),
            )
            if color_similar(color_tmp, unselected_color):
                self.click(tmp, interval=0.2)
                continue
            break

        logger.info("Select preset group")

        time.sleep(0.5)
        tmp = self.__getattribute__("C_PRESET_TEAM_" + str(preset_team))
        if tmp is None:
            tmp = self.C_PRESET_TEAM_1
        color_size = [5, 5]
        unselected_color = (216.8, 185.0, 146.8)
        choose_team_timer = Timer(4).start()
        while True:
            if choose_team_timer.reached():
                logger.warning(timeout_warning)
                return
            self.screenshot()
            color_tmp = get_color(
                self.device.image,
                (tmp.roi_back[0], tmp.roi_back[1], tmp.roi_back[0] + color_size[0], tmp.roi_back[1] + color_size[1]),
            )
            if color_similar(color_tmp, unselected_color):
                self.click(tmp, interval=0.2)
                continue
            break

        self.click(tmp)
        logger.info("Select preset team")

        wait_ensure_timer = Timer(4).start()
        while 1:
            if wait_ensure_timer.reached():
                logger.warning(timeout_warning)
                return
            self.screenshot()
            if not self.appear(self.I_PRESET_ENSURE):
                break
            if self.appear_then_click(self.I_PRESET_ENSURE, threshold=0.8, interval=0.2):
                continue
        logger.info("Click preset ensure")

    def random_click_swipt(self):
        """在战斗过程中执行随机点击或滑动。

        Returns:
            None: 命中概率时执行随机操作，否则短暂等待。
        """
        if 0 <= random.randint(0, 500) <= 3:
            rand_type = random.randint(0, 2)
            match rand_type:
                case 0:
                    self.click(self.C_RANDOM_CLICK, interval=20)
                case 1:
                    self.swipe(self.S_BATTLE_RANDOM_LEFT, interval=20)
                case 2:
                    self.swipe(self.S_BATTLE_RANDOM_RIGHT, interval=20)
        else:
            time.sleep(0.4)

    def check_take_over_battle(self, is_screenshot: bool, config: GeneralBattleConfig) -> bool | None:
        """
        TODO: 旧接管入口，待所有调用方迁到 goto_page 接管后删除。
        中途接入战斗并接管。

        Args:
            is_screenshot: 是否先执行一次截图。
            config: 当前通用战斗配置。

        Returns:
            bool | None: 战斗结果；如果当前不在战斗态则返回 `None`。
        """
        if is_screenshot:
            self.screenshot()
        if not self.is_in_battle(False):
            return None
        return self.run_general_battle(config=config, battle_key="__legacy_takeover__")

    def check_lock(self, enable: bool, lock_image, unlock_image):
        """
        检测是否锁定队伍。

        Args:
            enable: 目标是否应为锁队状态。
            lock_image: 已锁定状态的识别图像。
            unlock_image: 未锁定状态的识别图像。

        Returns:
            None: 直接执行锁定状态切换。
        """
        if enable:
            logger.info("Lock team")
            while 1:
                self.screenshot()
                if self.appear(lock_image):
                    break
                if self.appear_then_click(unlock_image, interval=1):
                    continue
        else:
            logger.info("Unlock team")
            while 1:
                self.screenshot()
                if self.appear(unlock_image):
                    break
                if self.appear_then_click(lock_image, interval=1):
                    continue

    def check_and_open_buff(self, buff: Union[BuffClass | list[BuffClass]] = None):
        """
        检测是否开启 buff。

        Args:
            buff: 需要开启或关闭的 buff 配置；为空时直接跳过。

        Returns:
            None: 直接执行 buff 界面点击流程。
        """
        if not buff:
            return
        logger.info(f"Open buff {buff}")
        self.ui_click(self.I_BUFF, self.I_CLOUD, interval=2)
        if isinstance(buff, BuffClass):
            buff = [buff]
        match_method = {
            BuffClass.AWAKE: (self.awake, True),
            BuffClass.SOUL: (self.soul, True),
            BuffClass.GOLD_50: (self.gold_50, True),
            BuffClass.GOLD_100: (self.gold_100, True),
            BuffClass.EXP_50: (self.exp_50, True),
            BuffClass.EXP_100: (self.exp_100, True),
            BuffClass.AWAKE_CLOSE: (self.awake, False),
            BuffClass.SOUL_CLOSE: (self.soul, False),
            BuffClass.GOLD_50_CLOSE: (self.gold_50, False),
            BuffClass.GOLD_100_CLOSE: (self.gold_100, False),
            BuffClass.EXP_50_CLOSE: (self.exp_50, False),
            BuffClass.EXP_100_CLOSE: (self.exp_100, False),
        }
        for buff_item in buff:
            func, is_open = match_method[buff_item]
            func(is_open)
            time.sleep(0.1)
        logger.info("Open buff success")
        while 1:
            self.screenshot()
            if not self.appear(self.I_CLOUD):
                break
            if self.appear_then_click(self.I_BUFF, interval=1):
                continue


def run_task_or_default_general_battle(task) -> bool:
    """优先使用任务自身的通用战斗实现，缺失时回退默认 GeneralBattle。

    Args:
        task: 当前触发 `page_battle` hook 的任务实例。

    Returns:
        bool: 通用战斗执行结果。
    """
    battle_takeover = getattr(getattr(task.config, "global_game", None), "battle", None)
    on_takeover = getattr(battle_takeover, "on_takeover", "finish")
    on_takeover_value = getattr(on_takeover, "value", on_takeover)
    battle_config = GeneralBattle.build_quick_exit_config() if on_takeover_value == "exit" else None

    battle_handler = getattr(task, "run_general_battle", None)
    if callable(battle_handler):
        if battle_config is not None:
            return battle_handler(config=battle_config)
        return battle_handler()

    match_page_once = getattr(task, "_match_page_once", None)
    navigator = getattr(task, "navigator", None)
    if not callable(match_page_once) or navigator is None:
        logger.warning("Battle page recognized but no general battle handler is available")
        return False

    fallback = GeneralBattle(config=task.config, device=task.device)
    fallback.navigator = navigator
    fallback._match_page_once = match_page_once
    fallback.current_count = task.current_count
    try:
        if battle_config is not None:
            return fallback.run_general_battle(config=battle_config)
        return fallback.run_general_battle()
    finally:
        task.current_count = fallback.current_count
