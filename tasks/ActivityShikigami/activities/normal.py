"""当期爬塔独有页面与执行逻辑。"""

from datetime import datetime
import random
import time

from module.exception import GameStuckError
from module.logger import logger
from tasks.ActivityShikigami.assets import ActivityShikigamiAssets
from tasks.ActivityShikigami.base_act import ActivityResourceNotEnough
import tasks.ActivityShikigami.page as pages


class NormalClimbAct:
    """体力、门票、首领和百体四种爬塔战斗。"""

    CLIMB_OCR_REDIRECT_AFTER_CORRECTIONS = 5

    def setup_climb_pages(self):
        page_act = self.navigator.resolve_page(pages.page_act)
        page_climb_main = self.navigator.resolve_page(pages.page_climb_main)
        page_ap = self.navigator.resolve_page(pages.page_climb_ap)
        page_ap100 = self.navigator.resolve_page(pages.page_climb_ap100)
        page_boss = self.navigator.resolve_page(pages.page_climb_boss)
        page_pass = self.navigator.resolve_page(pages.page_climb_pass)

        # 进入边：活动主页直达爬塔主页 / 体力 / 百体 / 首领；门票再经爬塔主页中转。
        page_act.connect(
            page_climb_main,
            ActivityShikigamiAssets.I_TO_BATTLE_MAIN,
            key='activity->climb_main',
        )
        page_act.connect(
            page_ap,
            ActivityShikigamiAssets.I_TO_BATTLE_AP,
            key='activity->climb_ap',
        )
        page_act.connect(
            page_ap100,
            ActivityShikigamiAssets.I_TO_BATTLE_AP100,
            key='activity->climb_ap100',
        )
        page_act.connect(
            page_boss,
            ActivityShikigamiAssets.I_TO_BATTLE_BOSS,
            key='activity->climb_boss',
        )
        page_climb_main.connect(
            page_pass,
            ActivityShikigamiAssets.I_TO_BATTLE_CLIMB,
            key='climb_main->climb_pass',
        )
        # 本期停用边与钩子统一收在文件末尾的「Climb disabled transitions」区块。

    def run_boss(self):
        logger.hr('Start activity: Boss', 1)
        self.setup_climb_pages()
        self._run_climb_type('boss')

    def run_climb(self):
        logger.hr('Start activity: Climb', 1)
        self.setup_climb_pages()
        for action_type in self.conf.general_config.climb_sequence_v:
            if self.time_limit_reached():
                return
            if action_type in ('pass_easy', 'pass_hard'):
                self._run_climb_type('pass', pass_mode=action_type[5:])
            else:
                self._run_climb_type(action_type)

    def _run_climb_type(self, action_type: str, pass_mode: str = None):
        if action_type == 'pass':
            # 门票与体力已分家，门票数量只有门票页能读到，必须先进门票页再统一读数。
            self.goto_page(pages.page_climb_pass)
            remain = self._read_shared_climb_tickets()
            # 指定难度时只执行当前分支；未指定时困难收益优先，任一模式次数为 0 时直接跳过。
            for mode in ((pass_mode,) if pass_mode else ('hard', 'easy')):
                pass_limit = self.conf.general_config.pass_limit_for(mode)
                if pass_limit <= 0:
                    logger.info(f'Skip pass mode {mode}: limit is 0')
                    continue
                if self.time_limit_reached():
                    return
                required = 5 if mode == 'hard' else 1
                if remain < required:
                    logger.info(f'Skip pass mode {mode}: tickets={remain}, required={required}')
                    continue
                self._run_climb_branch(action_type, pass_mode=mode)
                # 两种难度共用门票，前一分支消耗后更新余量再筛选下一分支。
                remain = self._read_shared_climb_tickets()
            self.current_pass_mode = None
            return

        self._run_climb_branch(action_type)

    def _read_shared_climb_tickets(self):
        self.screenshot()
        # 本期活动没有门票选择器空态「+」，停用该判据，只保留 OCR 读数。
        # if self.appear(self.I_ORCHI_SELECT_NONE):
        #     self.climb_consumable_count['pass'] = 0
        #     self.climb_pending_consumption['pass'] = 0
        #     self.climb_ocr_correction_rounds['pass'] = 0
        #     logger.info(
        #         'Climb ticket selector is empty; skip all pass modes'
        #     )
        #     return 0
        return self._update_climb_consumable_count(
            'pass', self.O_REMAIN_PASS.ocr_digit(self.device.image))

    def _run_climb_branch(self, action_type: str, pass_mode: str = None):
        logger.hr(f'Start climb type: {action_type}', 2)
        self.current_action_type = action_type
        self.current_pass_mode = pass_mode
        destination = getattr(pages, f'page_climb_{action_type}')
        self.goto_page(destination)
        if pass_mode is not None:
            self._sync_pass_difficulty(pass_mode)
        self._sync_climb_team_lock(action_type)

        while True:
            if pass_mode is not None:
                mode_limit = self.conf.general_config.pass_limit_for(pass_mode)
                if self.pass_action_count[pass_mode] >= mode_limit:
                    logger.info(
                        f'Pass mode {pass_mode} count limit reached: '
                        f'{self.pass_action_count[pass_mode]}/{mode_limit}'
                    )
                    return
            self.screenshot()
            if self.appear_then_click(self.I_USELESS_MESSAGE_CLOSE, interval=1):
                continue
            if self.appear_then_click(
                self.I_AUTOFIGHT,
                action=self.C_RANDOM_CLOSE_AUTOFIGHT,
                interval=1,
            ):
                continue
            current_page = self.get_current_page()
            if current_page == destination:
                # 五倍卷只支持普通体力战斗，门票等分支不读取也不切换。
                if action_type == 'ap':
                    self._sync_climb_penta_pass()
                if not self.prepare_next_action(action_type):
                    return
                self._handle_climb_drink_break()
                try:
                    self._run_climb_action(action_type, destination)
                except ActivityResourceNotEnough:
                    branch = f'/{pass_mode}' if pass_mode else ''
                    logger.info(
                        f'Climb resource exhausted: {action_type}{branch}'
                    )
                    # 困难门票不足时关闭提示，仅结束困难分支，随后可执行简单模式。
                    self.screenshot()
                    if self.appear_then_click(self.I_UI_BACK_RED, interval=0):
                        self.device.click_record_clear()
                    return
                continue
            if current_page in (pages.page_battle_prepare, pages.page_battle):
                self.run_general_battle(
                    self.battle_config(action_type),
                    battle_key=f'activity_{action_type}',
                )
                continue
            if current_page == pages.page_reward:
                self.click(self._battle_settlement_click(), interval=1.5)
                continue
            if current_page is None:
                time.sleep(0.5)
                continue
            self.goto_page(destination)

    def _start_climb_drink_timer(self, interval_range: tuple[int, int]) -> None:
        limit_minutes = random.randint(*interval_range)
        self._climb_drink_started_at = time.monotonic()
        self._climb_drink_limit_seconds = limit_minutes * 60
        self._climb_drink_interval_range = interval_range
        logger.info(
            'Climb drink timer started: '
            f'limit={limit_minutes}m, '
            f'range={interval_range[0]}-{interval_range[1]}m'
        )

    def _handle_climb_drink_break(self) -> None:
        """爬塔内部连续运行达到间隔后，在下一场开始前暂停。"""
        config = self.conf.general_config
        if not config.climb_drink_break:
            return

        parts = config.climb_drink_interval.split(',')
        interval_range = int(parts[0]), int(parts[1])
        started_at = getattr(self, '_climb_drink_started_at', None)
        previous_range = getattr(self, '_climb_drink_interval_range', None)
        if started_at is None or previous_range != interval_range:
            self._start_climb_drink_timer(interval_range)
            return

        elapsed = time.monotonic() - started_at
        if elapsed < self._climb_drink_limit_seconds:
            return

        if random.random() < 0.9:
            rest_minutes = random.triangular(2, 8, 5)
            branch = 'short'
        else:
            rest_minutes = random.triangular(8, 20, 8)
            branch = 'long_tail'
        rest_seconds = max(120, min(1200, round(rest_minutes * 60)))
        logger.info(
            'Climb drink break started: '
            f'elapsed={elapsed / 60:.1f}m, '
            f'rest={rest_seconds / 60:.1f}m, distribution={branch}'
        )
        rest_started_at = datetime.now()
        time.sleep(rest_seconds)
        # 内部喝水休息不占用式神活动的任务时限。
        self.start_time += datetime.now() - rest_started_at
        logger.info('Climb drink break finished; continue current climb task')
        self._start_climb_drink_timer(interval_range)

    def _run_climb_action(self, action_type: str, destination):
        if not self._climb_resource_available(action_type):
            raise ActivityResourceNotEnough

        soul_action_type = action_type
        if action_type == 'pass' and self.current_pass_mode == 'hard':
            # 困难门票使用独立的御魂预设及切换状态。
            soul_action_type = 'pass_hard'
            logger.info('Pass hard mode uses its own soul preset')
        self.switch_soul_for(
            soul_action_type,
            self.I_BATTLE_MAIN_TO_RECORDS,
            return_page=destination,
            exit_records=True,
        )
        if action_type == 'pass' and self.current_pass_mode is not None:
            # 首次切换御魂返回后重新确认难度，避免页面往返重置选择。
            self._sync_pass_difficulty(self.current_pass_mode)
        entered = self._enter_climb_battle(action_type)
        if not entered:
            raise ActivityResourceNotEnough

        self._record_climb_consumption(action_type)
        self.record_action(action_type)
        if action_type == 'pass' and self.current_pass_mode is not None:
            self.pass_action_count[self.current_pass_mode] += 1
            mode_limit = self.conf.general_config.pass_limit_for(
                self.current_pass_mode
            )
            logger.info(
                f'Pass mode {self.current_pass_mode} action count: '
                f'{self.pass_action_count[self.current_pass_mode]}/{mode_limit}'
            )
        self.run_general_battle(
            self.battle_config(action_type),
            battle_key=f'activity_{action_type}',
        )

    def _climb_fire_rule(self, action_type: str):
        return self._fire_template(action_type)

    def _climb_penta_enabled(self, action_type: str) -> bool:
        """返回当前体力分支是否实际启用了五倍挑战。"""
        return (
            action_type == 'ap'
            and self.penta_pass_active
            and self.climb_consumable_count['penta_pass'] > 0
        )

    def _climb_resource_consumption(self, action_type: str) -> int:
        """返回当前分支一场战斗应消耗的主资源数量。"""
        if action_type == 'ap':
            return 30 if self._climb_penta_enabled(action_type) else 6
        hard_pass = (
            action_type == 'pass'
            and self.current_pass_mode == 'hard'
        )
        return 5 if hard_pass else 1

    def _climb_ap_pass_consumption(self, action_type: str) -> int:
        """返回体力挑战门票的单场消耗量。"""
        return 5 if self._climb_penta_enabled(action_type) else 1

    def _record_climb_consumption(self, action_type: str) -> None:
        """成功进入战斗时保存本场不可变的资源消耗快照。"""
        penta_enabled = self._climb_penta_enabled(action_type)
        resource_consumption = self._climb_resource_consumption(action_type)
        penta_consumption = 1 if penta_enabled else 0
        # 体力不再通过 OCR 跟踪；体力分支只记录并检查活动门票。
        if action_type != 'ap':
            self.climb_pending_consumption[action_type] = resource_consumption
        ap_pass_consumption = '-'
        if action_type == 'ap':
            ap_pass_consumption = self._climb_ap_pass_consumption(action_type)
            self.climb_pending_consumption['ap_pass'] = ap_pass_consumption
        self.climb_pending_consumption['penta_pass'] = penta_consumption
        logger.info(
            'Record climb consumption snapshot: '
            f'resource={action_type}:'
            f'{resource_consumption if action_type != "ap" else "untracked"}, '
            f'ap_pass={ap_pass_consumption}, '
            f'penta_pass={penta_consumption}'
        )

    def _sync_climb_penta_pass(self) -> None:
        """按通用配置及剩余数量同步五倍卷开关。"""
        configured = self.conf.general_config.use_penta_pass
        remain = None
        desired_enabled = False
        pending_consumption = self.climb_pending_consumption['penta_pass']
        if configured or pending_consumption > 0:
            raw_remain = self.O_REMAIN_PENTA_PASS.ocr_digit(
                self.device.image
            )
            remain = self._update_climb_consumable_count(
                'penta_pass', raw_remain
            )
            desired_enabled = configured and remain > 0
            if not desired_enabled:
                logger.info('Climb penta pass exhausted; disable penta mode')

        enabled_rule = self.I_FIGHT_PENTA_USE
        disabled_rule = self.I_FIGHT_PENTA_DISUSE
        target_rule = enabled_rule if desired_enabled else disabled_rule
        click_rule = disabled_rule if desired_enabled else enabled_rule

        for attempt in range(1, 4):
            self.screenshot()
            if self.appear(target_rule):
                self.penta_pass_active = desired_enabled
                logger.debug(
                    'Climb penta mode synchronized: '
                    f'enabled={desired_enabled}, remain={remain}'
                )
                return
            if not self.appear(click_rule):
                self.penta_pass_active = self.appear(enabled_rule)
                logger.warning(
                    'Cannot identify climb penta toggle state; '
                    f'enabled={desired_enabled}, remain={remain}'
                )
                return
            self.click(click_rule, interval=0)
            time.sleep(0.5)
            logger.debug(
                'Toggle climb penta mode: '
                f'enabled={desired_enabled}, attempt={attempt}/3'
            )

        logger.warning(
            'Failed to synchronize climb penta mode after 3 attempts: '
            f'enabled={desired_enabled}, remain={remain}'
        )
        self.screenshot()
        self.penta_pass_active = self.appear(enabled_rule)

    def _sync_pass_difficulty(self, mode: str) -> None:
        """点击并确认门票简单/困难分支，失败三次后报错。"""
        if mode == 'hard':
            target_rule = self.I_CHECK_CLIMB_HARD
            click_rule = self.C_CL_SELECT_HARD
        elif mode == 'easy':
            target_rule = self.I_CHECK_CLIMB_EASY
            click_rule = self.C_CL_SELECT_EASY
        else:
            raise ValueError(f'Unsupported pass mode: {mode}')

        for attempt in range(1, 4):
            self.screenshot()
            if self.appear(target_rule):
                logger.info(f'Pass mode ready: {mode}')
                return
            self.click(click_rule, interval=0)
            if self.wait_until_appear(target_rule, wait_time=3):
                self.device.click_record_clear()
                logger.info(
                    f'Pass mode selected: {mode}, attempt={attempt}/3'
                )
                return
            logger.warning(
                f'Pass mode selection timeout: {mode}, attempt={attempt}/3'
            )

        raise GameStuckError(
            f'Failed to select pass mode {mode} after 3 attempts'
        )

    @staticmethod
    def _normalize_climb_consumable_count(
            name: str,
            raw_count: int,
            previous_count: int,
            expected_consumption: int,
    ) -> int:
        """根据上一场消耗快照修正任意爬塔资源的 OCR 异常下降。"""
        if previous_count < 0:
            if raw_count <= 0:
                logger.info(
                    f'Climb {name} count is 0 on entry; resource exhausted'
                )
            return max(raw_count, 0)

        if expected_consumption <= 0:
            return max(raw_count, 0)

        expected_count = max(previous_count - expected_consumption, 0)
        if raw_count < expected_count:
            logger.warning(
                f'Climb {name} OCR decreased beyond consumption snapshot: '
                f'previous={previous_count}, raw={raw_count}, '
                f'consumption={expected_consumption}, '
                f'corrected={expected_count}'
            )
            return expected_count

        if raw_count < previous_count:
            logger.info(
                f'Climb {name} count decreased: '
                f'{previous_count} -> {raw_count}, '
                f'expected_consumption={expected_consumption}'
            )
        return raw_count

    def _update_climb_consumable_count(
            self, name: str, raw_count: int
    ) -> int:
        """用公共修复器更新一种爬塔资源，并消费其待确认快照。"""
        previous_count = self.climb_consumable_count[name]
        expected_consumption = self.climb_pending_consumption[name]
        expected_count = max(previous_count - expected_consumption, 0)
        correction_required = (
            previous_count >= 0
            and expected_consumption > 0
            and raw_count < expected_count
        )
        if correction_required:
            correction_rounds = self.climb_ocr_correction_rounds[name] + 1
            self.climb_ocr_correction_rounds[name] = correction_rounds
        else:
            correction_rounds = 0
            self.climb_ocr_correction_rounds[name] = 0

        if (
            correction_required
            and correction_rounds
            >= self.CLIMB_OCR_REDIRECT_AFTER_CORRECTIONS
        ):
            remain = max(raw_count, 0)
            self.climb_ocr_correction_rounds[name] = 0
            logger.warning(
                f'Climb {name} OCR stayed abnormal for '
                f'{correction_rounds} rounds; redirect cached count: '
                f'previous={previous_count}, raw={raw_count}, '
                f'expected={expected_count}'
            )
        else:
            remain = self._normalize_climb_consumable_count(
                name=name,
                raw_count=raw_count,
                previous_count=previous_count,
                expected_consumption=expected_consumption,
            )
        self.climb_consumable_count[name] = remain
        self.climb_pending_consumption[name] = 0
        logger.info(
            f'Climb {name} remain: raw={raw_count}, normalized={remain}, '
            f'previous={previous_count}, '
            f'expected_consumption={expected_consumption}, '
            f'correction_rounds={correction_rounds}'
        )
        return remain

    def _enter_climb_battle(self, action_type: str) -> bool:
        click_times = 0
        miss_times = 0
        max_times = random.randint(3, 5)
        while True:
            self.screenshot()
            if self.is_in_battle(False):
                return True
            if click_times >= max_times:
                logger.warning(f'{action_type} cannot enter battle, click reach max times')
                raise ActivityResourceNotEnough
            if self.appear_then_click(self.I_UI_BACK_RED, interval=2):
                # boss 打出超过历史最高伤害时会弹出提示浮层，关掉继续挑战；
                # 连续 3 轮仍未进入战斗才按资源耗尽处理
                self.device.click_record_clear()
                miss_times += 1
                logger.info(f'Close unexpected dialog, retry {action_type} fire')
                if miss_times >= self.MAX_FIRE_MISS:
                    logger.warning(f'{action_type} dialog keeps appearing, treat as resource exhausted')
                    raise ActivityResourceNotEnough
                continue
            if self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=1) or \
                    self.appear_then_click(self.I_UI_CONFIRM, interval=1):
                continue
            fire_rule = self._climb_fire_rule(action_type)
            if fire_rule is None:
                miss_times += 1
                if miss_times >= self.MAX_FIRE_MISS:
                    logger.warning(f'{action_type} fire button not found by ocr for {miss_times} rounds')
                    raise ActivityResourceNotEnough
                continue
            if self.appear_then_click(fire_rule, interval=1):
                self.device.click_record_clear()
                click_times += 1
                miss_times = 0
                logger.info(f'Try click fire, remain times[{max_times - click_times}]')
            elif self.interval_timer[fire_rule.name].reached():
                # 节流窗口已过仍未命中才算一次未命中，并重新计时，避免刷帧把偶发抖动算进去
                miss_times += 1
                self.interval_timer[fire_rule.name].reset()
                if miss_times >= self.MAX_FIRE_MISS:
                    logger.warning(f'{action_type} fire button not matched for {miss_times} rounds')
                    raise ActivityResourceNotEnough

    def _sync_climb_team_lock(self, action_type: str):
        """
        同步阵容的锁定状态

        锁定图标存在两套外观，这里取并集识别，任意一套命中即可
        """
        enable = self.battle_config(action_type).lock_team_enable
        locks = [self.I_LOCK_1, self.I_LOCK_2]
        unlocks = [self.I_UNLOCK_1, self.I_UNLOCK_2]
        if enable:
            logger.info(f'Lock {action_type} team')
            click_rules, stop_rules = unlocks, locks
        else:
            logger.info(f'Unlock {action_type} team')
            click_rules, stop_rules = locks, unlocks
        while 1:
            self.screenshot()
            if any(self.appear(rule) for rule in stop_rules):
                break
            if any(self.appear_then_click(rule, interval=1.5) for rule in click_rules):
                continue

    def _climb_resource_available(self, action_type: str) -> bool:
        logger.hr(f'Check {action_type} resource')
        self.screenshot()
        if action_type == 'pass':
            raw_remain = self.O_REMAIN_PASS.ocr_digit(self.device.image)
        elif action_type == 'ap':
            raw_ap_pass = self.O_REMAIN_AP_PASS.ocr_digit(
                self.device.image
            )
        elif action_type == 'boss':
            _, raw_remain, _ = self.O_REMAIN_BOSS.ocr_digit_counter(self.device.image)
        else:
            raw_remain = self.O_REMAIN_AP100.ocr_digit(self.device.image)

        remain = None
        if action_type != 'ap':
            remain = self._update_climb_consumable_count(
                action_type, raw_remain
            )
        ap_pass_remain = None
        if action_type == 'ap':
            ap_pass_remain = self._update_climb_consumable_count(
                'ap_pass', raw_ap_pass
            )
        required = (
            self._climb_resource_consumption(action_type)
            if action_type != 'ap'
            else None
        )
        ap_pass_required = (
            self._climb_ap_pass_consumption(action_type)
            if action_type == 'ap'
            else None
        )
        if (remain is not None and remain < required) or (
            ap_pass_remain is not None
            and ap_pass_remain < ap_pass_required
        ):
            logger.info(
                f'Climb {action_type} resource below branch requirement: '
                f'remain={remain}, required={required}, '
                f'ap_pass_remain={ap_pass_remain}, '
                f'ap_pass_required={ap_pass_required}, '
                f'mode={self.current_pass_mode}'
            )
            return False
        return True


