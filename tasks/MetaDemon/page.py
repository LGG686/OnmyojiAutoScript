"""超鬼王页面定义。

活动入口、活动页与弹窗均由本任务自行识别和处理，不依赖 `page_activity`
的公共活动按钮：在庭院右侧活动栏里直接点超鬼王入口。
"""

import time

from module.base.timer import Timer
from module.logger import logger
from tasks.Component.RightActivity.assets import RightActivityAssets
from tasks.GameUi.page import (
    Page,
    any_of,
    page_battle_result,
    page_main,
    page_reward,
    random_click,
    reward_random_click,
)
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.MetaDemon.assets import MetaDemonAssets

# 庭院右侧活动栏最多尝试切换的轮数。
METADEMON_ENTRY_MAX_TOGGLES = 8
# 活动页弹窗清理的等待上限，单位秒。
METADEMON_OVERLAY_TIMEOUT_SECONDS = 15


def find_metademon_entry(task) -> bool:
    """在庭院右侧活动栏中寻找超鬼王入口，必要时切换栏目。"""
    for _ in range(METADEMON_ENTRY_MAX_TOGGLES):
        task.screenshot()
        if not task.appear(task.I_CHECK_MAIN):
            return False
        if task.appear_then_click(MetaDemonAssets.I_MAIN_GOTO_METADEMON, interval=1):
            return True
        if task.appear_then_click(RightActivityAssets.I_TOGGLE_BUTTON, interval=1):
            time.sleep(0.5)
            continue
        return False

    logger.warning(f'MetaDemon entry not found after {METADEMON_ENTRY_MAX_TOGGLES} column checks')
    return False


def handle_metademon_overlay(task) -> bool:
    """清理昨日奖励与活动弹窗，直到活动页主标志稳定。"""
    timer = Timer(METADEMON_OVERLAY_TIMEOUT_SECONDS).start()
    while not timer.reached():
        task.screenshot()

        if task.appear_then_click(MetaDemonAssets.I_MD_GET_YESTERDAY_REWARD, interval=1):
            continue
        if task.appear_then_click(MetaDemonAssets.I_MD_CLOSE_POPUP, interval=1):
            continue
        if task.appear(MetaDemonAssets.I_MD_CHECK_MAIN_PAGE):
            return True

        time.sleep(0.2)

    logger.warning('MetaDemon activity overlays did not finish within 15s')
    return False


def enter_metademon_boss(task) -> bool:
    """在活动页点鬼王入口，进入鬼王战斗页。"""
    return task.appear_then_click(MetaDemonAssets.I_MD_CHECK_MAIN_PAGE, interval=1)


page_meta_demon_boss = Page(MetaDemonAssets.I_CHECK_BOSS_PAGE)
page_meta_demon_boss.add_enter_success_hooks(MetaDemonAssets.I_MD_CLOSE_POPUP)

# 超鬼王活动页：用本任务自己的入口与弹窗标志识别，优先级高于公共活动页。
# 不把 I_MD_CLOSE_POPUP 放进识别条件：它在鬼王页也会出现，会与目标页抢识别。
page_md_activity = Page(
    any_of(
        MetaDemonAssets.I_MD_CHECK_MAIN_PAGE,
        MetaDemonAssets.I_MD_GET_YESTERDAY_REWARD,
    ),
    priority=70,
)
page_md_activity.add_enter_success_hooks(handle_metademon_overlay)
page_md_activity.connect(page_main, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_md_activity->page_main")
page_main.connect(page_md_activity, find_metademon_entry, key="page_main->page_md_activity")

page_md_activity.connect(page_meta_demon_boss, enter_metademon_boss,
                         key="page_md_activity->page_meta_demon_boss")
page_meta_demon_boss.connect(page_md_activity, GlobalGameAssets.I_UI_BACK_YELLOW,
                             key="page_meta_demon_boss->page_md_activity")

page_reward.connect(
    page_meta_demon_boss,
    reward_random_click(),
    key="page_reward->page_meta_demon_boss",
)
page_battle_result.connect(page_meta_demon_boss, random_click(), key="page_battle_result->page_meta_demon_boss")
