from tasks.Dokan.assets import DokanAssets
from tasks.GameUi.action import sequence
from tasks.GameUi.default_pages import (page_shirin, page_shikigami_records, page_battle, page_battle_result,
                                        page_battle_prepare, page_reward, random_click, page_main)
from tasks.GameUi.matcher import any_of
from tasks.GameUi.page_definition import Page
from tasks.GlobalGame.assets import GlobalGameAssets

# 道馆地图页面
page_dokan_map = Page(any_of(DokanAssets.I_RYOU_DOKAN_FOUND_DOKAN, DokanAssets.I_RYOU_DOKAN_FINDING_DOKAN))
page_shirin.connect(page_dokan_map, DokanAssets.I_SCENE_SHENSHE, key="page_shirin->page_dokan_map")
page_dokan_map.connect(page_shirin, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_dokan_map->page_shirin")


def map_enter_dokan(task) -> bool:
    try_count = 0
    while try_count < 5:
        task.screenshot()
        if task.appear(task.I_RYOU_DOKAN_CHECK):
            return True
        pos = task.O_DOKAN_MAP.ocr_full(task.device.image)
        if pos != (0, 0, 0, 0):
            x = pos[0] + pos[2] / 2  # 取中间
            y = pos[1] - 20  # 往上偏移20
            task.device.click(x=x, y=y, control_name='dokan_map_goto_dokan')
        try_count += 1
    return False


# 道馆页面(必须道馆已经开启才可以调用)
page_dokan = Page(DokanAssets.I_RYOU_DOKAN_CHECK)
page_dokan.connect(page_dokan_map,
                   sequence(DokanAssets.I_RYOU_DOKAN_DOKAN_QUIT, DokanAssets.I_RYOU_DOKAN_EXIT_ENSURE,
                            success_index=1),
                   key="page_dokan->page_dokan_map")
page_dokan_map.connect(page_dokan, action=map_enter_dokan, key="page_dokan_map->page_dokan")

page_dokan.connect(page_shikigami_records, DokanAssets.I_RYOU_DOKAN_SHIKIGAMI, key="page_dokan->page_shikigami_records")
page_shikigami_records.connect(page_dokan, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_shikigami_records->page_dokan")


def priority_enter_dokan(task) -> bool:
    priority_list = [DokanAssets.I_RYOU_DOKAN_ATTACK_PRIORITY_0,
                     DokanAssets.I_RYOU_DOKAN_ATTACK_PRIORITY_1,
                     DokanAssets.I_RYOU_DOKAN_ATTACK_PRIORITY_2,
                     DokanAssets.I_RYOU_DOKAN_ATTACK_PRIORITY_3,
                     DokanAssets.I_RYOU_DOKAN_ATTACK_PRIORITY_4]
    target_priority = priority_list[task.config.dokan.dokan_config.dokan_attack_priority]
    return task.appear_then_click(target_priority, interval=1.2)


# 道馆攻击优先级页面
page_dokan_priority = Page(DokanAssets.I_RYOU_DOKAN_ATTACK_PRIORITY_0, priority=75)
page_dokan.connect(page_dokan_priority, DokanAssets.I_RYOU_DOKAN_ATTACK_PRIORITY, key="page_dokan->page_dokan_priority")
page_dokan_priority.connect(page_dokan, priority_enter_dokan, key="page_dokan_priority->page_dokan")
