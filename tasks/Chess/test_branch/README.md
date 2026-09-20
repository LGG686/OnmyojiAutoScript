# Chess 测试支线

这是文件夹，不是 Git 分支。`MUMU-2` 执行 `Chess` 时加载这里的
`script_task.py`；其他配置继续加载 `tasks/Chess/script_task.py`。

`state.py` 集中保存同一截图的读取结果及每局、每回目的进度；
`decision.py` 从观察和进度生成纯决策；`events.py` 在原回目循环中同步
收集模式变化、回目确认、符咒弹窗和对局结束事件。识别、点击及资源仍
沿用稳定版，不启动并发截图/点击的后台监视线程。
