from tasks.GameUi.assets import GameUiAssets
from tasks.GameUi.page import (
    Page,
    page_act_list,
    page_battle,
    page_battle_result,
    page_main,
    page_reward,
    page_shikigami_records,
    random_click,
)
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.MetaDemon.assets import MetaDemonAssets

page_act_list_meta_demon = Page(MetaDemonAssets.I_CHECK_ACT_LIST_METADEMON_ACT)
page_act_list.connect(page_act_list_meta_demon, MetaDemonAssets.L_GOTO_METADEMON_LIST, key="page_act_list->page_act_list_meta_demon")
page_act_list_meta_demon.connect(page_main, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_act_list_meta_demon->page_main")

page_meta_demon = Page(MetaDemonAssets.I_MD_CHECK_MAIN_PAGE)
page_meta_demon.add_enter_success_hooks(MetaDemonAssets.I_MD_GET_YESTERDAY_REWARD, MetaDemonAssets.I_MD_CLOSE_POPUP)
page_meta_demon.connect(page_act_list_meta_demon, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_meta_demon->page_act_list_meta_demon")
page_act_list_meta_demon.connect(page_meta_demon, GameUiAssets.I_ACT_LIST_GOTO_ACT, key="page_act_list_meta_demon->page_meta_demon")

page_meta_demon_boss = Page(MetaDemonAssets.I_CHECK_BOSS_PAGE)
page_meta_demon_boss.add_enter_success_hooks(MetaDemonAssets.I_MD_CLOSE_POPUP)
page_meta_demon_boss.connect(page_meta_demon, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_meta_demon_boss->page_meta_demon")
page_meta_demon.connect(page_meta_demon_boss, MetaDemonAssets.I_MD_CHECK_MAIN_PAGE, key="page_meta_demon->page_meta_demon_boss")

page_reward.connect(page_meta_demon_boss, random_click(), key="page_reward->page_meta_demon_boss")
page_battle_result.connect(page_meta_demon_boss, random_click(), key="page_battle_result->page_meta_demon_boss")
