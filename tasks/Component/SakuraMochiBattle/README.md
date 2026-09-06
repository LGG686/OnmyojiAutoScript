# SakuraMochiBattle

`SakuraMochiBattle` 是樱饼挂机的只读战斗观察组件。它只在开始时执行一次任务提供的入口动作；确认开启后，只截图并识别准备、战斗、结算、奖励和任务主页，不执行任何后续点击。

支持该方式的任务需要：

1. 将原本继承的 `GeneralBattle` 替换为 `SakuraMochiBattle`。
2. 在任务配置中提供樱饼开关。
3. 在任务素材中提供任务专用的入口、开启态、关闭态和任务主页标志。
4. 构造 `SakuraMochiBattleProfile` 后调用 `run_sakura_mochi_battle()`。

```python
profile = SakuraMochiBattleProfile(
    enabled=self.config.some_task.sakura_mochi_enable,
    entry_action=self.I_TASK_SAKURA_MOCHI,
    active_marker=self.I_TASK_SAKURA_MOCHI_ON,
    inactive_marker=self.I_TASK_SAKURA_MOCHI_OFF,
    task_page_marker=self.I_TASK_FIRE,
    battle_key='some_task_sakura_mochi',
)
summary = self.run_sakura_mochi_battle(profile)
```

`entry_action` 也可以使用 `ActionSequence`，用于需要先打开任务专用面板再点击樱饼开关的入口。组件会先确认任务主页及关闭态，动作序列完成并识别到 `active_marker` 后，再进入严格的无点击观察阶段。`observer` 只应用于任务自身的只读记录，不应执行任何界面操作。