# ---------------------------------------------------------------------------
# Climb disabled transitions
#
# 本期活动布局变更后停用，与 setup_climb_pages() 配套：
#   - 体力 / 百体已改为活动主页直达，不再经由爬塔主页；门票仍走爬塔主页中转
#   - 同一爬塔界面内切换模式的机制已不存在，模式纠正钩子一并停用
# 若后续活动改回「爬塔主页 + 内部模式切换」的旧布局，把下面内容移回
# setup_climb_pages() 取消注释即可（其中 page_ap / page_pass 是该函数内
# resolve_page 得到的 session 副本，模块级无法直接引用）。
#
# page_climb_main.connect(
#     page_ap,
#     ActivityShikigamiAssets.I_TO_BATTLE_CLIMB,
#     key='climb_main->climb_ap',
# )
# page_ap.add_enter_failure_hooks(pages.conditional_action(
#     condition=ActivityShikigamiAssets.I_CLIMB_MODE_PASS,
#     action=ActivityShikigamiAssets.I_CLIMB_MODE_SWITCH,
# ))
# page_pass.add_enter_failure_hooks(pages.conditional_action(
#     condition=ActivityShikigamiAssets.I_CLIMB_MODE_AP,
#     action=ActivityShikigamiAssets.I_CLIMB_MODE_SWITCH,
# ))
# page_pass.connect(page_ap, ActivityShikigamiAssets.I_CLIMB_MODE_SWITCH, key='climb_pass->climb_ap')
# page_ap.connect(page_pass, ActivityShikigamiAssets.I_CLIMB_MODE_SWITCH, key='climb_ap->climb_pass')
#
# 另有 _read_shared_climb_tickets() 内停用的门票选择器空态判据
# （I_ORCHI_SELECT_NONE），因与函数内计数逻辑绑定，保留在原处。
# ---------------------------------------------------------------------------
