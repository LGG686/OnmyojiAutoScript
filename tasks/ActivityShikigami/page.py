from tasks.ActivityShikigami.assets import ActivityShikigamiAssets
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.Component.RightActivity.assets import RightActivityAssets
from tasks.GameUi.action import conditional_action
from tasks.GameUi.default_pages import random_click
from tasks.GameUi.page import Page, page_main, sequence, page_battle, page_battle_prepare, page_reward
from tasks.GlobalGame.assets import GlobalGameAssets

# 爬塔活动主界面
page_act = Page(ActivityShikigamiAssets.I_TO_BATTLE_MAIN)
page_act.add_enter_failure_hooks(RightActivityAssets.I_TOGGLE_BUTTON,
                                 conditional_action(GlobalGameAssets.I_UI_REWARD, random_click),
                                 GlobalGameAssets.I_UI_BACK_RED, ActivityShikigamiAssets.I_SKIP_BUTTON)
page_act.connect(page_main, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_act->page_main")
page_main.connect(page_act, ActivityShikigamiAssets.I_MAIN_GOTO_ACT, key="page_main->page_act")
# 体力爬塔页面
page_act_ap = Page(ActivityShikigamiAssets.I_CLIMB_MODE_AP)
page_act_ap.connect(page_act, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_act_ap->page_act")
page_act.connect(page_act_ap, ActivityShikigamiAssets.I_TO_BATTLE_AP, key="page_act->page_act_ap")
# 爬塔活动第2个页面
page_act_2 = Page(ActivityShikigamiAssets.I_AS_CHECK_MAIN_2)
page_act_2.add_enter_success_hooks(GlobalGameAssets.I_UI_BACK_RED)
page_act.connect(page_act_2, ActivityShikigamiAssets.I_TO_BATTLE_MAIN, key="page_act->page_act_2")
page_act_2.connect(page_act, GlobalGameAssets.I_UI_BACK_CIRCLE, key="page_act_2->page_act")
# 暗黑爬塔页面
page_act_dark = Page(ActivityShikigamiAssets.I_AS_CLOSE_EYE, priority=75)
page_act_dark.add_enter_failure_hooks(GlobalGameAssets.I_UI_BACK_RED)
page_act_dark.add_enter_success_hooks(ActivityShikigamiAssets.I_AS_LOCATE)
page_act_dark.connect(page_act, GlobalGameAssets.I_UI_BACK_CIRCLE, key="page_act_dark->page_act")
page_act_2.connect(page_act_dark, ActivityShikigamiAssets.I_AS_OPEN_EYE, key="page_act_2->page_act_dark")
# 门票爬塔页面
page_act_pass = Page(ActivityShikigamiAssets.I_CLIMB_MODE_PASS)
page_act_pass.connect(page_act_dark, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_act_pass->page_act_2")
page_act_dark.connect(page_act_pass, ActivityShikigamiAssets.I_AS_TO_PASS, key="page_act_dark->page_act_pass")
# 100体爬塔页面
page_act_ap100 = Page(ActivityShikigamiAssets.I_CLIMB_MODE_AP100)
page_act_ap100.add_enter_failure_hooks(GlobalGameAssets.I_UI_BACK_RED)
page_act_ap100.connect(page_act_dark, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_act_ap100->page_act_2")
page_act_dark.connect(page_act_ap100, ActivityShikigamiAssets.O_ENTER_AP100, key="page_act_dark->page_act_ap100")

