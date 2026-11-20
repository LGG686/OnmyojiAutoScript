# This Python file uses the following encoding: utf-8
"""半自动点击：按规则表点按钮，认出战斗页就交给通用战斗。

常驻工具而不是调度任务：运行时由 `/android/tool/start?name=semi_auto` 拉起，用户停之前
一直循环。循环只做三件事——截图、认战斗页、按规则表点第一个命中的按钮；认到准备页或
战斗中页就整场交给 `run_general_battle`，打完自动回到点击循环。

规则表直接引用各任务现有的资产对象，不再另建一份 assets.py：`RuleImage` 只是「文件 +
ROI + 阈值」的描述，多个任务共用同一个对象没有副作用（`interval_timer` 按对象名分开，
而且工具跑在独立进程里）。挑战按钮按圈定的集合整表列出；按钮各自带着
原来的 `roi_back`，只在它该出现的位置匹配，避免不同界面的「挑战」互相误命中。

Semi-auto clicking: match a rule table and click, hand battle pages to GeneralBattle.

A long-running tool rather than a scheduled task: the runtime starts it through
`/android/tool/start?name=semi_auto` and it loops until stopped. Each round only
screenshots, detects a battle page, and clicks the first matching rule; a prepare/
battle page is handed to `run_general_battle` for the whole fight and the click loop
resumes afterwards.

The rule table references the other tasks' asset objects directly — there is no
`semi_auto/assets.py`. A `RuleImage` is just (file, ROI, threshold); sharing one
instance across tasks is harmless (timers are keyed by object name and the tool runs
in its own process). Every screen's challenge button looks different, so all of them
are listed; each keeps its original `roi_back` so it only matches where it belongs.
"""
import tasks.GameUi.page as pages
from module.logger import logger
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.GeneralInvite.assets import GeneralInviteAssets
from tasks.DyeTrials.assets import DyeTrialsAssets
from tasks.EternitySea.assets import EternitySeaAssets
from tasks.EvoZone.assets import EvoZoneAssets
from tasks.FallenSun.assets import FallenSunAssets
from tasks.GameUi.navigator import GameUi
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.GoryouRealm.assets import GoryouRealmAssets
from tasks.LBS.assets import LBSAssets
from tasks.Orochi.assets import OrochiAssets
from tasks.RealmRaid.assets import RealmRaidAssets


class SemiAuto(GeneralBattle, GameUi):
    """出现即点击的常驻工具；战斗交给通用战斗，打完回到点击循环。"""

    # 规则表：从上到下尝试，命中一个就结束本轮，避免一帧连点多个按钮。
    # Rule table: tried top-down; the first hit ends the round so one frame never
    # clicks two buttons.
    def _rules(self):
        return (
            # 各玩法副本的挑战按钮（每个界面的按钮长得都不一样，逐一引用）
            DyeTrialsAssets.I_FP_CHALLENGE,  # 副本右下「挑战」
            OrochiAssets.I_OROCHI_FIRE,  # 八岐大蛇 / 御魂组队「挑战」
            GeneralInviteAssets.I_FIRE,  # 通用组队房间金色「挑战」
            LBSAssets.I_LBS_TEAM_CHALLENGE,  # 连拔山组队「挑战」
            EvoZoneAssets.I_EVOZONE_FIRE,  # 觉醒副本
            RealmRaidAssets.I_FIRE,  # 业原火
            EternitySeaAssets.I_ETERNITY_SEA_FIRE,  # 永生之海
            FallenSunAssets.I_FALLEN_SUN_FIRE,  # 日轮之陨
            GoryouRealmAssets.I_GR_FIRE,  # 御灵
            # 通用确认
            GlobalGameAssets.I_UI_CONFIRM,  # 弹窗「确定」
        )

    def __init__(self, config, device) -> None:
        super().__init__(config, device)
        # 常驻循环没有「任务结束」这一说，卡死判定会把它误杀，所以只关这一项。
        # 注意不能调 disable_stuck_detection()：它会把 click_record_check 一起换成空函数，
        # 连点保护就没了——游戏没反应时工具会一直点下去。保留 click_record_check 后，
        # 同一按钮累计 10 次（或两个按钮交替各 6 次）会抛 GameTooManyClickError 终止工具。
        #
        # A resident loop has no "task finished", so stuck detection would kill it — disable
        # only that. Do not call disable_stuck_detection(): it also blanks
        # click_record_check, and the "same button clicked ten times" guard
        # (GameTooManyClickError) is exactly what stops a dead-end click loop.
        self.device.stuck_record_check = lambda *args, **kwargs: False

    def _battle_page(self):
        """只认准备页与战斗中页；结算/奖励交给通用战斗内部处理，普通弹窗不算战斗。"""
        return GameUi.detect_page_in(
            self, pages.page_battle_prepare, pages.page_battle, include_global=False)

    def _click_rule_once(self) -> bool:
        """按规则表点一次；命中返回 True。"""
        for rule in self._rules():
            if self.appear_then_click(rule, interval=1.5):
                logger.info(f'Semi auto: click {rule.name}')
                return True
        return False

    def run(self) -> None:
        logger.hr('Semi auto', 0)
        logger.info('Semi auto: watching for rules and battle pages')
        while True:
            self.screenshot()
            if self._battle_page():
                logger.info('Semi auto: battle detected, handed over to general battle')
                self.run_general_battle()
                continue
            self._click_rule_once()
