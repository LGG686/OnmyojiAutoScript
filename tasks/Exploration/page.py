from tasks.Exploration.assets import ExplorationAssets
from tasks.GameUi.action import sequence
from tasks.GameUi.page import (
    all_of,
    any_of,
    page_battle,
    page_battle_prepare,
    page_exploration,
)
from tasks.GameUi.page_definition import Page
from tasks.GlobalGame.assets import GlobalGameAssets


# 探索副本入口：复刻原 Scene.ENTRANCE 的 "两个标志都要命中"，避免和 page_exploration 识别条件重叠
page_exp_entrance = Page(ExplorationAssets.I_E_EXPLORATION_CLICK)

# 探索副本主界面：任一设置/轮换按钮可见即可
page_exp_main = Page(any_of(ExplorationAssets.I_E_SETTINGS_BUTTON, ExplorationAssets.I_E_AUTO_ROTATE_ON,
                            ExplorationAssets.I_E_AUTO_ROTATE_OFF))

page_exp_main.connect(page_exp_entrance,
                      action=sequence(GlobalGameAssets.I_UI_BACK_YELLOW, ExplorationAssets.I_E_EXIT_CONFIRM),
                      key="page_exp_main->page_exp_entrance")
page_exp_entrance.connect(page_exp_main, ExplorationAssets.I_E_EXPLORATION_CLICK, key="page_exp_entrance->page_exp_main")

